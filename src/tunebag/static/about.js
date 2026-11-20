(() => {
  "use strict";

  /** @typedef {{ id: string, label: string, layer: number, col: number, tip: string, summary: string, points?: string[] }} Concept */
  /** @typedef {{ from: string, to: string, label: string, tip: string, dashed?: boolean, route?: string, labelT?: number }} Edge */

  /**
   * Six equal columns (centers at (i+0.5)/6):
   *   1 Peer, Locator
   *   2 Device
   *   3 Intent, Sequence, Assignment, Cache, Player
   *   4 Event log, Catalog, Tag
   *   5 Artist, Release, Rating
   *   6 Reject
   */
  const COL = {
    peer: 1 / 12,
    device: 0.3,
    intent: 5 / 12,
    catalog: 7 / 12,
    artist: 9 / 12,
    reject: 11 / 12,
  };

  /** @type {Concept[]} */
  const CONCEPTS = [
    {
      id: "peer",
      label: "Peer",
      layer: 0,
      col: COL.peer,
      tip: "A paired Device you can sync Catalog with and copy audio from.",
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
      col: COL.device,
      tip: "One Tunebag install with a stable Identity; authors Events and holds Cache.",
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
      col: COL.peer,
      tip: "Where a Device is reachable right now — not Identity, and never trust by itself.",
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
      col: COL.catalog,
      tip: "Signed append-only source of truth; Peers sync this to rebuild the same Catalog.",
      summary:
        "The source of truth for Catalog: a signed append-only stream of catalog changes, replicated between paired Peers.",
      points: [
        "Same events ⇒ same Catalog, independent of apply order (per-type deterministic merge).",
        "Paired Devices exchange the Event log (peer sync); audio does not travel in it.",
      ],
    },
    {
      id: "catalog",
      label: "Catalog",
      layer: 2,
      col: COL.catalog,
      tip: "Replicated metadata projection of the Event log on every paired Device.",
      summary:
        "The projected, fully replicated metadata on every paired Device. Derived only from the Event log.",
      points: [
        "Includes Artists, Releases, Tags, Ratings, Rejects, Last heard, Intents, Sequences, Assignments.",
        "Disposable: rebuilt by replaying the Event log.",
      ],
    },
    {
      id: "intent",
      label: "Intent",
      layer: 3,
      col: COL.intent,
      tip: "Shared plan: tag filter + rating distribution; Devices attach hours (and optional expiry).",
      summary:
        "A shared plan: tag filter plus rating distribution. Devices attach hours and optional expiry.",
      points: [
        "Membership uses OR of required Tags.",
        "Rating distribution draws across 5★…1★ and unrated (must sum to 1).",
        "All Devices sharing an Intent share one seeded Sequence.",
      ],
    },
    {
      id: "artist",
      label: "Artist",
      layer: 3,
      col: COL.artist,
      tip: "A source-platform creator whose uploads become Releases (Mix or Album) in the Catalog.",
      summary:
        "A source-platform creator whose uploads are ingested into the Catalog as Releases (Mix or Album).",
      points: [
        "Listing shape is platform-defined (e.g. SoundCloud/hearthis → Mix uploads; Bandcamp/YouTube → Album discography).",
        "YouTube (including Music URLs) lists Album Releases from the channel releases tab.",
        "If YouTube blocks anonymous fetch, restart with tunebag serve --cookies FILE or --cookies-from-browser BROWSER.",
        "Delete of an Artist is sticky across Devices.",
      ],
    },
    {
      id: "sequence",
      label: "Sequence",
      layer: 4,
      col: COL.intent,
      tip: "Seeded ordered Release list for one Intent, filled to the largest Device budget.",
      summary:
        "A seeded ordered list of Releases for one Intent. Fills until cumulative duration meets the largest Device budget.",
      points: [
        "May include the Release that crosses the budget.",
        "Smaller Device budgets cover the opening stretch.",
      ],
    },
    {
      id: "release",
      label: "Release",
      layer: 4,
      col: COL.artist,
      tip: "One listening item in the Catalog — either a Mix or an Album.",
      summary:
        "One listening item in the Catalog. A Release is either a Mix (single file, typically a DJ set) or an Album (ordered tracks). Budgets, Played, Rating, Reject, tags, Playhead, and Last heard attach to the Release as a whole.",
      points: [
        "Mix: one audio file; duration and size are that file’s.",
        "Album: ordered tracks; duration/size are sums; Played uses the whole Album timeline (v1).",
        "Wire/API names may still say mix / mix_id; the domain term is Release.",
      ],
    },
    {
      id: "assignment",
      label: "Assignment",
      layer: 5,
      col: COL.intent,
      tip: "Which Device hours cover which Sequence prefix — independent of on-disk audio.",
      summary:
        "Which Device hours cover which prefix of the Sequence — independent of whether audio is on disk.",
      points: ["Drives what the Cache should hold.", "Built from Device hours on the shared Sequence."],
    },
    {
      id: "tag",
      label: "Tag",
      layer: 5,
      col: COL.catalog,
      tip: "Free-text label on a Release; Intent membership is OR of required Tags.",
      summary: "A free-text label on a Release. Suggestions prefer existing tags.",
      points: [
        "Intent membership uses OR of required Tags.",
        "Unrated Releases may still match a tagged Intent.",
      ],
    },
    {
      id: "rating",
      label: "Rating",
      layer: 5,
      col: COL.artist,
      tip: "1–5★ score on a Release; Intents draw by rating distribution (separate from Reject).",
      summary: "Score 1–5 on a Release (UI may show ★). Separate from Reject.",
      points: [
        "Rating distribution on an Intent sets draw chances including unrated.",
        "Default distribution: 0.3 / 0.2 / 0.1 / 0.05 / 0.05 / 0.3 (5★…1★, unrated).",
      ],
    },
    {
      id: "reject",
      label: "Reject",
      layer: 5,
      col: COL.reject,
      tip: "Never assign again until Un-reject; after undo window, File bytes are deleted everywhere.",
      summary:
        "“Never assign again” until Un-reject. After a 20s local undo window, File bytes are deleted on every Device.",
      points: [
        "Applies to the whole Release (not individual Album tracks) in v1.",
        "Un-reject clears Reject so the Release may re-enter Sequences.",
        "Un-reject does not by itself restore File bytes — Cache fill runs when assigned again.",
      ],
    },
    {
      id: "cache",
      label: "Cache",
      layer: 6,
      col: COL.intent,
      tip: "Audio Files this Device holds for its Assignments (origin, Peer, or USB).",
      summary:
        "The set of Files (audio bytes) a Device currently holds for its Assignments.",
      points: [
        "Filled from origin, Peer, or USB as needed by Assignments.",
        "One File blob for a Mix; an Album needs every track file local before it counts as present.",
        "Metered mode caps origin downloads to the current Release + one ahead per Intent.",
      ],
    },
    {
      id: "player",
      label: "Player",
      layer: 7,
      col: COL.intent,
      tip: "Local playback of Cache; source of play, rating, reject, tag, and playhead signals.",
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
    {
      from: "peer",
      to: "device",
      label: "paired",
      tip: "Trust established (QR / short code); then they can sync and share files.",
      route: "right",
    },
    {
      from: "device",
      to: "locator",
      label: "reachability",
      tip: "How to find this Device on the network right now — changes; not Identity.",
      dashed: true,
      route: "down-enter-right",
    },
    {
      from: "device",
      to: "event-log",
      label: "authors",
      tip: "This Device signs and appends Catalog-changing Events.",
    },
    {
      from: "event-log",
      to: "device",
      label: "peer sync",
      tip: "Paired Devices exchange Events so each can rebuild the same Catalog.",
      dashed: true,
      route: "up-enter-right",
    },
    {
      from: "device",
      to: "cache",
      label: "holds",
      tip: "The Device stores the audio bytes for its Assignments.",
      route: "down-then-across",
    },
    {
      from: "event-log",
      to: "catalog",
      label: "projects",
      tip: "Replay the Event log → same Catalog on every Peer.",
    },
    {
      from: "catalog",
      to: "intent",
      label: "contains",
      tip: "Catalog holds Intent records as projected Event-log state.",
      dashed: true,
    },
    {
      from: "catalog",
      to: "artist",
      label: "contains",
      tip: "Catalog holds Artist records from Events.",
      dashed: true,
    },
    {
      from: "catalog",
      to: "release",
      label: "contains",
      tip: "Catalog holds Release metadata (tags, rating, reject, …) from Events.",
      dashed: true,
      route: "down-gap-across",
    },
    {
      from: "artist",
      to: "release",
      label: "owns",
      tip: "Ingesting an Artist brings their uploads in as Releases (Mix or Album).",
    },
    {
      from: "release",
      to: "tag",
      label: "has",
      tip: "Releases carry free-text Tags used by Intent filters.",
    },
    {
      from: "release",
      to: "rating",
      label: "has",
      tip: "Optional 1–5★ score; feeds Intent draw chances.",
      labelT: 0.72,
    },
    {
      from: "release",
      to: "reject",
      label: "may",
      tip: "A Release can be Rejected so it leaves future Assignments.",
    },
    {
      from: "intent",
      to: "sequence",
      label: "builds",
      tip: "One seeded Sequence is built from the Intent’s tags + rating draws.",
    },
    {
      from: "sequence",
      to: "assignment",
      label: "prefix",
      tip: "Each Device’s hours cover a prefix of the shared Sequence.",
    },
    {
      from: "assignment",
      to: "cache",
      label: "needs",
      tip: "Assigned Releases are what the Cache should fill.",
    },
    {
      from: "cache",
      to: "player",
      label: "plays",
      tip: "The Player reads audio from the local Cache.",
    },
  ];

  const byId = Object.fromEntries(CONCEPTS.map((c) => [c.id, c]));

  /**
   * Keep in sync with docs/LATER.md § Planned features.
   * @typedef {{ title: string, body: string }} PlannedFeature
   * @type {PlannedFeature[]}
   */
  const PLANNED_FEATURES = [
    {
      title: "Bandcamp track-level UX",
      body: "the Artist → Album adapter is in; seek-bar track marks + hover titles are in; later: per-track skip/reject, and titles while playing.",
    },
    {
      title: "OR tag filters",
      body: "on intents (e.g. tribal OR relaxing). Own sequence per filter. A release may appear in multiple intents; deletes wait until no remaining intent on that device wants the file.",
    },
    {
      title: "Library import",
      body: "from the laptop: match on-disk files to ~/.music-snd-downloaded.txt (SoundCloud, hearthis.at, and Bandcamp ids), seed the laptop cache, mark archive ids with no remaining file as already seen. Artist refresh itself is hackathon issue 09 (re-list known artists; do not resurrect committed rejects or old deletes).",
    },
    {
      title: "Profile import",
      body: "SoundCloud and hearthis.at follow lists.",
    },
    {
      title: "Artist reposts",
      body: "in addition to own uploads.",
    },
    {
      title: "Search",
      body: "across the catalog (and later across platforms) by tag, artist, title.",
    },
    {
      title: "Suggested tags and ratings",
      body: "from titles/metadata, later from audio analysis.",
    },
    {
      title: "Peer cache file share",
      body: "copy assigned Release bytes from a reachable Peer’s Cache over HTTP (and USB when present) before origin download; honor fetch priority / metered rules (peer/USB = unmetered). Closes the gap between in-process demo copy and real multi-process devices.",
    },
    {
      title: "Cross-network meet relay",
      body: "reach a paired Peer outside the LAN multicast domain without pasting a Locator (optional server/relay peer).",
    },
    {
      title: "Web player as a paired peer",
      body: "for ad-hoc listening from anywhere (same sync protocol).",
    },
    {
      title: "Foobar (macOS) and Vanilla Music (Android)",
      body: "opening intent folders as dumb consumers of files; signal capture stays in Tunebag until adapters exist.",
    },
  ];

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /** @type {HTMLElement | null} */
  let tipEl = null;

  function ensureTip() {
    if (!tipEl) tipEl = document.getElementById("concept-tip");
    return tipEl;
  }

  /**
   * @param {string} text
   * @param {number} clientX
   * @param {number} clientY
   */
  function showTip(text, clientX, clientY) {
    const el = ensureTip();
    if (!el || !text) return;
    el.textContent = text;
    el.hidden = false;
    moveTip(clientX, clientY);
  }

  /**
   * @param {number} clientX
   * @param {number} clientY
   */
  function moveTip(clientX, clientY) {
    const el = ensureTip();
    if (!el || el.hidden) return;
    const pad = 12;
    const tw = el.offsetWidth || 220;
    const th = el.offsetHeight || 40;
    let left = clientX + 14;
    let top = clientY + 16;
    if (left + tw + pad > window.innerWidth) left = clientX - tw - 12;
    if (top + th + pad > window.innerHeight) top = clientY - th - 12;
    el.style.left = `${Math.max(pad, left)}px`;
    el.style.top = `${Math.max(pad, top)}px`;
  }

  function hideTip() {
    const el = ensureTip();
    if (!el) return;
    el.hidden = true;
    el.textContent = "";
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

      if (route === "down-gap-across") {
        // Catalog → Release: down from Catalog, horizontal in the Artist–Release gap, then down into Release.
        const artist = box.artist;
        const x1 = a.cx;
        const y1 = a.y + a.h + gap;
        const x2 = b.cx;
        const y2 = b.y - gap;
        const midY = artist
          ? (artist.y + artist.h + b.y) / 2
          : y1 + (y2 - y1) * 0.62;
        return {
          d: `M ${x1} ${y1} L ${x1} ${midY} L ${x2} ${midY} L ${x2} ${y2}`,
          lx: (x1 + x2) / 2,
          ly: midY - 10,
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
      // Shared elbow height for siblings (e.g. Release → Tag / Reject).
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
      el.addEventListener("pointerenter", (ev) => {
        setActiveEdge(edge.from, edge.to, true);
        showTip(edge.tip, ev.clientX, ev.clientY);
      });
      el.addEventListener("pointermove", (ev) => moveTip(ev.clientX, ev.clientY));
      el.addEventListener("pointerleave", () => {
        setActiveEdge(edge.from, edge.to, false);
        hideTip();
      });
    }

    for (const concept of CONCEPTS) {
      const b = box[concept.id];
      const g = document.createElementNS(svgNS, "g");
      g.classList.add("concept-node");
      g.dataset.id = concept.id;
      g.setAttribute("tabindex", "0");
      g.setAttribute("role", "link");
      g.setAttribute(
        "aria-label",
        `${concept.label}: ${concept.tip} Click to jump to description.`,
      );
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
      g.addEventListener("pointerenter", (ev) => {
        setActiveNode(concept.id, true);
        showTip(concept.tip, ev.clientX, ev.clientY);
      });
      g.addEventListener("pointermove", (ev) => moveTip(ev.clientX, ev.clientY));
      g.addEventListener("pointerleave", () => {
        setActiveNode(concept.id, false);
        hideTip();
      });
      g.addEventListener("focus", () => {
        setActiveNode(concept.id, true);
        const rectBox = g.getBoundingClientRect();
        showTip(concept.tip, rectBox.left + rectBox.width / 2, rectBox.bottom);
      });
      g.addEventListener("blur", () => {
        setActiveNode(concept.id, false);
        hideTip();
      });

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

  /**
   * @param {HTMLElement} host
   */
  function renderPlannedFeatures(host) {
    host.replaceChildren();
    for (const feature of PLANNED_FEATURES) {
      const li = document.createElement("li");
      const strong = document.createElement("strong");
      strong.textContent = feature.title;
      li.appendChild(strong);
      li.appendChild(document.createTextNode(` ${feature.body}`));
      host.appendChild(li);
    }
  }

  function init() {
    const articlesHost = document.getElementById("concept-articles");
    const graphHost = document.getElementById("concept-graph");
    const plannedHost = document.getElementById("planned-features");
    if (!articlesHost || !graphHost) return;

    renderArticles(articlesHost);
    renderGraph(graphHost);
    if (plannedHost) renderPlannedFeatures(plannedHost);

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

    // Deep-link support: /about#concept-release (legacy: #concept-mix)
    const hash = location.hash.replace(/^#/, "");
    if (hash.startsWith("concept-")) {
      let id = hash.slice("concept-".length);
      if (id === "mix") id = "release";
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
