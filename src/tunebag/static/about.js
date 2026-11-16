(() => {
  "use strict";

  /** @typedef {{ id: string, label: string, layer: number, col: number, summary: string, points?: string[] }} Concept */
  /** @typedef {{ from: string, to: string, label: string, dashed?: boolean, route?: string, labelT?: number }} Edge */

  /**
   * Layout (top → bottom only; Event log / Catalog centered; Artist–Mix cluster on the right):
   *
   *   Peer —— Device
   *     \       |  \
   *   Locator  Event log                     Artist
   *              |                              |
   *           Catalog ————— contains ———————— Mix
   *              |                          /  |  \
   *            Intent                     Tag Rating Reject
   *              |
   *           Sequence → Assignment → Cache → Player
   *                                         ↑ holds (Device)
   */
  /** @type {Concept[]} */
  const CONCEPTS = [
    {
      id: "peer",
      label: "Peer",
      layer: 0,
      col: 0.08,
      summary:
        "Another Device that has paired with this one and is reachable over LAN or USB, usable as a file source.",
      points: [
        "Trust comes from pairing (QR or short code), not from a Locator.",
        "Peers exchange the Event log when they can reach each other.",
      ],
    },
    {
      id: "device",
      label: "Device",
      layer: 0,
      col: 0.28,
      summary:
        "A Tunebag installation with a stable Identity (device_id + keypair) that authors Event log entries.",
      points: [
        "Identity is not a network address.",
        "Holds Cache files for its Assignments.",
        "Local-only: File bytes, Metered flag, private key material.",
      ],
    },
    {
      id: "locator",
      label: "Locator",
      layer: 1,
      col: 0.08,
      summary:
        "An ephemeral reachability hint for a Device (HTTP URL, IP:port, USB path, …).",
      points: [
        "Locators change with the network; they are not Identity.",
        "A Locator never grants trust — key proof is required before sync.",
      ],
    },
    {
      id: "event-log",
      label: "Event log",
      layer: 1,
      col: 0.48,
      summary:
        "The source of truth for Catalog: a signed append-only stream of catalog changes, replicated between paired Peers.",
      points: [
        "Same events ⇒ same Catalog, independent of apply order (per-type deterministic merge).",
        "Paired Devices exchange the Event log (peer sync); audio does not travel in it.",
      ],
    },
    {
      id: "artist",
      label: "Artist",
      layer: 1,
      col: 0.84,
      summary:
        "A source-platform creator whose own uploads are ingested into the Catalog.",
      points: ["Own uploads become Mixes in the Catalog.", "Delete of an Artist is sticky across Devices."],
    },
    {
      id: "mix",
      label: "Mix",
      layer: 2,
      col: 0.84,
      summary:
        "One audio file treated as a single listening item (typically a DJ set). Budgets and Played use its duration.",
      points: [
        "May carry Tags, Rating, Reject, Played, Last heard, and Playhead.",
        "Album-style releases are later; not in this map.",
      ],
    },
    {
      id: "catalog",
      label: "Catalog",
      layer: 2,
      col: 0.48,
      summary:
        "The projected, fully replicated metadata on every paired Device. Derived only from the Event log.",
      points: [
        "Includes Artists, Mixes, Tags, Ratings, Rejects, play history, Intents, Sequences, Assignments.",
        "Disposable: rebuilt by replaying the Event log.",
      ],
    },
    {
      id: "tag",
      label: "Tag",
      layer: 3,
      col: 0.70,
      summary: "A free-text label on a Mix. Suggestions prefer existing tags.",
      points: ["Intent membership uses AND of required Tags.", "Unrated Mixes may still match a tagged Intent."],
    },
    {
      id: "rating",
      label: "Rating",
      layer: 3,
      col: 0.84,
      summary: "Score 1–5 on a Mix (UI may show ★). Separate from Reject.",
      points: [
        "Rating distribution on an Intent sets draw chances including unrated.",
        "Default distribution: 0.3 / 0.2 / 0.1 / 0.05 / 0.05 / 0.3 (5★…1★, unrated).",
      ],
    },
    {
      id: "reject",
      label: "Reject",
      layer: 3,
      col: 0.96,
      summary:
        "“Never assign again” until Un-reject. After a 20s local undo window, File bytes are deleted on every Device.",
      points: [
        "Un-reject clears Reject so the Mix may re-enter Sequences.",
        "Un-reject does not by itself restore File bytes — Cache fill runs when assigned again.",
      ],
    },
    {
      id: "intent",
      label: "Intent",
      layer: 3,
      col: 0.48,
      summary:
        "A shared plan: tag filter plus rating distribution. Devices attach hours and optional expiry.",
      points: [
        "Membership uses AND of required Tags.",
        "Rating distribution draws across 5★…1★ and unrated (must sum to 1).",
        "All Devices sharing an Intent share one seeded Sequence.",
      ],
    },
    {
      id: "sequence",
      label: "Sequence",
      layer: 4,
      col: 0.48,
      summary:
        "A seeded ordered list of Mixes for one Intent. Fills until cumulative duration meets the largest Device budget.",
      points: ["May include the Mix that crosses the budget.", "Smaller Device budgets cover the opening stretch."],
    },
    {
      id: "assignment",
      label: "Assignment",
      layer: 5,
      col: 0.48,
      summary:
        "Which Device hours cover which prefix of the Sequence — independent of whether audio is on disk.",
      points: ["Drives what the Cache should hold.", "Built from Device hours on the shared Sequence."],
    },
    {
      id: "cache",
      label: "Cache",
      layer: 6,
      col: 0.48,
      summary:
        "The set of Files (audio bytes) a Device currently holds for its Assignments.",
      points: [
        "Filled from origin, Peer, or USB as needed by Assignments.",
        "Metered mode caps origin downloads to the current Mix + one ahead per Intent.",
      ],
    },
    {
      id: "player",
      label: "Player",
      layer: 7,
      col: 0.48,
      summary:
        "Local playback of cached audio. In v1 it is the source of play, rating, reject, tag, and playhead signals.",
      points: [
        "Plays Files from the Cache (ffplay / afplay).",
        "Closing the companion page does not stop playback.",
        "Playhead, Played, and Last heard are written from listening here.",
      ],
    },
  ];

  /** @type {Edge[]} */
  const EDGES = [
    { from: "peer", to: "device", label: "paired", route: "right" },
    { from: "device", to: "locator", label: "reachability", dashed: true, route: "down-enter-right" },
    { from: "device", to: "event-log", label: "authors" },
    { from: "event-log", to: "device", label: "peer sync", dashed: true, route: "up-enter-right" },
    { from: "device", to: "cache", label: "holds", route: "down-then-across" },
    { from: "event-log", to: "catalog", label: "projects" },
    { from: "catalog", to: "intent", label: "contains", dashed: true },
    { from: "catalog", to: "mix", label: "contains", dashed: true, route: "right" },
    { from: "artist", to: "mix", label: "owns" },
    { from: "mix", to: "tag", label: "has" },
    { from: "mix", to: "rating", label: "has", labelT: 0.72 },
    { from: "mix", to: "reject", label: "may" },
    { from: "intent", to: "sequence", label: "builds" },
    { from: "sequence", to: "assignment", label: "prefix" },
    { from: "assignment", to: "cache", label: "needs" },
    { from: "cache", to: "player", label: "plays" },
  ];

  const byId = Object.fromEntries(CONCEPTS.map((c) => [c.id, c]));

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function renderArticles(host) {
    host.replaceChildren();
    for (const concept of CONCEPTS) {
      const article = document.createElement("article");
      article.id = `concept-${concept.id}`;
      article.className = "concept-article";
      article.dataset.conceptId = concept.id;

      const h3 = document.createElement("h3");
      h3.textContent = concept.label;
      article.appendChild(h3);

      const p = document.createElement("p");
      p.textContent = concept.summary;
      article.appendChild(p);

      if (concept.points?.length) {
        const ul = document.createElement("ul");
        for (const point of concept.points) {
          const li = document.createElement("li");
          li.textContent = point;
          ul.appendChild(li);
        }
        article.appendChild(ul);
      }

      host.appendChild(article);
    }
  }

  function highlightArticle(id) {
    const article = document.getElementById(`concept-${id}`);
    if (!article) return;
    document
      .querySelectorAll(".concept-article.is-highlight")
      .forEach((el) => el.classList.remove("is-highlight"));
    article.classList.add("is-highlight");
    article.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
    window.setTimeout(() => article.classList.remove("is-highlight"), 1600);
  }

  /**
   * @param {string} label
   */
  function measureNode(label) {
    const charW = 7.1;
    const padX = 16;
    const w = Math.max(76, Math.ceil(label.length * charW + padX * 2));
    const h = 34;
    return { w, h };
  }

  /**
   * @param {HTMLElement} host
   */
  function renderGraph(host) {
    const width = Math.max(host.clientWidth || 720, 720);
    const layerGap = 86;
    const topPad = 24;
    const bottomPad = 32;
    const sidePad = 36;
    const layers = Math.max(...CONCEPTS.map((c) => c.layer)) + 1;
    const height = topPad + bottomPad + (layers - 1) * layerGap + 34;

    /** @type {Record<string, { x: number, y: number, w: number, h: number, cx: number, cy: number }>} */
    const box = {};
    for (const concept of CONCEPTS) {
      const { w, h } = measureNode(concept.label);
      const cx = sidePad + concept.col * (width - sidePad * 2);
      const cy = topPad + h / 2 + concept.layer * layerGap;
      box[concept.id] = { x: cx - w / 2, y: cy - h / 2, w, h, cx, cy };
    }

    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", String(height));
    svg.setAttribute("role", "group");
    svg.setAttribute("aria-label", "Tunebag concept relationships");
    svg.classList.add("concept-graph-svg");

    const defs = document.createElementNS(svgNS, "defs");
    // Tip sits at path end (refX = tip). Active variants exist because marker fill
    // cannot be restyled via .is-active on the referencing edge.
    for (const [id, cls] of [
      ["concept-arrow", "concept-arrow-head"],
      ["concept-arrow-muted", "concept-arrow-head is-dashed"],
      ["concept-arrow-active", "concept-arrow-head is-active"],
      ["concept-arrow-muted-active", "concept-arrow-head is-dashed is-active"],
    ]) {
      const marker = document.createElementNS(svgNS, "marker");
      marker.setAttribute("id", id);
      marker.setAttribute("viewBox", "0 0 10 10");
      marker.setAttribute("refX", "9");
      marker.setAttribute("refY", "5");
      marker.setAttribute("markerWidth", "8");
      marker.setAttribute("markerHeight", "8");
      marker.setAttribute("orient", "auto");
      marker.setAttribute("markerUnits", "userSpaceOnUse");
      marker.setAttribute("overflow", "visible");
      const arrowPath = document.createElementNS(svgNS, "path");
      arrowPath.setAttribute("d", "M 0 0 L 9 5 L 0 10 Z");
      arrowPath.setAttribute("class", cls);
      marker.appendChild(arrowPath);
      defs.appendChild(marker);
    }
    svg.appendChild(defs);

    function markerFor(edge, active) {
      if (edge.dashed) {
        return active ? "url(#concept-arrow-muted-active)" : "url(#concept-arrow-muted)";
      }
      return active ? "url(#concept-arrow-active)" : "url(#concept-arrow)";
    }

    function syncEdgeMarker(el, edge, active) {
      const line = el.querySelector(".concept-edge-line");
      if (line) line.setAttribute("marker-end", markerFor(edge, active));
    }

    const edgeLayer = document.createElementNS(svgNS, "g");
    edgeLayer.classList.add("concept-edges");
    svg.appendChild(edgeLayer);

    const nodeLayer = document.createElementNS(svgNS, "g");
    nodeLayer.classList.add("concept-nodes");
    svg.appendChild(nodeLayer);

    /** @type {Map<string, SVGElement>} */
    const edgeEls = new Map();
    /** @type {Map<string, SVGGElement>} */
    const nodeEls = new Map();

    function edgeKey(e) {
      return `${e.from}->${e.to}:${e.label}`;
    }

    /**
     * Orthogonal routes. Default flow is top→bottom; `route: "up"` is the explicit sync back-edge.
     * @param {typeof box[string]} a
     * @param {typeof box[string]} b
     * @param {Edge} edge
     */
    function routePath(a, b, edge) {
      // Same small clearance at path start and arrow tip (marker tip sits on path end).
      const gap = 3;
      const route = edge.route || "down";

      if (route === "right") {
        // Same-row (or nearly): leave right side → enter left side. Nudge down if target is lower.
        const x1 = a.x + a.w + gap;
        const y1 = a.cy;
        const x2 = b.x - gap;
        const y2 = Math.max(a.cy, b.cy);
        if (Math.abs(y2 - y1) < 1) {
          return { d: `M ${x1} ${y1} L ${x2} ${y2}`, lx: (x1 + x2) / 2, ly: y1 - 11 };
        }
        const midX = (x1 + x2) / 2;
        return {
          d: `M ${x1} ${y1} L ${midX} ${y1} L ${midX} ${y2} L ${x2} ${y2}`,
          lx: midX,
          ly: (y1 + y2) / 2,
        };
      }

      if (route === "up-enter-right") {
        // Event log → Device: up from Event log's right half (clear of "authors"), then into Device from the right.
        const x1 = Math.min(a.x + a.w - 8, a.cx + 20);
        const y1 = a.y - gap;
        const y2 = b.cy;
        const x2 = b.x + b.w + gap;
        return {
          d: `M ${x1} ${y1} L ${x1} ${y2} L ${x2} ${y2}`,
          lx: (x1 + x2) / 2,
          ly: y2 - 10,
        };
      }

      if (route === "down-enter-right") {
        // Device → Locator: straight down from Device, then left into Locator's right side.
        const x1 = a.cx;
        const y1 = a.y + a.h + gap;
        const y2 = b.cy;
        const x2 = b.x + b.w + gap;
        return {
          d: `M ${x1} ${y1} L ${x1} ${y2} L ${x2} ${y2}`,
          lx: (x1 + x2) / 2,
          ly: y2 - 10,
        };
      }

      if (route === "down-then-across") {
        // Device → Cache: drop under Device, then across into Cache (never left of Device).
        const x1 = a.cx;
        const y1 = a.y + a.h + gap;
        const x2 = b.cx;
        const y2 = b.y - gap;
        const approachY = Math.min(y2 - 6, b.y - 20);
        return {
          d: `M ${x1} ${y1} L ${x1} ${approachY} L ${x2} ${approachY} L ${x2} ${y2}`,
          lx: (x1 + x2) / 2,
          ly: approachY - 10,
        };
      }

      // Default: leave bottom → enter top. Elbow y is always between endpoints (never above start).
      const x1 = a.cx;
      const y1 = a.y + a.h + gap;
      const x2 = b.cx;
      const y2 = b.y - gap;
      if (y2 <= y1) {
        // Same band fallback: horizontal-ish via a slight down-then-across (still not up).
        const y = y1 + 12;
        return {
          d: `M ${x1} ${y1} L ${x1} ${y} L ${x2} ${y} L ${x2} ${Math.max(y, y2)}`,
          lx: (x1 + x2) / 2,
          ly: y - 10,
        };
      }
      if (Math.abs(x1 - x2) < 2) {
        const t = edge.labelT ?? 0.5;
        return { d: `M ${x1} ${y1} L ${x2} ${y2}`, lx: x1 + 18, ly: y1 + (y2 - y1) * t };
      }
      // Shared elbow height for siblings (e.g. Mix → Tag / Reject).
      const midY = y1 + (y2 - y1) * 0.45;
      return {
        d: `M ${x1} ${y1} L ${x1} ${midY} L ${x2} ${midY} L ${x2} ${y2}`,
        lx: (x1 + x2) / 2,
        ly: midY - 10,
      };
    }

    for (const edge of EDGES) {
      const a = box[edge.from];
      const b = box[edge.to];
      if (!a || !b) continue;

      const g = document.createElementNS(svgNS, "g");
      g.classList.add("concept-edge");
      if (edge.dashed) g.classList.add("is-dashed");
      g.dataset.from = edge.from;
      g.dataset.to = edge.to;

      const { d, lx, ly } = routePath(a, b, edge);
      const hit = document.createElementNS(svgNS, "path");
      hit.setAttribute("d", d);
      hit.classList.add("concept-edge-hit");
      g.appendChild(hit);

      const path = document.createElementNS(svgNS, "path");
      path.setAttribute("d", d);
      path.classList.add("concept-edge-line");
      path.setAttribute(
        "marker-end",
        edge.dashed ? "url(#concept-arrow-muted)" : "url(#concept-arrow)",
      );
      g.appendChild(path);

      const label = document.createElementNS(svgNS, "text");
      label.setAttribute("x", String(lx));
      label.setAttribute("y", String(ly));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("dominant-baseline", "middle");
      label.classList.add("concept-edge-label");
      label.textContent = edge.label;
      g.appendChild(label);

      edgeLayer.appendChild(g);
      edgeEls.set(edgeKey(edge), g);
    }

    function clearHighlight() {
      for (const [key, el] of edgeEls) {
        const edge = EDGES.find((e) => edgeKey(e) === key);
        el.classList.remove("is-active", "is-dim");
        if (edge) syncEdgeMarker(el, edge, false);
      }
      for (const el of nodeEls.values()) {
        el.classList.remove("is-active", "is-related", "is-dim");
      }
    }

    /** Highlight a node and every edge/node it touches. */
    function setActiveNode(id, on) {
      if (!on) {
        clearHighlight();
        return;
      }
      for (const [key, el] of edgeEls) {
        const edge = EDGES.find((e) => edgeKey(e) === key);
        if (!edge) continue;
        const related = edge.from === id || edge.to === id;
        el.classList.toggle("is-active", related);
        el.classList.toggle("is-dim", !related);
        syncEdgeMarker(el, edge, related);
      }
      for (const [nid, el] of nodeEls) {
        const related =
          nid === id ||
          EDGES.some((e) => (e.from === id && e.to === nid) || (e.to === id && e.from === nid));
        el.classList.toggle("is-active", nid === id);
        el.classList.toggle("is-related", related && nid !== id);
        el.classList.toggle("is-dim", !related);
      }
    }

    /** Highlight one edge and its two endpoints. */
    function setActiveEdge(fromId, toId, on) {
      if (!on) {
        clearHighlight();
        return;
      }
      for (const [key, el] of edgeEls) {
        const edge = EDGES.find((e) => edgeKey(e) === key);
        if (!edge) continue;
        const related = edge.from === fromId && edge.to === toId;
        el.classList.toggle("is-active", related);
        el.classList.toggle("is-dim", !related);
        syncEdgeMarker(el, edge, related);
      }
      for (const [nid, el] of nodeEls) {
        const endpoint = nid === fromId || nid === toId;
        el.classList.toggle("is-active", endpoint);
        el.classList.toggle("is-related", false);
        el.classList.toggle("is-dim", !endpoint);
      }
    }

    for (const [key, el] of edgeEls) {
      const edge = EDGES.find((e) => edgeKey(e) === key);
      if (!edge) continue;
      el.addEventListener("pointerenter", () => setActiveEdge(edge.from, edge.to, true));
      el.addEventListener("pointerleave", () => setActiveEdge(edge.from, edge.to, false));
    }

    for (const concept of CONCEPTS) {
      const b = box[concept.id];
      const g = document.createElementNS(svgNS, "g");
      g.classList.add("concept-node");
      g.dataset.id = concept.id;
      g.setAttribute("tabindex", "0");
      g.setAttribute("role", "link");
      g.setAttribute("aria-label", `${concept.label}: jump to description`);
      g.style.transformOrigin = `${b.cx}px ${b.cy}px`;

      const rect = document.createElementNS(svgNS, "rect");
      rect.setAttribute("x", String(b.x));
      rect.setAttribute("y", String(b.y));
      rect.setAttribute("width", String(b.w));
      rect.setAttribute("height", String(b.h));
      rect.setAttribute("rx", "10");
      rect.setAttribute("ry", "10");
      g.appendChild(rect);

      const text = document.createElementNS(svgNS, "text");
      text.setAttribute("x", String(b.cx));
      text.setAttribute("y", String(b.cy));
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("dominant-baseline", "middle");
      text.classList.add("concept-node-label");
      text.textContent = concept.label;
      g.appendChild(text);

      const activate = () => highlightArticle(concept.id);
      g.addEventListener("click", activate);
      g.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          activate();
        }
      });
      g.addEventListener("pointerenter", () => setActiveNode(concept.id, true));
      g.addEventListener("pointerleave", () => setActiveNode(concept.id, false));
      g.addEventListener("focus", () => setActiveNode(concept.id, true));
      g.addEventListener("blur", () => setActiveNode(concept.id, false));

      nodeLayer.appendChild(g);
      nodeEls.set(concept.id, g);
    }

    host.replaceChildren(svg);

    if (!prefersReducedMotion()) {
      svg.classList.add("is-animate-in");
    }
  }

  function fitSectionNav() {
    const nav = document.querySelector(".section-nav");
    const inner = nav?.querySelector(".section-nav-inner");
    if (!nav || !inner) return;
    nav.classList.remove("compact");
    if (inner.scrollWidth > inner.clientWidth + 1) {
      nav.classList.add("compact");
    }
  }

  function init() {
    const articlesHost = document.getElementById("concept-articles");
    const graphHost = document.getElementById("concept-graph");
    if (!articlesHost || !graphHost) return;

    renderArticles(articlesHost);
    renderGraph(graphHost);

    let resizeTimer = 0;
    window.addEventListener("resize", () => {
      fitSectionNav();
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => renderGraph(graphHost), 120);
    });
    fitSectionNav();
    if (typeof ResizeObserver !== "undefined") {
      const nav = document.querySelector(".section-nav");
      if (nav) new ResizeObserver(() => fitSectionNav()).observe(nav);
    }

    // Deep-link support: /about#concept-mix
    const hash = location.hash.replace(/^#/, "");
    if (hash.startsWith("concept-")) {
      const id = hash.slice("concept-".length);
      if (byId[id]) {
        requestAnimationFrame(() => highlightArticle(id));
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
