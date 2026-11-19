let localDeviceId = null;
let localFingerprint = null;
let localPriority = null;
let currentMixId = null;
let peersCache = [];
const expandedCatalogArtists = new Set();
const expandedCacheIntents = new Set();
const expandedIntentPanes = new Set();
/** @type {Map<string, {mode: "add"|"edit", deviceId?: string}>} */
const hoursEditorState = new Map();
/** Catalog Rejected filter (default off). */
let showRejectedCatalog = false;
/** Catalog source filter (OR); default all platforms once mounted. */
let catalogFilterPlatforms = [];
/** Catalog minimum stars filter; null = any rating (incl. unrated). */
let catalogFilterMinStars = null;
/** Catalog tag filter (AND); empty = no tag constraint. */
let catalogFilterTags = [];
/** @type {ReturnType<typeof mountTagEditor> | null} */
let catalogTagFilterEditor = null;
/** @type {{ setFloor: (n: number|null) => void, getFloor: () => number|null } | null} */
let catalogStarFilter = null;
/** Play history Rejected filter (default off). */
let showRejectedHistory = false;
let rejectUndoTimer = null;
/** @type {Map<string, number>} mixId → timeout handle for catalog reject undo refresh */
const catalogRejectTimers = new Map();
let fillWasInProgress = false;
let lastFilesRefreshAt = 0;
let filesRefreshInFlight = null;
const FILES_REFRESH_MIN_MS = 1000;
let lastPlayheadCommitAt = 0;
let lastKnownPositionSeconds = 0;
let playheadCommitInFlight = false;
const PLAYHEAD_COMMIT_MS = 10000;
/** Mix id already announced as marked played during this play session. */
let playheadPlayedNotifiedForMix = null;
/** Last player poll: used so intent-list play buttons stay in sync. */
let lastPlayerPlaying = false;
let lastPlayerIntentId = null;
/** @type {ReturnType<typeof mountTagEditor> | null} */
let playerTagEditor = null;
/** @type {ReturnType<typeof mountStarRating> | null} */
let playerStarRating = null;
/** @type {ReturnType<typeof mountAnnotateKit> | null} */
let playerAnnotateKit = null;
/** @type {ReturnType<typeof mountIntentComposer> | null} */
let createComposer = null;
/** @type {ReturnType<typeof mountIntentComposer> | null} */
let editComposer = null;
/** @type {string | null} */
let editingIntentId = null;

/** Compact action glyphs; always set aria-label + data-tip (hover name). */
const BTN = {
  edit: "✎",
  refresh: "↻",
  fill: "⬇",
  delete: "⌫",
  confirmDelete: "💥",
  reject: "✕",
  unreject: "↺",
  add: "✚",
  save: "✓",
  cancel: "×",
  sync: "⇄",
  setCurrent: "◉",
  clearCurrent: "○",
  play: "▶",
  pause: "⏸",
  resume: "▶",
  copy: "⎘",
};

function setSymbolButton(btn, symbol, label) {
  btn.classList.add("symbol-btn");
  btn.textContent = symbol;
  btn.removeAttribute("title");
  btn.setAttribute("aria-label", label);
  btn.dataset.tip = label;
}

/** Mark static single-glyph action buttons as compact squares. */
function markStaticSymbolButtons() {
  for (const btn of document.querySelectorAll("button[data-tip]")) {
    if (
      btn.classList.contains("section-info-btn") ||
      btn.classList.contains("tag-chip-add") ||
      btn.classList.contains("tag-chip-x") ||
      btn.classList.contains("star-rating-star")
    ) {
      continue;
    }
    const text = btn.textContent.replace(/\s+/g, "");
    if ([...text].length <= 2) {
      btn.classList.add("symbol-btn");
    }
  }
}

/** @type {string[]} */
let catalogTagsCache = [];
/** @type {{id: string, name: string}[]} */
let catalogArtistsCache = [];

function normalizeTag(tag) {
  return String(tag || "")
    .trim()
    .toLowerCase();
}

function normalizeArtistNeedle(text) {
  return String(text || "")
    .trim()
    .toLowerCase();
}

/**
 * Categorical OKLCH swatches for tags (N=64).
 * Built once via maximin packing over an L/C/hue grid so arbitrary slot
 * pairs stay farther apart than golden-angle indexing (which can land ~8°
 * apart). Assignment stays hash-preferred + alpha linear probe — not
 * distance-optimized per catalog — so merge recolors stay rare.
 */
const TAG_CHIP_PALETTE = (() => {
  const n = 64;
  const Ls = [0.44, 0.52, 0.6, 0.68];
  const Cs = [0.1, 0.135, 0.17, 0.2];
  /** @type {{ L: number, C: number, hue: number }[]} */
  const candidates = [];
  for (const L of Ls) {
    for (const C of Cs) {
      for (let hue = 0; hue < 360; hue += 8) {
        candidates.push({ L, C, hue });
      }
    }
  }

  function oklchDist(a, b) {
    const dL = (a.L - b.L) * 2.8;
    const dC = (a.C - b.C) * 2.2;
    const dh = Math.min(
      Math.abs(a.hue - b.hue),
      360 - Math.abs(a.hue - b.hue),
    );
    const dH = 2 * Math.sqrt(Math.max(a.C * b.C, 0)) * Math.sin((dh * Math.PI) / 360);
    return Math.hypot(dL, dC, dH * 3.2);
  }

  /** @type {{ L: number, C: number, hue: number }[]} */
  const out = [];
  // Deterministic seed: mid-light, mid-chroma, hue 0.
  let seedIdx = 0;
  let seedScore = Infinity;
  for (let i = 0; i < candidates.length; i += 1) {
    const c = candidates[i];
    const score = Math.hypot(c.L - 0.52, c.C - 0.135, Math.min(c.hue, 360 - c.hue) / 180);
    if (score < seedScore) {
      seedScore = score;
      seedIdx = i;
    }
  }
  out.push(candidates[seedIdx]);
  const taken = new Set([seedIdx]);

  while (out.length < n) {
    let bestIdx = -1;
    let bestMin = -1;
    for (let i = 0; i < candidates.length; i += 1) {
      if (taken.has(i)) continue;
      let minD = Infinity;
      for (const sw of out) {
        const d = oklchDist(candidates[i], sw);
        if (d < minD) minD = d;
      }
      if (
        minD > bestMin ||
        (minD === bestMin &&
          bestIdx >= 0 &&
          candidates[i].hue < candidates[bestIdx].hue)
      ) {
        bestMin = minD;
        bestIdx = i;
      }
    }
    if (bestIdx < 0) break;
    taken.add(bestIdx);
    out.push(candidates[bestIdx]);
  }
  return out;
})();

/** Muted swatch for not-yet-created tag suggestions. */
const TAG_CHIP_CREATE_SWATCH = { L: 0.58, C: 0.01, hue: 0 };

function tagChipHash(tag) {
  let hash = 2166136261;
  for (let i = 0; i < tag.length; i += 1) {
    hash ^= tag.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/**
 * Unique palette slots for a tag set: preferred = hash % N; conflicts walk
 * alphabetically and take the smallest k with (hash + k) % N free.
 * When the table is full (|tags| > N), further tags reuse hash % N (no loop).
 * @param {Iterable<string>} allTags
 * @returns {Map<string, number>}
 */
function assignTagChipSlots(allTags) {
  const n = TAG_CHIP_PALETTE.length;
  const keys = [
    ...new Set(
      [...allTags].map(normalizeTag).filter(Boolean),
    ),
  ].sort();
  /** @type {Map<string, number>} */
  const slots = new Map();
  const used = new Set();
  for (const key of keys) {
    const preferred = tagChipHash(key) % n;
    let slot = preferred;
    if (used.size < n) {
      for (let k = 0; k < n; k += 1) {
        const cand = (preferred + k) % n;
        if (!used.has(cand)) {
          slot = cand;
          break;
        }
      }
      used.add(slot);
    }
    // else: palette full — reuse preferred (intentional collision)
    slots.set(key, slot);
  }
  return slots;
}

function tagChipSwatchCss(swatch) {
  const border = `oklch(${swatch.L} ${swatch.C} ${swatch.hue})`;
  const fill = `oklch(${Math.min(swatch.L + 0.1, 0.78)} ${swatch.C} ${swatch.hue} / 0.2)`;
  return [border, fill];
}

/**
 * Soft OKLCH border/fill for a tag given the catalog∪in-view tag set.
 * @param {string} tag
 * @param {Iterable<string>} [allTags]
 */
function tagChipColors(tag, allTags) {
  const key = normalizeTag(tag);
  const slots = assignTagChipSlots(allTags != null ? [...allTags, key] : [key]);
  const slot = slots.get(key) ?? tagChipHash(key) % TAG_CHIP_PALETTE.length;
  return tagChipSwatchCss(TAG_CHIP_PALETTE[slot]);
}

/**
 * Read-only colored chips (no add/remove). Colors match the tag editor.
 * @param {string[]} tags
 * @param {Iterable<string>} [allTags]
 * @returns {HTMLElement}
 */
function renderTagChipsDisplay(tags, allTags) {
  const cleaned = (tags || []).map(normalizeTag).filter(Boolean);
  const chipsEl = document.createElement("div");
  chipsEl.className = "tag-chips";
  if (!cleaned.length) {
    const empty = document.createElement("span");
    empty.className = "intent-meta-empty";
    empty.textContent = "-";
    chipsEl.appendChild(empty);
    return chipsEl;
  }
  const context = allTags != null ? [...allTags, ...cleaned] : cleaned;
  const slots = assignTagChipSlots(context);
  for (const tag of cleaned) {
    const slot = slots.get(tag) ?? tagChipHash(tag) % TAG_CHIP_PALETTE.length;
    const [border, fill] = tagChipSwatchCss(TAG_CHIP_PALETTE[slot]);
    const chip = document.createElement("span");
    chip.className = "tag-chip";
    chip.style.setProperty("--tag-chip-border", border);
    chip.style.setProperty("--tag-chip-fill", fill);
    chip.dataset.tag = tag;
    const label = document.createElement("span");
    label.className = "tag-chip-label";
    label.textContent = tag;
    chip.appendChild(label);
    chipsEl.appendChild(chip);
  }
  return chipsEl;
}

/**
 * Chip tag editor: thin colored chips, confirm-to-remove (optional), + picker.
 * @param {HTMLElement} root
 * @param {{
 *   tags?: string[],
 *   onAdd: (tag: string) => Promise<void> | void,
 *   onRemove: (tag: string) => Promise<void> | void,
 *   getCatalogTags?: () => string[],
 *   confirmRemove?: boolean,
 * }} options
 */
function mountTagEditor(root, options) {
  const getCatalogTags = options.getCatalogTags || (() => catalogTagsCache);
  const confirmRemove = options.confirmRemove !== false;
  let tags = (options.tags || []).map(normalizeTag).filter(Boolean);
  let confirming = null;
  let picking = false;
  let filterText = "";
  let highlightIndex = 0;
  let saving = false;
  /** @type {ReturnType<typeof setTimeout> | null} */
  let confirmTimer = null;
  /** @type {HTMLInputElement | null} */
  let filterInput = null;

  function isBusy() {
    return picking || confirming != null || saving;
  }

  function syncBusyClass() {
    root.classList.toggle("is-busy", isBusy());
  }

  function clearConfirm() {
    confirming = null;
    if (confirmTimer != null) {
      clearTimeout(confirmTimer);
      confirmTimer = null;
    }
  }

  function armConfirm(tag) {
    clearConfirm();
    confirming = tag;
    picking = false;
    confirmTimer = setTimeout(() => {
      clearConfirm();
      syncBusyClass();
      render();
    }, 4000);
    syncBusyClass();
    render();
  }

  function suggestionRows() {
    const owned = new Set(tags);
    const needle = normalizeTag(filterText);
    const catalog = getCatalogTags().map(normalizeTag).filter(Boolean);
    const catalogSet = new Set(catalog);
    const matches = catalog.filter(
      (tag) => !owned.has(tag) && (!needle || tag.includes(needle)),
    );
    // Prefer prefix matches, then shorter names, keep popularity order otherwise.
    matches.sort((a, b) => {
      const ap = needle && a.startsWith(needle) ? 0 : 1;
      const bp = needle && b.startsWith(needle) ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return 0;
    });
    const rows = matches.slice(0, 6).map((tag) => ({ tag, create: false }));
    if (needle && !owned.has(needle)) {
      if (!rows.some((row) => row.tag === needle)) {
        const create = !catalogSet.has(needle);
        if (rows.length < 6) rows.push({ tag: needle, create });
        else rows[rows.length - 1] = { tag: needle, create };
      }
    }
    return rows;
  }

  async function addTag(tag) {
    const cleaned = normalizeTag(tag);
    if (!cleaned || tags.includes(cleaned) || saving) return;
    const prev = [...tags];
    tags = [...tags, cleaned];
    picking = false;
    filterText = "";
    clearConfirm();
    saving = true;
    syncBusyClass();
    render();
    try {
      await options.onAdd(cleaned);
    } catch (err) {
      tags = prev;
      console.error(err);
    } finally {
      saving = false;
      syncBusyClass();
      render();
    }
  }

  async function removeTag(tag) {
    const cleaned = normalizeTag(tag);
    if (!cleaned || !tags.includes(cleaned) || saving) return;
    const prev = [...tags];
    tags = tags.filter((t) => t !== cleaned);
    clearConfirm();
    saving = true;
    syncBusyClass();
    render();
    try {
      await options.onRemove(cleaned);
    } catch (err) {
      tags = prev;
      console.error(err);
    } finally {
      saving = false;
      syncBusyClass();
      render();
    }
  }

  function detachDocListeners() {
    document.removeEventListener("pointerdown", onDocPointer, true);
    document.removeEventListener("keydown", onDocKey, true);
  }

  function onDocPointer(event) {
    if (!root.isConnected) {
      detachDocListeners();
      return;
    }
    if (!root.contains(event.target)) {
      let changed = false;
      if (confirming != null) {
        clearConfirm();
        changed = true;
      }
      if (picking) {
        closePicker();
        changed = true;
      }
      if (changed) {
        syncBusyClass();
        render();
      }
    }
  }

  function onDocKey(event) {
    if (!root.isConnected) {
      detachDocListeners();
      return;
    }
    if (event.key !== "Escape") return;
    if (!isBusy()) return;
    clearConfirm();
    if (picking) closePicker();
    syncBusyClass();
    render();
  }

  document.addEventListener("pointerdown", onDocPointer, true);
  document.addEventListener("keydown", onDocKey, true);

  root.classList.add("tag-editor");
  const chipsEl = document.createElement("div");
  chipsEl.className = "tag-chips";
  root.replaceChildren(chipsEl);

  /** @type {HTMLElement | null} */
  let suggestList = null;

  function paintHighlight() {
    if (!suggestList) return;
    suggestList.querySelectorAll(".tag-suggest").forEach((el, i) => {
      el.classList.toggle("is-active", i === highlightIndex);
    });
  }

  /** Catalog ∪ editor tags (+ extras) for unique color assignment. */
  function colorContextTags(extra = []) {
    return [
      ...getCatalogTags().map(normalizeTag).filter(Boolean),
      ...tags,
      ...extra.map(normalizeTag).filter(Boolean),
    ];
  }

  function renderSuggestions() {
    if (!suggestList) return;
    const rows = suggestionRows();
    if (highlightIndex >= rows.length) {
      highlightIndex = Math.max(0, rows.length - 1);
    }
    const slots = assignTagChipSlots(
      colorContextTags(
        rows.filter((row) => !row.create).map((row) => row.tag),
      ),
    );
    suggestList.replaceChildren();
    rows.forEach((row, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "tag-suggest";
      if (index === highlightIndex) item.classList.add("is-active");
      if (row.create) item.classList.add("is-create");
      const [border, fill] = row.create
        ? tagChipSwatchCss(TAG_CHIP_CREATE_SWATCH)
        : tagChipSwatchCss(
            TAG_CHIP_PALETTE[
              slots.get(normalizeTag(row.tag)) ??
                tagChipHash(normalizeTag(row.tag)) % TAG_CHIP_PALETTE.length
            ],
          );
      item.style.setProperty("--tag-chip-border", border);
      item.style.setProperty("--tag-chip-fill", fill);
      const label = document.createElement("span");
      label.textContent = row.tag;
      item.appendChild(label);
      if (row.create) {
        const plus = document.createElement("span");
        plus.className = "tag-suggest-plus";
        plus.textContent = "+";
        item.appendChild(plus);
      }
      item.addEventListener("click", (event) => {
        event.stopPropagation();
        void addTag(row.tag);
      });
      item.addEventListener("pointerenter", () => {
        highlightIndex = index;
        paintHighlight();
      });
      suggestList.appendChild(item);
    });
  }

  function renderChipNodes() {
    const slots = assignTagChipSlots(colorContextTags());
    const frag = document.createDocumentFragment();
    for (const tag of tags) {
      const slot =
        slots.get(tag) ?? tagChipHash(tag) % TAG_CHIP_PALETTE.length;
      const [border, fill] = tagChipSwatchCss(TAG_CHIP_PALETTE[slot]);
      const chip = document.createElement("span");
      chip.className = "tag-chip";
      chip.style.setProperty("--tag-chip-border", border);
      chip.style.setProperty("--tag-chip-fill", fill);
      chip.dataset.tag = tag;
      const label = document.createElement("span");
      label.className = "tag-chip-label";
      label.textContent = tag;
      chip.appendChild(label);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tag-chip-x";
      // pointerdown (not click): player poll remounts chips between mousedown and
      // click, which can deliver the click to a different tag's ×.
      if (confirmRemove && confirming === tag) {
        remove.classList.add("confirm-pending", "is-armed");
        remove.textContent = BTN.confirmDelete;
        remove.setAttribute("aria-label", `Really remove “${tag}”?`);
        remove.dataset.tip = `really remove “${tag}”?`;
        remove.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          event.stopPropagation();
          void removeTag(tag);
        });
      } else {
        remove.textContent = "×";
        remove.setAttribute("aria-label", `Remove “${tag}”`);
        remove.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (confirmRemove) armConfirm(tag);
          else void removeTag(tag);
        });
      }
      chip.appendChild(remove);
      frag.appendChild(chip);
    }
    return frag;
  }

  function closePicker() {
    picking = false;
    filterText = "";
    highlightIndex = 0;
    filterInput = null;
    suggestList = null;
  }

  function openPicker() {
    clearConfirm();
    picking = true;
    filterText = "";
    highlightIndex = 0;
    syncBusyClass();

    const pickerWrap = document.createElement("div");
    pickerWrap.className = "tag-picker-wrap";
    filterInput = document.createElement("input");
    filterInput.type = "text";
    filterInput.className = "tag-picker-input";
    filterInput.placeholder = "tag";
    filterInput.autocomplete = "off";
    filterInput.spellcheck = false;
    filterInput.addEventListener("click", (event) => event.stopPropagation());
    filterInput.addEventListener("pointerdown", (event) => event.stopPropagation());
    filterInput.addEventListener("input", () => {
      filterText = filterInput?.value || "";
      highlightIndex = 0;
      renderSuggestions();
    });
    filterInput.addEventListener("keydown", (event) => {
      const currentRows = suggestionRows();
      if (event.key === "Enter") {
        event.preventDefault();
        const row = currentRows[highlightIndex] || currentRows[0];
        if (row) void addTag(row.tag);
        else if (normalizeTag(filterText)) void addTag(filterText);
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        highlightIndex = Math.min(
          highlightIndex + 1,
          Math.max(0, currentRows.length - 1),
        );
        paintHighlight();
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        highlightIndex = Math.max(highlightIndex - 1, 0);
        paintHighlight();
      }
    });
    suggestList = document.createElement("div");
    suggestList.className = "tag-suggest-list";
    pickerWrap.appendChild(filterInput);
    pickerWrap.appendChild(suggestList);

    const addBtn = chipsEl.querySelector(".tag-chip-add");
    if (addBtn) addBtn.replaceWith(pickerWrap);
    else chipsEl.appendChild(pickerWrap);

    filterInput.focus();
    renderSuggestions();
  }

  function render() {
    syncBusyClass();
    if (picking) {
      // Rebuild chips only; keep the live picker/input mounted.
      const picker = chipsEl.querySelector(".tag-picker-wrap");
      const chipFrag = renderChipNodes();
      chipsEl.replaceChildren(chipFrag);
      if (picker) {
        chipsEl.appendChild(picker);
        renderSuggestions();
      } else {
        openPicker();
      }
      return;
    }
    filterInput = null;
    suggestList = null;
    const frag = renderChipNodes();
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "tag-chip-add";
    addBtn.textContent = "+";
    addBtn.setAttribute("aria-label", "Add tag");
    addBtn.dataset.tip = "Add tag";
    addBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openPicker();
    });
    frag.appendChild(addBtn);
    chipsEl.replaceChildren(frag);
  }

  render();

  return {
    setTags(next) {
      if (isBusy()) return;
      const normalized = (next || []).map(normalizeTag).filter(Boolean);
      if (
        normalized.length === tags.length &&
        normalized.every((tag, i) => tag === tags[i])
      ) {
        return;
      }
      tags = normalized;
      render();
    },
    getTags() {
      return [...tags];
    },
    isBusy,
    destroy() {
      clearConfirm();
      detachDocListeners();
      root.replaceChildren();
      root.classList.remove("tag-editor", "is-busy");
    },
  };
}

/**
 * Chip artist picker: plain chips, confirm-to-remove, + search (catalog only).
 * @param {HTMLElement} root
 * @param {{
 *   artists?: {id: string, name: string}[],
 *   onAdd: (artist: {id: string, name: string}) => Promise<void> | void,
 *   onRemove: (artist: {id: string, name: string}) => Promise<void> | void,
 *   getCatalogArtists?: () => {id: string, name: string}[],
 * }} options
 */
function mountArtistEditor(root, options) {
  const getCatalogArtists =
    options.getCatalogArtists || (() => catalogArtistsCache);
  /** @type {{id: string, name: string}[]} */
  let artists = [...(options.artists || [])];
  let confirming = null;
  let picking = false;
  let filterText = "";
  let highlightIndex = 0;
  let saving = false;
  /** @type {ReturnType<typeof setTimeout> | null} */
  let confirmTimer = null;
  /** @type {HTMLInputElement | null} */
  let filterInput = null;

  function isBusy() {
    return picking || confirming != null || saving;
  }

  function syncBusyClass() {
    root.classList.toggle("is-busy", isBusy());
  }

  function clearConfirm() {
    confirming = null;
    if (confirmTimer != null) {
      clearTimeout(confirmTimer);
      confirmTimer = null;
    }
  }

  function armConfirm(artistId) {
    clearConfirm();
    confirming = artistId;
    picking = false;
    confirmTimer = setTimeout(() => {
      clearConfirm();
      syncBusyClass();
      render();
    }, 4000);
    syncBusyClass();
    render();
  }

  function suggestionRows() {
    const owned = new Set(artists.map((a) => a.id));
    const needle = normalizeArtistNeedle(filterText);
    const catalog = getCatalogArtists().filter((a) => a && a.id && a.name);
    const matches = catalog.filter((artist) => {
      if (owned.has(artist.id)) return false;
      if (!needle) return true;
      return normalizeArtistNeedle(artist.name).includes(needle);
    });
    matches.sort((a, b) => {
      const an = normalizeArtistNeedle(a.name);
      const bn = normalizeArtistNeedle(b.name);
      const ap = needle && an.startsWith(needle) ? 0 : 1;
      const bp = needle && bn.startsWith(needle) ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return an.localeCompare(bn);
    });
    return matches.slice(0, 6);
  }

  async function addArtist(artist) {
    if (!artist?.id || artists.some((a) => a.id === artist.id) || saving) return;
    const prev = [...artists];
    artists = [...artists, { id: artist.id, name: artist.name }];
    picking = false;
    filterText = "";
    clearConfirm();
    saving = true;
    syncBusyClass();
    render();
    try {
      await options.onAdd(artist);
    } catch (err) {
      artists = prev;
      console.error(err);
    } finally {
      saving = false;
      syncBusyClass();
      render();
    }
  }

  async function removeArtist(artistId) {
    if (!artistId || !artists.some((a) => a.id === artistId) || saving) return;
    const prev = [...artists];
    const removed = artists.find((a) => a.id === artistId);
    artists = artists.filter((a) => a.id !== artistId);
    clearConfirm();
    saving = true;
    syncBusyClass();
    render();
    try {
      if (removed) await options.onRemove(removed);
    } catch (err) {
      artists = prev;
      console.error(err);
    } finally {
      saving = false;
      syncBusyClass();
      render();
    }
  }

  function detachDocListeners() {
    document.removeEventListener("pointerdown", onDocPointer, true);
    document.removeEventListener("keydown", onDocKey, true);
  }

  function onDocPointer(event) {
    if (!root.isConnected) {
      detachDocListeners();
      return;
    }
    if (!root.contains(event.target)) {
      let changed = false;
      if (confirming != null) {
        clearConfirm();
        changed = true;
      }
      if (picking) {
        closePicker();
        changed = true;
      }
      if (changed) {
        syncBusyClass();
        render();
      }
    }
  }

  function onDocKey(event) {
    if (!root.isConnected) {
      detachDocListeners();
      return;
    }
    if (event.key !== "Escape") return;
    if (!isBusy()) return;
    clearConfirm();
    if (picking) closePicker();
    syncBusyClass();
    render();
  }

  document.addEventListener("pointerdown", onDocPointer, true);
  document.addEventListener("keydown", onDocKey, true);

  root.classList.add("tag-editor");
  const chipsEl = document.createElement("div");
  chipsEl.className = "tag-chips";
  root.replaceChildren(chipsEl);

  /** @type {HTMLElement | null} */
  let suggestList = null;

  function paintHighlight() {
    if (!suggestList) return;
    suggestList.querySelectorAll(".artist-suggest").forEach((el, i) => {
      el.classList.toggle("is-active", i === highlightIndex);
    });
  }

  function renderSuggestions() {
    if (!suggestList) return;
    const rows = suggestionRows();
    if (highlightIndex >= rows.length) {
      highlightIndex = Math.max(0, rows.length - 1);
    }
    suggestList.replaceChildren();
    rows.forEach((row, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "artist-suggest";
      if (index === highlightIndex) item.classList.add("is-active");
      item.textContent = row.name;
      item.addEventListener("click", (event) => {
        event.stopPropagation();
        void addArtist(row);
      });
      item.addEventListener("pointerenter", () => {
        highlightIndex = index;
        paintHighlight();
      });
      suggestList.appendChild(item);
    });
  }

  function renderChipNodes() {
    const frag = document.createDocumentFragment();
    artists.forEach((artist, index) => {
      if (index > 0) {
        const sep = document.createElement("span");
        sep.className = "artist-chip-sep";
        sep.textContent = ", ";
        frag.appendChild(sep);
      }
      const chip = document.createElement("span");
      chip.className = "artist-chip";
      chip.dataset.artistId = artist.id;
      const label = document.createElement("span");
      label.className = "artist-chip-label";
      label.textContent = artist.name;
      chip.appendChild(label);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tag-chip-x";
      if (confirming === artist.id) {
        remove.classList.add("confirm-pending", "is-armed");
        remove.textContent = BTN.confirmDelete;
        remove.setAttribute("aria-label", `Really remove “${artist.name}”?`);
        remove.dataset.tip = `really remove “${artist.name}”?`;
        remove.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          event.stopPropagation();
          void removeArtist(artist.id);
        });
      } else {
        remove.textContent = "×";
        remove.setAttribute("aria-label", `Remove “${artist.name}”`);
        remove.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          event.stopPropagation();
          armConfirm(artist.id);
        });
      }
      chip.appendChild(remove);
      frag.appendChild(chip);
    });
    return frag;
  }

  function closePicker() {
    picking = false;
    filterText = "";
    highlightIndex = 0;
    filterInput = null;
    suggestList = null;
  }

  function openPicker() {
    clearConfirm();
    picking = true;
    filterText = "";
    highlightIndex = 0;
    syncBusyClass();

    const pickerWrap = document.createElement("div");
    pickerWrap.className = "tag-picker-wrap";
    filterInput = document.createElement("input");
    filterInput.type = "text";
    filterInput.className = "tag-picker-input";
    filterInput.placeholder = "artist";
    filterInput.autocomplete = "off";
    filterInput.spellcheck = false;
    filterInput.addEventListener("click", (event) => event.stopPropagation());
    filterInput.addEventListener("pointerdown", (event) => event.stopPropagation());
    filterInput.addEventListener("input", () => {
      filterText = filterInput?.value || "";
      highlightIndex = 0;
      renderSuggestions();
    });
    filterInput.addEventListener("keydown", (event) => {
      const currentRows = suggestionRows();
      if (event.key === "Enter") {
        event.preventDefault();
        const row = currentRows[highlightIndex] || currentRows[0];
        if (row) void addArtist(row);
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        highlightIndex = Math.min(
          highlightIndex + 1,
          Math.max(0, currentRows.length - 1),
        );
        paintHighlight();
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        highlightIndex = Math.max(highlightIndex - 1, 0);
        paintHighlight();
      }
    });
    suggestList = document.createElement("div");
    suggestList.className = "artist-suggest-list";
    pickerWrap.appendChild(filterInput);
    pickerWrap.appendChild(suggestList);

    const addBtn = chipsEl.querySelector(".tag-chip-add");
    if (addBtn) addBtn.replaceWith(pickerWrap);
    else chipsEl.appendChild(pickerWrap);

    filterInput.focus();
    renderSuggestions();
  }

  function render() {
    syncBusyClass();
    if (picking) {
      const picker = chipsEl.querySelector(".tag-picker-wrap");
      const chipFrag = renderChipNodes();
      chipsEl.replaceChildren(chipFrag);
      if (picker) {
        chipsEl.appendChild(picker);
        renderSuggestions();
      } else {
        openPicker();
      }
      return;
    }
    filterInput = null;
    suggestList = null;
    const frag = renderChipNodes();
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "tag-chip-add";
    addBtn.textContent = "+";
    addBtn.setAttribute("aria-label", "Add artist");
    addBtn.dataset.tip = "Add artist";
    addBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openPicker();
    });
    frag.appendChild(addBtn);
    chipsEl.replaceChildren(frag);
  }

  root.classList.add("artist-editor");
  render();

  return {
    setIds(nextIds) {
      if (isBusy()) return;
      const wanted = Array.from(new Set((nextIds || []).map(String).filter(Boolean)));
      const byId = new Map(getCatalogArtists().map((a) => [a.id, a.name]));
      for (const artist of artists) {
        if (!byId.has(artist.id)) byId.set(artist.id, artist.name);
      }
      const next = wanted.map((id) => ({
        id,
        name: byId.get(id) || artistNameById.get(id) || id,
      }));
      if (
        next.length === artists.length &&
        next.every((artist, i) => artist.id === artists[i].id)
      ) {
        return;
      }
      artists = next;
      render();
    },
    getIds() {
      return artists.map((a) => a.id);
    },
    isBusy,
    destroy() {
      clearConfirm();
      detachDocListeners();
      root.replaceChildren();
      root.classList.remove("tag-editor", "artist-editor", "is-busy");
    },
  };
}

function mixTagHandlers(mixId) {
  return {
    async onAdd(tag) {
      const res = await fetch(`/api/mixes/${mixId}/tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tag }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Add tag failed");
      }
      await refreshTagSuggestions();
    },
    async onRemove(tag) {
      const res = await fetch(`/api/mixes/${mixId}/tags/${encodeURIComponent(tag)}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Remove tag failed");
      }
      await refreshTagSuggestions();
    },
  };
}

/**
 * Collapse add/create fields behind ✚; expand morphs the button to ✓ for submit.
 * Optional cancel (×) shows while expanded and discards without submitting.
 * @returns {{ expand: (opts?: {submitLabel?: string}) => void, collapse: () => void, isExpanded: () => boolean }}
 */
function bindCollapsibleAdd(form, {
  button,
  expandLabel,
  submitLabel,
  cancelButton = null,
  focusSelector = null,
  onExpand = null,
  onCollapse = null,
  onCancel = null,
} = {}) {
  const btn = typeof button === "string" ? form.querySelector(button) : button;
  const cancelBtn = cancelButton
    ? typeof cancelButton === "string"
      ? form.querySelector(cancelButton)
      : cancelButton
    : null;
  const fieldNodes = () => form.querySelectorAll(".add-form-fields");

  function isExpanded() {
    return form.classList.contains("add-form-open");
  }

  function syncUi(activeSubmitLabel) {
    const open = isExpanded();
    for (const el of fieldNodes()) {
      el.hidden = !open;
    }
    if (open) {
      setSymbolButton(btn, BTN.save, activeSubmitLabel || submitLabel);
    } else {
      setSymbolButton(btn, BTN.add, expandLabel);
    }
    if (cancelBtn) {
      cancelBtn.hidden = !open;
      if (open) {
        setSymbolButton(cancelBtn, BTN.cancel, "Cancel");
      }
    }
  }

  function expand(opts = {}) {
    const wasOpen = isExpanded();
    form.classList.add("add-form-open");
    syncUi(opts.submitLabel || submitLabel);
    if (!wasOpen) {
      onExpand?.();
      if (focusSelector) {
        form.querySelector(focusSelector)?.focus?.();
      }
    }
  }

  function collapse() {
    const wasOpen = isExpanded();
    form.classList.remove("add-form-open");
    syncUi();
    if (wasOpen) {
      onCollapse?.();
    }
  }

  form.classList.remove("add-form-open");
  syncUi();

  btn.addEventListener("click", (event) => {
    if (!isExpanded()) {
      event.preventDefault();
      expand();
    }
  });

  cancelBtn?.addEventListener("click", () => {
    onCancel?.();
    collapse();
  });

  form.addEventListener(
    "submit",
    (event) => {
      if (!isExpanded()) {
        event.preventDefault();
        event.stopImmediatePropagation();
        expand();
      }
    },
    true,
  );

  return { expand, collapse, isExpanded };
}

/** @type {ReturnType<typeof bindCollapsibleAdd> | null} */
let artistsCollapsible = null;
/** @type {Map<string, string>} */
let artistNameById = new Map();
/** @type {ReturnType<typeof bindCollapsibleAdd> | null} */
let pairCollapsible = null;

/** First click arms (💥); second click runs onConfirm. */
function bindConfirmDelete(btn, { label, onConfirm, stopPropagation = false }) {
  setSymbolButton(btn, BTN.delete, label);
  let armed = false;
  let resetTimer = null;

  const reset = () => {
    armed = false;
    btn.classList.remove("confirm-pending");
    setSymbolButton(btn, BTN.delete, label);
    if (resetTimer) {
      clearTimeout(resetTimer);
      resetTimer = null;
    }
  };

  btn.addEventListener("click", async (event) => {
    if (stopPropagation) event.stopPropagation();
    if (!armed) {
      armed = true;
      btn.classList.add("confirm-pending");
      setSymbolButton(btn, BTN.confirmDelete, "really delete?");
      if (actionTipActive === btn) showActionTip(btn);
      resetTimer = setTimeout(reset, 4000);
      return;
    }
    reset();
    await onConfirm(event);
  });
}

let actionTipEl = null;
let actionTipActive = null;

function actionTipLabel(el) {
  if (!(el instanceof Element)) return "";
  // Tag chip ×: aria-label always; tip only when armed (data-tip set).
  // Tag chip +: tip via data-tip (same as other symbol actions).
  if (el.classList.contains("tag-chip-x") || el.classList.contains("tag-chip-add")) {
    return el.dataset.tip || "";
  }
  // Seek section buttons keep aria-label for a11y; no hover tip.
  if (el.classList.contains("player-seek-section")) {
    return "";
  }
  return (
    el.dataset.tip ||
    el.getAttribute("aria-label") ||
    el.getAttribute("title") ||
    ""
  );
}

function ensureActionTip() {
  if (actionTipEl) return actionTipEl;
  actionTipEl = document.createElement("div");
  actionTipEl.className = "action-tip";
  actionTipEl.hidden = true;
  document.body.appendChild(actionTipEl);
  return actionTipEl;
}

function positionActionTip(el) {
  const tip = ensureActionTip();
  const rect = el.getBoundingClientRect();
  const tipRect = tip.getBoundingClientRect();
  let left = rect.left + rect.width / 2;
  let top = rect.top - 8;
  const pad = 8;
  left = Math.max(pad + tipRect.width / 2, Math.min(left, window.innerWidth - pad - tipRect.width / 2));
  if (top - tipRect.height < pad) {
    top = rect.bottom + 8;
    tip.dataset.placement = "below";
  } else {
    tip.dataset.placement = "above";
  }
  tip.style.left = `${Math.round(left)}px`;
  tip.style.top = `${Math.round(top)}px`;
}

function showActionTip(el) {
  const text = actionTipLabel(el);
  if (!text || el.classList.contains("section-info-btn")) return;
  const tip = ensureActionTip();
  actionTipActive = el;
  tip.textContent = text;
  tip.hidden = false;
  positionActionTip(el);
}

function hideActionTip(el) {
  if (el && actionTipActive !== el) return;
  actionTipActive = null;
  if (actionTipEl) actionTipEl.hidden = true;
}

const ACTION_TIP_SELECTOR =
  "button[aria-label], button[data-tip], button[title], a[aria-label], a[title], .has-tip[data-tip]";

function initActionTips() {
  ensureActionTip();
  document.addEventListener("pointerover", (event) => {
    const el = event.target.closest(ACTION_TIP_SELECTOR);
    if (!el) return;
    showActionTip(el);
  });
  document.addEventListener("pointerout", (event) => {
    const el = event.target.closest(ACTION_TIP_SELECTOR);
    if (!el || !actionTipLabel(el)) return;
    const next = event.relatedTarget instanceof Element
      ? event.relatedTarget.closest(ACTION_TIP_SELECTOR)
      : null;
    if (next === el) return;
    hideActionTip(el);
  });
  document.addEventListener(
    "scroll",
    () => {
      if (actionTipActive) positionActionTip(actionTipActive);
    },
    true,
  );
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

function initSectionNav() {
  const nav = document.querySelector(".section-nav");
  if (!nav) return;
  fitSectionNav();
  window.addEventListener("resize", fitSectionNav);
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => fitSectionNav());
    observer.observe(nav);
  }
}

function initSectionInfo() {
  for (const info of document.querySelectorAll(".section-info")) {
    const btn = info.querySelector(".section-info-btn");
    if (!btn) continue;
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = !info.classList.contains("open");
      for (const other of document.querySelectorAll(".section-info.open")) {
        if (other !== info) {
          other.classList.remove("open");
          other.querySelector(".section-info-btn")?.setAttribute("aria-expanded", "false");
        }
      }
      info.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  document.addEventListener("click", () => {
    for (const info of document.querySelectorAll(".section-info.open")) {
      info.classList.remove("open");
      info.querySelector(".section-info-btn")?.setAttribute("aria-expanded", "false");
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    for (const info of document.querySelectorAll(".section-info.open")) {
      info.classList.remove("open");
      info.querySelector(".section-info-btn")?.setAttribute("aria-expanded", "false");
    }
  });
}

function fillInProgressFromEntries(entries) {
  let inProgress = false;
  for (const entry of entries) {
    const msg = entry.message || "";
    if (msg.startsWith("fill caches start")) {
      inProgress = true;
    } else if (msg.startsWith("fill caches end")) {
      inProgress = false;
    }
  }
  return inProgress;
}

function requestFilesRefresh({ force = false } = {}) {
  const now = Date.now();
  if (!force && now - lastFilesRefreshAt < FILES_REFRESH_MIN_MS) {
    return filesRefreshInFlight || Promise.resolve();
  }
  lastFilesRefreshAt = now;
  filesRefreshInFlight = refreshFiles().finally(() => {
    filesRefreshInFlight = null;
  });
  return filesRefreshInFlight;
}

const CHANCE_IDS = [
  "chance-five",
  "chance-four",
  "chance-three",
  "chance-two",
  "chance-one",
  "chance-unrated",
];
const CHANCE_RATING_IDS = CHANCE_IDS.slice(0, 5);
const CHANCE_DEFAULTS = {
  "chance-five": 30,
  "chance-four": 20,
  "chance-three": 10,
  "chance-two": 10,
  "chance-one": 0,
  "chance-unrated": 30,
};
/** One block per 0, 10, …, 90/100%. */
const CHANCE_BLOCKS = "⠀▁▂▃▄▅▆▇▉▀";

function chanceBlock(pct) {
  const idx = Math.max(0, Math.min(CHANCE_BLOCKS.length - 1, Math.round(pct / 10)));
  return CHANCE_BLOCKS[idx];
}

function formatChanceBlocksFromPct(chances) {
  return CHANCE_IDS.map((id) => chanceBlock(chances[id])).join("");
}

function formatChancePercentsFromPct(chances) {
  return CHANCE_IDS.map((id) => chances[id]).join(" | ");
}

function distToChancePcts(dist) {
  return {
    "chance-five": Math.round(dist.five * 100),
    "chance-four": Math.round(dist.four * 100),
    "chance-three": Math.round(dist.three * 100),
    "chance-two": Math.round(dist.two * 100),
    "chance-one": Math.round(dist.one * 100),
    "chance-unrated": Math.round(dist.unrated * 100),
  };
}

function formatChanceBlocks(dist) {
  return formatChanceBlocksFromPct(distToChancePcts(dist));
}

function formatChancePercents(dist) {
  return formatChancePercentsFromPct(distToChancePcts(dist));
}

function snapChancePct(n) {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n / 10) * 10));
}

function sumChances(chances, ids = CHANCE_IDS) {
  return ids.reduce((sum, id) => sum + chances[id], 0);
}

/** Reduce lowest positive among `ids` until `need` is removed (10% steps). */
function reduceLowestPositive(chances, ids, need) {
  let remaining = need;
  while (remaining > 0) {
    let bestId = null;
    let bestVal = Infinity;
    for (const id of ids) {
      const val = chances[id];
      if (val > 0 && val < bestVal) {
        bestId = id;
        bestVal = val;
      }
    }
    if (bestId == null) break;
    const take = Math.min(bestVal, remaining);
    chances[bestId] -= take;
    remaining -= take;
  }
  return remaining;
}

function fillChanceSelect(select, selected) {
  select.innerHTML = "";
  for (let pct = 0; pct <= 100; pct += 10) {
    const option = document.createElement("option");
    option.value = String(pct);
    option.textContent = String(pct);
    if (pct === selected) option.selected = true;
    select.appendChild(option);
  }
}

function chancesFromDist(dist) {
  const chances = {
    "chance-five": snapChancePct(dist.five * 100),
    "chance-four": snapChancePct(dist.four * 100),
    "chance-three": snapChancePct(dist.three * 100),
    "chance-two": snapChancePct(dist.two * 100),
    "chance-one": snapChancePct(dist.one * 100),
    "chance-unrated": snapChancePct(dist.unrated * 100),
  };
  const total = sumChances(chances);
  if (total !== 100) {
    const ratingsSum = sumChances(chances, CHANCE_RATING_IDS);
    const rest = 100 - ratingsSum;
    if (rest >= 0) {
      chances["chance-unrated"] = rest;
    } else {
      chances["chance-unrated"] = 0;
      reduceLowestPositive(chances, CHANCE_RATING_IDS, -rest);
    }
  }
  return chances;
}

function rebalanceChanceMap(chances, changedId) {
  let total = sumChances(chances);
  if (total === 100) return chances;
  if (changedId !== "chance-unrated") {
    const ratingsSum = sumChances(chances, CHANCE_RATING_IDS);
    const rest = 100 - ratingsSum;
    if (rest >= 0) {
      chances["chance-unrated"] = rest;
    } else {
      chances["chance-unrated"] = 0;
      const others = CHANCE_RATING_IDS.filter((id) => id !== changedId);
      reduceLowestPositive(chances, others, -rest);
      total = sumChances(chances);
      if (total > 100) {
        reduceLowestPositive(chances, CHANCE_RATING_IDS, total - 100);
      }
    }
  } else if (total < 100) {
    chances["chance-five"] = Math.min(100, chances["chance-five"] + (100 - total));
    total = sumChances(chances);
    if (total < 100) {
      for (const id of CHANCE_RATING_IDS) {
        if (total >= 100) break;
        const room = 100 - chances[id];
        const add = Math.min(room, 100 - total);
        chances[id] += add;
        total += add;
      }
    }
  } else {
    reduceLowestPositive(chances, CHANCE_RATING_IDS, total - 100);
  }
  return chances;
}

function chancesToDistribution(chances) {
  return {
    five: chances["chance-five"] / 100,
    four: chances["chance-four"] / 100,
    three: chances["chance-three"] / 100,
    two: chances["chance-two"] / 100,
    one: chances["chance-one"] / 100,
    unrated: chances["chance-unrated"] / 100,
  };
}

const DEFAULT_INTENT_PLATFORMS = ["soundcloud", "hearthisat", "bandcamp", "youtube"];
const PLATFORM_LABELS = {
  soundcloud: "SoundCloud",
  hearthisat: "hearthis.at",
  bandcamp: "Bandcamp",
  youtube: "YouTube",
};
const PLATFORM_SVG = {
  soundcloud:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M1.75 12.85c0 .46.37.84.84.84h.42c.46 0 .84-.38.84-.84V9.6c0-.46-.38-.84-.84-.84h-.42c-.47 0-.84.38-.84.84v3.25zm3.36 2.1c0 .46.38.84.84.84h.42c.46 0 .84-.38.84-.84V7.5c0-.46-.38-.84-.84-.84h-.42c-.46 0-.84.38-.84.84v7.45zm3.37.42c0 .46.37.84.84.84h.42c.46 0 .84-.38.84-.84V6.2c0-.46-.38-.84-.84-.84h-.42c-.47 0-.84.38-.84.84v9.17zm3.36.21V5.36c0-.7.57-1.26 1.26-1.26.7 0 1.26.56 1.26 1.26v10.22h2.94c2.52 0 4.56-2.04 4.56-4.56 0-2.4-1.86-4.36-4.21-4.54a3.78 3.78 0 0 0-7.07 1.84v7.96c0 .46.38.84.84.84h.42c.01 0 .01 0 0 0z"/></svg>',
  hearthisat:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2a7 7 0 0 0-7 7v3.2A3.8 3.8 0 0 0 8.8 16H10v4h4v-4h1.2A3.8 3.8 0 0 0 19 12.2V9a7 7 0 0 0-7-7zm-2.5 8.5a1.2 1.2 0 1 1 0-2.4 1.2 1.2 0 0 1 0 2.4zm5 0a1.2 1.2 0 1 1 0-2.4 1.2 1.2 0 0 1 0 2.4z"/></svg>',
  bandcamp:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M0 18.75l7.06-13.5H24l-7.06 13.5H0z"/></svg>',
  youtube:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M23.5 7.2a3 3 0 0 0-2.1-2.1C19.5 4.6 12 4.6 12 4.6s-7.5 0-9.4.5A3 3 0 0 0 .5 7.2 31.5 31.5 0 0 0 0 12a31.5 31.5 0 0 0 .5 4.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31.5 31.5 0 0 0 24 12a31.5 31.5 0 0 0-.5-4.8zM9.75 15.02V8.98L15.5 12l-5.75 3.02z"/></svg>',
};

/**
 * Platform icon link to an artist or release page (catalog + player).
 * @param {string|null|undefined} platform
 * @param {string|null|undefined} href
 * @param {{ page?: "artist"|"release" }} [options]
 * @returns {HTMLAnchorElement|null}
 */
function createSourcePageLink(platform, href, options = {}) {
  const url = String(href || "").trim();
  if (!url) return null;
  const page = options.page === "release" ? "release" : "artist";
  const platformLabel = PLATFORM_LABELS[platform] || platform || "source";
  const openTip = `Open ${page} page on ${platformLabel}`;
  const link = document.createElement("a");
  link.className = "artist-link";
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.removeAttribute("title");
  link.setAttribute("aria-label", openTip);
  link.dataset.tip = openTip;
  if (platform && PLATFORM_SVG[platform]) {
    const icon = document.createElement("span");
    icon.className = "artist-source-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = PLATFORM_SVG[platform];
    link.appendChild(icon);
  } else {
    link.textContent = "↗";
  }
  return link;
}

const CHANCE_FIELD_META = [
  { id: "chance-five", label: "5★", title: "Share of the sequence for 5★ releases" },
  { id: "chance-four", label: "4★", title: "Share of the sequence for 4★ releases" },
  { id: "chance-three", label: "3★", title: "Share of the sequence for 3★ releases" },
  { id: "chance-two", label: "2★", title: "Share of the sequence for 2★ releases" },
  { id: "chance-one", label: "1★", title: "Share of the sequence for 1★ releases" },
  { id: "chance-unrated", label: "—", title: "Share of the sequence for unrated releases" },
];

/**
 * Shared create/edit intent composer: short name + ✓×, then Tags/Artists/Sources/chances.
 * @param {HTMLElement} root
 * @param {{
 *   values?: {
 *     name?: string,
 *     tags?: string[],
 *     artist_ids?: string[],
 *     platforms?: string[],
 *     distribution?: {five:number,four:number,three:number,two:number,one:number,unrated:number},
 *   },
 *   saveLabel?: string,
 *   onSave: (values: {
 *     name: string,
 *     tags: string[],
 *     artist_ids: string[],
 *     platforms: string[],
 *     distribution: {five:number,four:number,three:number,two:number,one:number,unrated:number},
 *   }) => Promise<void> | void,
 *   onCancel: () => void,
 * }} options
 */
function mountIntentComposer(root, options) {
  const initial = options.values || {};
  root.classList.add("intent-composer");
  root.replaceChildren();

  const nameRow = document.createElement("div");
  nameRow.className = "intent-form-name-row";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.className = "intent-form-name";
  nameInput.required = true;
  nameInput.placeholder = "Name";
  nameInput.setAttribute("aria-label", "Name");
  nameInput.value = initial.name || "";
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  setSymbolButton(saveBtn, BTN.save, options.saveLabel || "Save");
  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  setSymbolButton(cancelBtn, BTN.cancel, "Cancel");
  nameRow.appendChild(nameInput);
  nameRow.appendChild(saveBtn);
  nameRow.appendChild(cancelBtn);

  const meta = document.createElement("div");
  meta.className = "intent-form-meta";

  const tagsRow = document.createElement("div");
  tagsRow.className = "intent-form-meta-row";
  tagsRow.title =
    "Empty tags alone = untagged only. With artists selected, empty tags include tagged and untagged.";
  const tagsLabel = document.createElement("span");
  tagsLabel.className = "intent-form-meta-label";
  tagsLabel.textContent = "Tags:";
  const tagsMount = document.createElement("div");
  tagsMount.className = "tag-editor";
  tagsMount.setAttribute("aria-label", "Intent filter tags");
  tagsRow.appendChild(tagsLabel);
  tagsRow.appendChild(tagsMount);

  const artistsRow = document.createElement("div");
  artistsRow.className = "intent-form-meta-row";
  artistsRow.title = "Optional. Leave empty for no artist filter. Selected artists match by OR.";
  const artistsLabel = document.createElement("span");
  artistsLabel.className = "intent-form-meta-label";
  artistsLabel.textContent = "Artists:";
  const artistsMount = document.createElement("div");
  artistsMount.className = "tag-editor";
  artistsMount.setAttribute("aria-label", "Intent artist filter");
  artistsRow.appendChild(artistsLabel);
  artistsRow.appendChild(artistsMount);

  const sourcesRow = document.createElement("div");
  sourcesRow.className = "intent-form-meta-row";
  sourcesRow.title =
    "Sources start on. Grey one out to exclude it. At least one must stay active.";
  const sourcesLabel = document.createElement("span");
  sourcesLabel.className = "intent-form-meta-label";
  sourcesLabel.textContent = "Sources:";
  const platformsRoot = document.createElement("div");
  platformsRoot.className = "source-toggles";
  platformsRoot.setAttribute("role", "group");
  platformsRoot.setAttribute("aria-label", "Sources");
  for (const platform of DEFAULT_INTENT_PLATFORMS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "source-toggle";
    btn.dataset.platform = platform;
    btn.setAttribute("aria-pressed", "true");
    btn.title = PLATFORM_LABELS[platform] || platform;
    btn.setAttribute("aria-label", PLATFORM_LABELS[platform] || platform);
    btn.innerHTML = PLATFORM_SVG[platform] || "";
    platformsRoot.appendChild(btn);
  }
  sourcesRow.appendChild(sourcesLabel);
  sourcesRow.appendChild(platformsRoot);

  const chancesDetails = document.createElement("details");
  chancesDetails.className = "intent-chances";
  const chancesSummary = document.createElement("summary");
  chancesSummary.className = "has-tip";
  const chanceGrid = document.createElement("div");
  chanceGrid.className = "chance-grid";
  /** @type {Map<string, HTMLSelectElement>} */
  const chanceSelects = new Map();
  for (const field of CHANCE_FIELD_META) {
    const label = document.createElement("label");
    label.title = field.title;
    label.appendChild(document.createTextNode(field.label));
    const select = document.createElement("select");
    select.dataset.chance = field.id;
    select.title = field.title;
    fillChanceSelect(select, CHANCE_DEFAULTS[field.id]);
    chanceSelects.set(field.id, select);
    label.appendChild(select);
    chanceGrid.appendChild(label);
  }
  chancesDetails.appendChild(chancesSummary);
  chancesDetails.appendChild(chanceGrid);

  meta.appendChild(tagsRow);
  meta.appendChild(artistsRow);
  meta.appendChild(sourcesRow);
  meta.appendChild(chancesDetails);
  root.appendChild(nameRow);
  root.appendChild(meta);

  const tagEditor = mountTagEditor(tagsMount, {
    tags: initial.tags || [],
    async onAdd() {},
    async onRemove() {},
  });
  const artistEditor = mountArtistEditor(artistsMount, {
    artists: [],
    async onAdd() {},
    async onRemove() {},
  });

  function platformButtons() {
    return Array.from(platformsRoot.querySelectorAll(".source-toggle"));
  }

  function readPlatforms() {
    return platformButtons()
      .filter((btn) => btn.getAttribute("aria-pressed") === "true")
      .map((btn) => btn.dataset.platform)
      .filter(Boolean);
  }

  function writePlatforms(platforms) {
    const wanted = new Set(
      platforms && platforms.length ? platforms : DEFAULT_INTENT_PLATFORMS,
    );
    for (const btn of platformButtons()) {
      btn.setAttribute(
        "aria-pressed",
        wanted.has(btn.dataset.platform) ? "true" : "false",
      );
    }
  }

  function readChances() {
    const chances = {};
    for (const id of CHANCE_IDS) {
      chances[id] = Number(chanceSelects.get(id)?.value || 0);
    }
    return chances;
  }

  function writeChances(chances) {
    for (const id of CHANCE_IDS) {
      const select = chanceSelects.get(id);
      if (select) select.value = String(chances[id]);
    }
    updateChanceSummary();
  }

  function updateChanceSummary() {
    const chances = readChances();
    chancesSummary.textContent = `Rating chances: ${formatChanceBlocksFromPct(chances)}`;
    chancesSummary.removeAttribute("title");
    chancesSummary.classList.add("has-tip");
    chancesSummary.dataset.tip = formatChancePercentsFromPct(chances);
  }

  function rebalanceChances(changedId) {
    writeChances(rebalanceChanceMap(readChances(), changedId));
  }

  for (const [id, select] of chanceSelects) {
    select.addEventListener("change", () => rebalanceChances(id));
  }

  platformsRoot.addEventListener("click", (event) => {
    const btn = event.target.closest(".source-toggle");
    if (!btn || !platformsRoot.contains(btn)) return;
    const pressed = btn.getAttribute("aria-pressed") === "true";
    if (pressed) {
      if (readPlatforms().length <= 1) return;
      btn.setAttribute("aria-pressed", "false");
      return;
    }
    btn.setAttribute("aria-pressed", "true");
  });

  function getValues() {
    const chances = readChances();
    return {
      name: nameInput.value.trim(),
      tags: tagEditor.getTags(),
      artist_ids: artistEditor.getIds(),
      platforms: readPlatforms(),
      distribution: chancesToDistribution(chances),
      chancePcts: chances,
    };
  }

  function setValues(next) {
    nameInput.value = next.name || "";
    tagEditor.setTags(next.tags || []);
    artistEditor.setIds(next.artist_ids || []);
    writePlatforms(next.platforms || DEFAULT_INTENT_PLATFORMS);
    if (next.distribution) writeChances(chancesFromDist(next.distribution));
    else writeChances({ ...CHANCE_DEFAULTS });
    chancesDetails.open = false;
  }

  setValues(initial);
  updateChanceSummary();

  let saving = false;
  saveBtn.addEventListener("click", async () => {
    if (saving) return;
    const values = getValues();
    if (!values.name) {
      nameInput.focus();
      return;
    }
    if (sumChances(values.chancePcts) !== 100) {
      const status = document.getElementById("intent-status");
      if (status) {
        status.textContent = `Rating chances must sum to 100% (got ${sumChances(values.chancePcts)})`;
      }
      return;
    }
    if (!values.platforms.length) {
      const status = document.getElementById("intent-status");
      if (status) status.textContent = "Keep at least one source active";
      return;
    }
    saving = true;
    saveBtn.disabled = true;
    try {
      await options.onSave({
        name: values.name,
        tags: values.tags,
        artist_ids: values.artist_ids,
        platforms: values.platforms,
        distribution: values.distribution,
      });
    } finally {
      saving = false;
      saveBtn.disabled = false;
    }
  });
  cancelBtn.addEventListener("click", () => options.onCancel());

  return {
    getValues,
    setValues,
    focusName() {
      nameInput.focus();
      nameInput.select?.();
    },
    isBusy() {
      return saving || tagEditor.isBusy() || artistEditor.isBusy();
    },
    syncArtists(selectedIds) {
      if (!artistEditor.isBusy()) artistEditor.setIds(selectedIds);
    },
    getArtistIds() {
      return artistEditor.getIds();
    },
    destroy() {
      tagEditor.destroy();
      artistEditor.destroy();
      root.replaceChildren();
      root.classList.remove("intent-composer");
    },
  };
}

async function refreshIntentArtistOptions() {
  const createIds = createComposer?.getArtistIds() || [];
  const editIds = editComposer?.getArtistIds() || [];
  try {
    const res = await fetch("/api/artists");
    const data = await res.json();
    const artists = (data.artists || []).map((artist) => ({
      id: artist.id,
      name: artist.name,
    }));
    catalogArtistsCache = artists;
    artistNameById = new Map(artists.map((artist) => [artist.id, artist.name]));
    createComposer?.syncArtists(createIds);
    editComposer?.syncArtists(editIds);
  } catch (err) {
    console.error(err);
  }
}

function isCreateFormOpen() {
  return document.getElementById("intent-form")?.classList.contains("add-form-open");
}

function collapseCreateForm() {
  const form = document.getElementById("intent-form");
  const mount = document.getElementById("intent-create-composer");
  const expandBtn = document.getElementById("intent-expand");
  if (createComposer) {
    createComposer.destroy();
    createComposer = null;
  }
  if (mount) mount.hidden = true;
  form?.classList.remove("add-form-open");
  if (expandBtn) {
    expandBtn.hidden = false;
    setSymbolButton(expandBtn, BTN.add, "Create intent");
  }
}

function expandCreateForm() {
  const form = document.getElementById("intent-form");
  const mount = document.getElementById("intent-create-composer");
  const expandBtn = document.getElementById("intent-expand");
  if (!form || !mount || !expandBtn) return;
  if (editingIntentId) {
    editingIntentId = null;
    void refreshIntents({ force: true });
  }
  form.classList.add("add-form-open");
  mount.hidden = false;
  expandBtn.hidden = true;
  if (createComposer) createComposer.destroy();
  createComposer = mountIntentComposer(mount, {
    saveLabel: "Create intent",
    values: {
      name: "",
      tags: [],
      artist_ids: [],
      platforms: DEFAULT_INTENT_PLATFORMS,
      distribution: {
        five: CHANCE_DEFAULTS["chance-five"] / 100,
        four: CHANCE_DEFAULTS["chance-four"] / 100,
        three: CHANCE_DEFAULTS["chance-three"] / 100,
        two: CHANCE_DEFAULTS["chance-two"] / 100,
        one: CHANCE_DEFAULTS["chance-one"] / 100,
        unrated: CHANCE_DEFAULTS["chance-unrated"] / 100,
      },
    },
    async onSave(values) {
      const status = document.getElementById("intent-status");
      status.textContent = "Creating intent…";
      try {
        const res = await fetch("/api/intents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(values),
        });
        const data = await res.json();
        if (!res.ok) {
          const detail = data.detail;
          status.textContent =
            typeof detail === "string"
              ? detail
              : detail?.[0]?.msg || "Create intent failed";
          return;
        }
        const filling = data.fill_in_progress ? " · filling caches…" : "";
        status.textContent = `Created “${data.intent.name}”${filling}`;
        collapseCreateForm();
        await refreshIntents({ force: true });
        await refreshFiles();
      } catch (err) {
        status.textContent = "Create intent request failed";
        console.error(err);
      }
    },
    onCancel() {
      document.getElementById("intent-status").textContent = "";
      collapseCreateForm();
    },
  });
  createComposer.focusName();
}

function resetIntentForm() {
  collapseCreateForm();
}

function hoursUntilExpiry(iso) {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms)) return "";
  if (ms <= 0) return "0";
  return String(Math.round((ms / 3600000) * 10) / 10);
}

function beginEditIntent(intent) {
  if (isCreateFormOpen()) collapseCreateForm();
  editingIntentId = intent.id;
  void refreshIntents({ force: true });
}

function cancelInlineIntentEdit() {
  editingIntentId = null;
  if (editComposer) {
    editComposer.destroy();
    editComposer = null;
  }
  void refreshIntents({ force: true });
}

function knownDevices() {
  const devices = [];
  if (localDeviceId) {
    devices.push({
      id: localDeviceId,
      name: document.getElementById("device-name").textContent || "this device",
      defaultHours: "8",
    });
  }
  for (const peer of peersCache) {
    devices.push({
      id: peer.id,
      name: peer.name,
      defaultHours: "2",
    });
  }
  return devices;
}

function deviceName(deviceId) {
  const known = knownDevices().find((d) => d.id === deviceId);
  if (known) return known.name;
  return String(deviceId).slice(0, 8);
}

function formatActivityTs(ts) {
  if (!ts) return "";
  const match = String(ts).match(/T(\d{2}:\d{2}:\d{2})/);
  return match ? match[1] : ts;
}

async function refreshActivity() {
  const list = document.getElementById("activity-list");
  if (!list) return;
  try {
    const res = await fetch("/api/activity");
    const data = await res.json();
    const chronological = Array.isArray(data.entries) ? data.entries : [];
    const entries = chronological.slice().reverse();
    list.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement("li");
      empty.className = "muted";
      empty.textContent = "No activity yet";
      list.appendChild(empty);
    } else {
      for (const entry of entries) {
        const li = document.createElement("li");
        li.className = `level-${entry.level || "INFO"}`;
        const time = document.createElement("span");
        time.className = "activity-ts";
        time.textContent = formatActivityTs(entry.ts);
        li.appendChild(time);
        li.appendChild(document.createTextNode(entry.message || ""));
        list.appendChild(li);
      }
    }

    const filling = fillInProgressFromEntries(chronological);
    if (filling) {
      await requestFilesRefresh();
    } else if (fillWasInProgress) {
      await requestFilesRefresh({ force: true });
      await refreshIntents();
    }
    fillWasInProgress = filling;
  } catch (err) {
    console.error(err);
  }
}

async function refreshHealth() {
  const el = document.getElementById("health");
  const nameEl = document.getElementById("device-name");
  const meteredToggle = document.getElementById("metered-toggle");
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    el.textContent = data.ok ? `ok (v${data.version})` : "degraded";
    nameEl.textContent = data.device || "unknown";
    localDeviceId = data.device_id || null;
    currentMixId = data.current_mix_id || null;
    if (meteredToggle) {
      meteredToggle.checked = Boolean(data.metered);
    }
    applyTrustedPeersList(peersCache);
  } catch (err) {
    el.textContent = "unreachable";
    console.error(err);
  }
}

let pairPollTimer = null;

function stopPairPoll() {
  if (pairPollTimer != null) {
    clearInterval(pairPollTimer);
    pairPollTimer = null;
  }
}

function startPairPoll() {
  stopPairPoll();
  pairPollTimer = setInterval(() => {
    void refreshPairingSession();
  }, 1000);
}

function collapsePairForm() {
  const url = document.getElementById("peer-url");
  const pin = document.getElementById("pair-code");
  if (url) url.value = "";
  if (pin) pin.value = "";
  pairCollapsible?.collapse();
}

function renderPairSession(session) {
  const hostPanel = document.getElementById("pair-host-panel");
  const confirmPanel = document.getElementById("pair-confirm-panel");
  const cancelBtn = document.getElementById("pair-cancel-btn");
  const qr = document.getElementById("qr");
  const pinEl = document.getElementById("pair-pin");
  const payloadEl = document.getElementById("pairing-payload");
  if (!session || !session.active) {
    hostPanel.hidden = true;
    confirmPanel.hidden = true;
    cancelBtn.hidden = true;
    qr.hidden = true;
    pinEl.value = "";
    stopPairPoll();
    return;
  }
  pairCollapsible?.expand();
  cancelBtn.hidden = false;
  if (session.role === "host" && session.state === "waiting") {
    hostPanel.hidden = false;
    confirmPanel.hidden = true;
    if (session.pin) {
      pinEl.value = session.pin;
    }
    if (session.offer) {
      payloadEl.textContent = JSON.stringify(session.offer, null, 2);
      qr.hidden = false;
      qr.src = `/api/pairing/qr.png?t=${Date.now()}`;
    }
  } else if (session.state === "pending_confirm") {
    hostPanel.hidden = session.role !== "host";
    confirmPanel.hidden = false;
    document.getElementById("pair-peer-name").textContent = session.peer_name || "peer";
    document.getElementById("pair-sas").textContent = session.sas || "…";
    if (session.role === "host" && session.pin) {
      pinEl.value = session.pin;
    }
  } else if (session.state === "complete") {
    confirmPanel.hidden = true;
    hostPanel.hidden = true;
    cancelBtn.hidden = true;
    pinEl.value = "";
    stopPairPoll();
  }
}

async function refreshPairing() {
  const res = await fetch("/api/pairing");
  const payload = await res.json();
  localFingerprint = payload.fingerprint || payload.short_code || null;
  localPriority = payload.priority != null ? payload.priority : null;
  applyTrustedPeersList(peersCache);
  await refreshPairingSession();
}

async function refreshPairingSession() {
  const res = await fetch("/api/pair/session?include_pin=true");
  const session = await res.json();
  renderPairSession(session);
  if (session.active && session.state === "pending_confirm") {
    // Guest may finish after host confirms.
    const refresh = await fetch("/api/pair/session/refresh", { method: "POST" });
    const data = await refresh.json();
    if (data.complete && data.peer) {
      document.getElementById("pair-status").textContent = `Paired with ${data.peer.name}`;
      renderPairSession(data.session || { active: false });
      collapsePairForm();
      await refreshPeers();
      await refreshIntents({ force: true });
      stopPairPoll();
    }
  }
}

function pairCandidatesSignature(candidates) {
  return (candidates || [])
    .map(
      (c) =>
        `${c.locator || ""}|${c.name || ""}|${c.fingerprint || c.short_code || ""}|${c.pairing ? 1 : 0}`,
    )
    .join("\n");
}

function fillPairCandidateSelect(candidates, previousValue) {
  const select = document.getElementById("pair-candidate");
  if (!select) return;
  const previous = previousValue != null ? previousValue : select.value;
  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = candidates.length
    ? "Select discovered peer…"
    : "No peers discovered";
  select.appendChild(placeholder);
  for (const candidate of candidates) {
    const opt = document.createElement("option");
    opt.value = candidate.locator || "";
    const mark = candidate.pairing ? " · pairing open" : "";
    opt.textContent = `${candidate.name} (${candidate.fingerprint || candidate.short_code || "?"})${mark}`;
    select.appendChild(opt);
  }
  if (previous) {
    select.value = previous;
  }
  select.dataset.candidatesSig = pairCandidatesSignature(candidates);
}

function applyTrustedPeersList(peers) {
  peersCache = peers || [];
  const list = document.getElementById("peer-list");
  if (!list) return;
  list.innerHTML = "";
  const selfLi = document.createElement("li");
  selfLi.className = "peer-self";
  const selfName =
    document.getElementById("device-name")?.textContent?.trim() || "this device";
  const selfPrio =
    localPriority != null ? ` (priority ${localPriority})` : "";
  const selfFp = localFingerprint ? ` · ${localFingerprint}` : "";
  const selfStrong = document.createElement("strong");
  selfStrong.textContent = `${selfName}${selfPrio}${selfFp}`;
  selfLi.appendChild(selfStrong);
  list.appendChild(selfLi);
  if (!peersCache.length) {
    return;
  }
  for (const peer of peersCache) {
    const li = document.createElement("li");
    li.className = "peer-row";
    const label = document.createElement("span");
    const fp = peer.fingerprint ? ` · ${peer.fingerprint}` : "";
    label.textContent = `${peer.name} (priority ${peer.priority})${fp}`;
    li.appendChild(label);
    const unpairBtn = document.createElement("button");
    unpairBtn.type = "button";
    unpairBtn.className = "peer-unpair";
    bindConfirmDelete(unpairBtn, {
      label: `Unpair ${peer.name}`,
      onConfirm: async () => {
        const status = document.getElementById("sync-status");
        if (status) status.textContent = `Unpairing ${peer.name}…`;
        try {
          const res = await fetch(`/api/peers/${peer.id}/unpair`, {
            method: "POST",
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            const detail = data.detail;
            if (status) {
              status.textContent =
                typeof detail === "string"
                  ? detail
                  : detail?.[0]?.msg || "Unpair failed";
            }
            return;
          }
          applyPeersPayload(data);
          if (status) status.textContent = `Unpaired ${peer.name}`;
        } catch (err) {
          if (status) status.textContent = "Unpair request failed";
          console.error(err);
        }
      },
    });
    li.appendChild(unpairBtn);
    list.appendChild(li);
  }
}

function applyPeersPayload(data) {
  applyTrustedPeersList(data.peers || []);
  fillPairCandidateSelect(data.candidates || []);
}

async function refreshPeers() {
  const res = await fetch("/api/peers");
  const data = await res.json();
  applyPeersPayload(data);
}

let pairCandidateRefreshing = false;

async function refreshPairCandidatesFromDiscovery() {
  if (pairCandidateRefreshing) return;
  pairCandidateRefreshing = true;
  const select = document.getElementById("pair-candidate");
  const previous = select?.value || "";
  // Keep current options visible while LAN browse runs; rewrite only if the set changed.
  try {
    const res = await fetch("/api/discovery/refresh", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      return;
    }
    const next = data.candidates || [];
    const nextSig = pairCandidatesSignature(next);
    const prevSig = select?.dataset.candidatesSig || "";
    applyTrustedPeersList(data.peers || []);
    if (nextSig !== prevSig) {
      fillPairCandidateSelect(next, previous);
    }
  } catch (err) {
    console.error(err);
  } finally {
    pairCandidateRefreshing = false;
  }
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}`;
}

/**
 * Clickable ★★★☆☆ rating control. Clearing a vote is not supported.
 * @param {HTMLElement} root
 * @param {{
 *   stars?: number|null,
 *   interactive?: boolean,
 *   onRate?: (stars: number) => void|Promise<void>,
 * }} [options]
 */
function mountStarRating(root, { stars = null, interactive = true, onRate = null } = {}) {
  root.classList.add("star-rating");
  root.classList.toggle("star-rating-readonly", !interactive);
  if (interactive) {
    root.setAttribute("role", "radiogroup");
  } else {
    root.setAttribute("role", "img");
  }

  let current = stars != null && stars !== "" ? Number(stars) : null;
  let busy = false;

  function paint() {
    const filled = current != null ? current : 0;
    root.dataset.stars = current != null ? String(current) : "";
    root.replaceChildren();
    root.setAttribute(
      "aria-label",
      current != null ? `${current} of 5 stars` : "Unrated",
    );
    for (let s = 1; s <= 5; s += 1) {
      const isFilled = s <= filled;
      if (!interactive) {
        const mark = document.createElement("span");
        mark.className = `star-rating-star ${isFilled ? "is-filled" : "is-empty"}`;
        mark.textContent = isFilled ? "★" : "☆";
        mark.setAttribute("aria-hidden", "true");
        root.appendChild(mark);
        continue;
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `star-rating-star ${isFilled ? "is-filled" : "is-empty"}`;
      btn.textContent = isFilled ? "★" : "☆";
      btn.setAttribute("role", "radio");
      btn.setAttribute("aria-checked", current === s ? "true" : "false");
      btn.setAttribute("aria-label", `Rate ${s} star${s === 1 ? "" : "s"}`);
      btn.title = `Rate ${s}★`;
      btn.disabled = busy;
      btn.addEventListener("click", async (event) => {
        event.stopPropagation();
        if (!onRate || busy) return;
        busy = true;
        paint();
        try {
          await onRate(s);
          current = s;
        } finally {
          busy = false;
          paint();
        }
      });
      root.appendChild(btn);
    }
  }

  paint();
  return {
    setStars(value) {
      current = value != null && value !== "" ? Number(value) : null;
      paint();
    },
    getStars() {
      return current;
    },
    isBusy() {
      return busy;
    },
  };
}

/**
 * Shared annotate control kit (Rate, Tag, Reject / Undo / Un-reject).
 * Used by Player, Play history, and Catalog so later tickets edit one mount.
 * Product behaviour matches pre-ui-actions-01 surfaces (Catalog Rate still off).
 *
 * Row mode (`surface` catalog|history): builds stars + reject chrome + tag editor.
 * Player mode (`surface` "player"): binds long-lived roots from index.html.
 *
 * @param {{
 *   surface: "catalog"|"history"|"player",
 *   mix?: { id: string, stars?: number|null, tags?: string[], rejected?: boolean, reject_pending_until?: string|null },
 *   starsRoot: HTMLElement,
 *   actionsRoot?: HTMLElement,
 *   tagRoot?: HTMLElement,
 *   rejectBtn?: HTMLElement,
 *   undoBtn?: HTMLElement,
 *   statusEl?: HTMLElement,
 *   rateInteractive?: boolean,
 *   allowUnreject?: boolean,
 *   refreshAfterTag?: boolean,
 *   starsClass?: string,
 *   tagEditorClass?: string,
 *   onRate?: (stars: number) => void|Promise<void>,
 *   getMixId?: () => string|null,
 * }} options
 */
function mountAnnotateKit(options) {
  const surface = options.surface;
  if (surface === "player") {
    return mountPlayerAnnotateKit(options);
  }
  return mountRowAnnotateKit(options);
}

/**
 * @param {{
 *   surface: "catalog"|"history",
 *   mix: { id: string, stars?: number|null, tags?: string[], rejected?: boolean, reject_pending_until?: string|null },
 *   starsRoot: HTMLElement,
 *   actionsRoot: HTMLElement,
 *   rateInteractive?: boolean,
 *   allowUnreject?: boolean,
 *   refreshAfterTag?: boolean,
 *   starsClass?: string,
 *   tagEditorClass?: string,
 * }} options
 */
function mountRowAnnotateKit({
  surface,
  mix,
  starsRoot,
  actionsRoot,
  rateInteractive = true,
  allowUnreject = true,
  refreshAfterTag = false,
  starsClass = null,
  tagEditorClass = null,
}) {
  if (starsClass) starsRoot.className = starsClass;
  if (rateInteractive) {
    starsRoot.setAttribute("aria-label", "Rate release");
  }
  const starRating = mountStarRating(starsRoot, {
    stars: mix.stars,
    interactive: rateInteractive,
    async onRate(stars) {
      const rateRes = await fetch(`/api/mixes/${mix.id}/rate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stars }),
      });
      if (!rateRes.ok) {
        throw new Error("Rate failed");
      }
      await refreshMixes({ force: true });
      await refreshPlayer();
    },
  });

  const rejectClass =
    surface === "catalog" ? "catalog-reject" : "history-reject";
  const undoClass =
    surface === "catalog" ? "catalog-undo-reject" : "history-undo-reject";
  const unRejectClass =
    surface === "catalog" ? "catalog-un-reject" : "history-un-reject";
  const rejectBtn = document.createElement("button");
  rejectBtn.type = "button";
  rejectBtn.className = rejectClass;
  const undoBtn = document.createElement("button");
  undoBtn.type = "button";
  undoBtn.className = undoClass;
  const unRejectBtn = document.createElement("button");
  unRejectBtn.type = "button";
  unRejectBtn.className = unRejectClass;
  setSymbolButton(rejectBtn, BTN.reject, "Reject release");
  setSymbolButton(undoBtn, BTN.cancel, "Undo reject");
  setSymbolButton(unRejectBtn, BTN.unreject, "Un-reject release");

  syncRowAnnotateRejectButtons({
    rejectBtn,
    undoBtn,
    unRejectBtn,
    mix,
    allowUnreject,
  });

  rejectBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    const res = await fetch(`/api/mixes/${mix.id}/reject`, { method: "POST" });
    if (res.ok) {
      await refreshMixes({ force: true });
      await refreshPlayer();
    }
  });
  undoBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    const res = await fetch(`/api/mixes/${mix.id}/undo-reject`, {
      method: "POST",
    });
    if (res.ok) {
      clearCatalogRejectTimer(mix.id);
      await refreshMixes({ force: true });
      await refreshPlayer();
    }
  });
  if (allowUnreject) {
    unRejectBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const res = await fetch(`/api/mixes/${mix.id}/un-reject`, {
        method: "POST",
      });
      if (res.ok) {
        await refreshMixes({ force: true });
        await refreshPlayer();
        await refreshIntents();
      }
    });
  } else {
    unRejectBtn.hidden = true;
  }

  actionsRoot.appendChild(rejectBtn);
  actionsRoot.appendChild(undoBtn);
  if (allowUnreject) actionsRoot.appendChild(unRejectBtn);

  const tagEditorRoot = document.createElement("div");
  tagEditorRoot.className =
    tagEditorClass || `tag-editor ${surface}-tag-editor`;
  tagEditorRoot.addEventListener("click", (event) => event.stopPropagation());
  const handlers = mixTagHandlers(mix.id);
  const tagEditor = mountTagEditor(tagEditorRoot, {
    tags: mix.tags || [],
    async onAdd(tag) {
      await handlers.onAdd(tag);
      if (refreshAfterTag) {
        await refreshMixes({ force: true });
        await refreshPlayer();
      }
    },
    async onRemove(tag) {
      await handlers.onRemove(tag);
      if (refreshAfterTag) {
        await refreshMixes({ force: true });
        await refreshPlayer();
      }
    },
  });
  actionsRoot.appendChild(tagEditorRoot);

  return { starRating, tagEditor, rejectBtn, undoBtn, unRejectBtn };
}

/**
 * Visibility + pending-timer scheduling for Catalog / History reject chrome.
 */
function syncRowAnnotateRejectButtons({
  rejectBtn,
  undoBtn,
  unRejectBtn,
  mix,
  allowUnreject = true,
}) {
  const pendingUntil = mix.reject_pending_until;
  if (pendingUntil) {
    rejectBtn.hidden = true;
    if (unRejectBtn) unRejectBtn.hidden = true;
    undoBtn.hidden = false;
    scheduleCatalogRejectRefresh(mix.id, pendingUntil);
  } else if (mix.rejected) {
    rejectBtn.hidden = true;
    undoBtn.hidden = true;
    if (unRejectBtn) unRejectBtn.hidden = !allowUnreject;
    clearCatalogRejectTimer(mix.id);
  } else {
    rejectBtn.hidden = false;
    undoBtn.hidden = true;
    if (unRejectBtn) unRejectBtn.hidden = true;
    clearCatalogRejectTimer(mix.id);
  }
}

/**
 * Player annotate kit: long-lived stars / tags / Reject+Undo (no Un-reject).
 * @param {{
 *   starsRoot: HTMLElement,
 *   tagRoot: HTMLElement,
 *   rejectBtn: HTMLElement,
 *   undoBtn: HTMLElement,
 *   statusEl?: HTMLElement|null,
 *   getMixId: () => string|null,
 *   onRate: (stars: number) => void|Promise<void>,
 * }} options
 */
function mountPlayerAnnotateKit({
  starsRoot,
  tagRoot,
  rejectBtn,
  undoBtn,
  statusEl = null,
  getMixId,
  onRate,
}) {
  const starRating = mountStarRating(starsRoot, {
    stars: null,
    async onRate(stars) {
      await onRate(stars);
    },
  });
  const tagEditor = mountTagEditor(tagRoot, {
    tags: [],
    async onAdd(tag) {
      const mixId = getMixId();
      if (!mixId) throw new Error("Nothing to tag");
      await mixTagHandlers(mixId).onAdd(tag);
    },
    async onRemove(tag) {
      const mixId = getMixId();
      if (!mixId) throw new Error("Nothing to tag");
      await mixTagHandlers(mixId).onRemove(tag);
    },
  });

  rejectBtn.addEventListener("click", async () => {
    const status = document.getElementById("player-status");
    const player = await (await fetch("/api/player")).json();
    if (!player.current_mix_id) {
      if (status) status.textContent = "Nothing to reject";
      return;
    }
    try {
      const res = await fetch(`/api/mixes/${player.current_mix_id}/reject`, {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (status) status.textContent = data.detail || "Reject failed";
        return;
      }
      if (status) status.textContent = "Reject started — undo available briefly";
      await refreshPlayer();
      await refreshMixes();
    } catch (err) {
      if (status) status.textContent = "Reject request failed";
      console.error(err);
    }
  });

  undoBtn.addEventListener("click", async () => {
    const status = document.getElementById("player-status");
    const player = await (await fetch("/api/player")).json();
    if (!player.current_mix_id) {
      if (status) status.textContent = "Nothing to undo";
      return;
    }
    try {
      const res = await fetch(`/api/mixes/${player.current_mix_id}/undo-reject`, {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (status) status.textContent = data.detail || "Undo reject failed";
        return;
      }
      if (status) {
        status.textContent = data.undone ? "Reject undone" : "Nothing to undo";
      }
      await refreshPlayer();
      await refreshMixes();
    } catch (err) {
      if (status) status.textContent = "Undo reject request failed";
      console.error(err);
    }
  });

  function updateRejectControls(data) {
    if (!undoBtn || !rejectBtn) return;
    const until = data.reject_pending_until;
    clearRejectUndoTimer();
    if (until && data.current_mix_id) {
      undoBtn.hidden = false;
      rejectBtn.hidden = true;
      if (statusEl) {
        statusEl.hidden = false;
        statusEl.textContent =
          "Reject pending — undo available for a few seconds";
      }
      const ms = Date.parse(until) - Date.now();
      if (Number.isFinite(ms) && ms > 0) {
        rejectUndoTimer = setTimeout(async () => {
          await refreshPlayer();
          await refreshMixes();
          await refreshFiles();
        }, ms + 50);
      } else {
        // Window already elapsed; refresh flushes commit via pending_rejects.
        void (async () => {
          await refreshPlayer();
          await refreshMixes();
          await refreshFiles();
        })();
      }
    } else {
      undoBtn.hidden = true;
      rejectBtn.hidden = false;
      if (statusEl) {
        if (data.rejected) {
          statusEl.hidden = false;
          statusEl.textContent = "Rejected";
        } else {
          statusEl.hidden = true;
          statusEl.textContent = "";
        }
      }
    }
  }

  return { starRating, tagEditor, updateRejectControls };
}

function formatClock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

let playerSeekDragging = false;
let playerPollTimer = null;
let playerSeekTracks = [];
let playerSeekArtist = "";
/** Stable key for current marks layout; skip DOM rebuild while unchanged. */
let playerSeekMarksKey = "";
/** Track index currently highlighted (−1 = none). Survives poll refreshes. */
let playerSeekHotIndex = -1;
/** Stable key for #player-now; skip DOM rebuild while unchanged. */
let playerNowKey = "";
let playerCoverMixId = null;

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Seek labels show the track name only; strip a leading "Artist - " if present. */
function displayTrackTitle(rawTitle, artist) {
  const title = String(rawTitle || "").trim();
  if (!title) return "";
  const name = String(artist || "").trim();
  if (!name) return title;
  const stripped = title.replace(
    new RegExp(`^${escapeRegExp(name)}\\s*[-–—:]\\s*`, "i"),
    "",
  ).trim();
  return stripped || title;
}

/** True when focus is on an editable control inside el, or a tag editor is busy. */
function focusInside(el) {
  if (!el) return false;
  if (el.querySelector(".tag-editor.is-busy")) return true;
  const active = document.activeElement;
  if (!active || !el.contains(active)) return false;
  const tag = active.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function setPlayerPolling(playing) {
  if (playing) {
    if (playerPollTimer == null) {
      playerPollTimer = setInterval(() => {
        void refreshPlayer();
      }, 500);
    }
  } else if (playerPollTimer != null) {
    clearInterval(playerPollTimer);
    playerPollTimer = null;
  }
}

function trackIndexAtTimelineSeconds(tracks, seconds) {
  if (!Array.isArray(tracks) || tracks.length === 0) return -1;
  let remaining = Math.max(0, Number(seconds) || 0);
  const last = tracks.length - 1;
  for (let i = 0; i < tracks.length; i += 1) {
    const duration = Math.max(0, Number(tracks[i].duration_seconds) || 0);
    if (i === last || remaining < duration) {
      return i;
    }
    remaining -= duration;
  }
  return last;
}

function trackAtTimelineSeconds(tracks, seconds) {
  const index = trackIndexAtTimelineSeconds(tracks, seconds);
  return index < 0 ? null : tracks[index];
}

function trackStartSeconds(tracks, index) {
  let start = 0;
  for (let i = 0; i < index; i += 1) {
    start += Math.max(0, Number(tracks[i]?.duration_seconds) || 0);
  }
  return start;
}

function setSeekTrackHighlight(index) {
  playerSeekHotIndex = index;
  const marksEl = document.getElementById("player-seek-marks");
  if (!marksEl) return;
  for (const el of marksEl.querySelectorAll(
    ".player-seek-section, .player-seek-section-fill, .player-seek-label",
  )) {
    const hot = Number(el.dataset.trackIndex) === index;
    el.classList.toggle("is-hot", hot);
  }
}

function clearSeekTrackHighlight() {
  playerSeekHotIndex = -1;
  const marksEl = document.getElementById("player-seek-marks");
  if (!marksEl) return;
  for (const el of marksEl.querySelectorAll(
    ".player-seek-section.is-hot, .player-seek-section-fill.is-hot, .player-seek-label.is-hot",
  )) {
    el.classList.remove("is-hot");
  }
}

function seekMarksLayoutKey(tracks, duration, artist) {
  if (!Array.isArray(tracks) || tracks.length < 2) return "";
  return JSON.stringify({
    artist: String(artist || ""),
    duration: Math.max(0, Number(duration) || 0),
    tracks: tracks.map((track) => [
      String(track?.title || ""),
      Math.max(0, Number(track?.duration_seconds) || 0),
    ]),
  });
}

function syncSeekProgress(seekbar) {
  if (!seekbar) return;
  const max = Number(seekbar.max) || 0;
  const value = Number(seekbar.value) || 0;
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  seekbar.style.setProperty("--seek-progress", `${pct}%`);
}

async function seekToPlayerPosition(positionSeconds) {
  const status = document.getElementById("player-status");
  const seekbar = document.getElementById("player-seekbar");
  const position = Math.max(0, Math.round(Number(positionSeconds) || 0));
  lastKnownPositionSeconds = position;
  lastPlayheadCommitAt = Date.now();
  if (seekbar) {
    seekbar.value = String(position);
    syncSeekProgress(seekbar);
  }
  const currentEl = document.getElementById("player-time-current");
  if (currentEl) {
    currentEl.textContent = formatClock(position);
  }
  try {
    const res = await fetch("/api/player/seek", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_seconds: position }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (status) status.textContent = data.detail || "Seek failed";
      await refreshPlayer();
      return false;
    }
    if (status) {
      status.textContent = data.played
        ? `Seeked to ${formatClock(position)} · marked played`
        : `Seeked to ${formatClock(position)}`;
    }
    if (data.played && data.mix_id) {
      playheadPlayedNotifiedForMix = data.mix_id;
    }
    await refreshPlayer();
    await refreshMixes();
    await refreshFiles();
    await refreshIntents();
    return true;
  } catch (err) {
    if (status) status.textContent = "Seek request failed";
    console.error(err);
    await refreshPlayer();
    return false;
  }
}

async function seekToTrackStart(index) {
  if (index < 0 || index >= playerSeekTracks.length) return false;
  const position = trackStartSeconds(playerSeekTracks, index);
  return seekToPlayerPosition(position);
}

/** Linear-interpolated quantile of a non-empty numeric array (p in [0, 1]). */
function quantile(values, p) {
  const sorted = values.slice().sort((a, b) => a - b);
  if (sorted.length === 1) return sorted[0];
  const pos = (sorted.length - 1) * Math.max(0, Math.min(1, p));
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  const w = pos - lo;
  return sorted[lo] * (1 - w) + sorted[hi] * w;
}

/**
 * Vertical headroom for −60° seek labels.
 * Sized to the 80% quantile of title lengths so most labels clear the clip;
 * longer outliers may overhang / overlap (clip edge is raised to #player).
 */
function seekLabelHeadroomRem(tracks, artist) {
  const lengths = [];
  for (const track of tracks) {
    const text = displayTrackTitle(track.title, artist) || "";
    lengths.push(text.length);
  }
  const chars = lengths.length === 0 ? 0 : quantile(lengths, 0.8);
  // 0.7rem labels at −60°: vertical rise ≈ chars * charWidth * sin(60°) + gap.
  return Math.min(16, Math.max(3.5, chars * 0.28 + 0.7));
}

/**
 * Extend .player-clip upward so overflow:clip matches the #player top edge.
 * Tag UI stays outside .player-clip (sibling) and is not clipped.
 */
function syncPlayerSeekClipRise() {
  const player = document.getElementById("player");
  const clip = player?.querySelector(".player-clip");
  if (!player || !clip) return;
  clip.style.setProperty("--player-seek-clip-rise", "0px");
  const rise = Math.max(
    0,
    Math.round(clip.getBoundingClientRect().top - player.getBoundingClientRect().top),
  );
  clip.style.setProperty("--player-seek-clip-rise", `${rise}px`);
}

const PLAYER_COVER_MIN_REM = 4.5;
const PLAYER_COVER_MAX_REM = 14;
/** Target share of now-row width when title stays beside the cover. */
const PLAYER_COVER_SIDE_FRACTION = 0.35;
/** Target share when stacked (title under cover). */
const PLAYER_COVER_STACK_FRACTION = 0.45;

/**
 * Intrinsic one-line width of #player-now.
 * The title is a block that fills .player-below-text, so scrollWidth equals the
 * flex leftover (≈ current cover) and locks sizing. Range measures the text
 * without mutating layout (avoids ResizeObserver re-entry).
 */
function measurePlayerTitleIntrinsicWidth(title) {
  const range = document.createRange();
  range.selectNodeContents(title);
  return range.getBoundingClientRect().width;
}

/**
 * Layout-aware cover size + stack: grow with the now-row, shrink to keep the
 * title beside the cover when possible, otherwise stack and allow a larger cover.
 * Side-by-side uses the same max as stacked so large clients grow again when
 * the title still fits.
 * Always measures in the side-by-side state to avoid oscillation.
 */
function syncPlayerNowStack() {
  const row = document.querySelector("#player .player-now-row");
  const cover = document.getElementById("player-cover");
  const title = document.getElementById("player-now");
  if (!row || !title) return;
  row.classList.remove("is-stacked");
  const coverVisible = Boolean(cover && !cover.hidden);
  if (!coverVisible) {
    row.style.removeProperty("--player-cover-size");
    return;
  }
  const rootFont =
    Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const pxToRem = (px) => px / rootFont;
  const remToPx = (rem) => rem * rootFont;
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

  const styles = getComputedStyle(row);
  const gap = Number.parseFloat(styles.columnGap || styles.gap) || 0;
  const rowWidth = row.clientWidth;
  const titleNeeds = measurePlayerTitleIntrinsicWidth(title);
  const desiredRem = clamp(
    pxToRem(rowWidth * PLAYER_COVER_SIDE_FRACTION),
    PLAYER_COVER_MIN_REM,
    PLAYER_COVER_MAX_REM,
  );
  const maxSidePx = rowWidth - gap - titleNeeds;
  const minPx = remToPx(PLAYER_COVER_MIN_REM);

  if (maxSidePx >= minPx - 0.5) {
    const sizeRem = clamp(
      Math.min(desiredRem, pxToRem(maxSidePx)),
      PLAYER_COVER_MIN_REM,
      PLAYER_COVER_MAX_REM,
    );
    row.style.setProperty("--player-cover-size", `${sizeRem}rem`);
    return;
  }

  const stackedRem = clamp(
    pxToRem(rowWidth * PLAYER_COVER_STACK_FRACTION),
    PLAYER_COVER_MIN_REM,
    PLAYER_COVER_MAX_REM,
  );
  row.style.setProperty("--player-cover-size", `${stackedRem}rem`);
  row.classList.add("is-stacked");
}

/**
 * When intent wraps under ▶ Player ⓘ, stretch the select to full width.
 * Use heading bottom vs intent top — offsetTop alone false-positives when
 * align-items:center makes the taller select sit lower on the same row.
 */
function syncPlayerIntentWrap() {
  const row = document.querySelector("#player .player-heading-row");
  const heading = row?.querySelector(".section-heading");
  const top = row?.querySelector(".player-top");
  if (!row || !heading || !top) return;
  // Measure without the wrapped styles so flex wrap decides naturally.
  row.classList.remove("intent-wrapped");
  const headingBottom = heading.getBoundingClientRect().bottom;
  const topTop = top.getBoundingClientRect().top;
  const wrapped = topTop >= headingBottom - 1;
  row.classList.toggle("intent-wrapped", wrapped);
}

function syncPlayerChrome() {
  syncPlayerIntentWrap();
  syncPlayerNowStack();
  syncPlayerSeekClipRise();
}

function setSeekLabelHeadroom(seekRow, tracks, artist) {
  if (!seekRow) return;
  if (!tracks || tracks.length < 2) {
    seekRow.classList.remove("has-track-labels");
    seekRow.style.removeProperty("--seek-label-headroom");
    syncPlayerChrome();
    return;
  }
  seekRow.classList.add("has-track-labels");
  seekRow.style.setProperty(
    "--seek-label-headroom",
    `${seekLabelHeadroomRem(tracks, artist)}rem`,
  );
  syncPlayerChrome();
}

function renderSeekMarks(tracks, duration, artist) {
  const marksEl = document.getElementById("player-seek-marks");
  const seekbar = document.getElementById("player-seekbar");
  const rail = seekbar?.closest(".player-seek-rail");
  const seekRow = seekbar?.closest(".player-seek");
  if (!marksEl || !seekbar) return;
  const list = Array.isArray(tracks) ? tracks : [];
  const total = Math.max(0, Number(duration) || 0);
  const layoutKey = seekMarksLayoutKey(list, total, artist);
  if (list.length < 2 || total <= 0) {
    if (playerSeekMarksKey !== "") {
      marksEl.replaceChildren();
      playerSeekMarksKey = "";
    }
    playerSeekTracks = [];
    playerSeekArtist = "";
    clearSeekTrackHighlight();
    seekbar.removeAttribute("title");
    rail?.classList.remove("has-track-labels");
    setSeekLabelHeadroom(seekRow, [], "");
    return;
  }
  playerSeekTracks = list;
  playerSeekArtist = String(artist || "");
  seekbar.removeAttribute("title");
  // Poll refreshes call this every 500ms; keep DOM stable so hover/is-hot survive.
  if (layoutKey === playerSeekMarksKey && marksEl.childElementCount > 0) {
    if (playerSeekHotIndex >= 0) {
      setSeekTrackHighlight(playerSeekHotIndex);
    }
    return;
  }
  playerSeekMarksKey = layoutKey;
  marksEl.replaceChildren();
  rail?.classList.add("has-track-labels");
  setSeekLabelHeadroom(seekRow, list, playerSeekArtist);
  let cumulative = 0;
  for (let i = 0; i < list.length; i += 1) {
    const trackDuration = Math.max(0, Number(list[i].duration_seconds) || 0);
    const startPct = (cumulative / total) * 100;
    const widthPct = (trackDuration / total) * 100;
    const midPct = startPct + widthPct / 2;
    const title =
      displayTrackTitle(list[i].title, playerSeekArtist) || `Track ${i + 1}`;

    const fill = document.createElement("span");
    fill.className = "player-seek-section-fill";
    fill.dataset.trackIndex = String(i);
    fill.style.left = `${startPct}%`;
    fill.style.width = `${Math.max(0, widthPct)}%`;
    marksEl.appendChild(fill);

    const section = document.createElement("button");
    section.type = "button";
    section.className = "player-seek-section";
    section.dataset.trackIndex = String(i);
    section.setAttribute("aria-label", `Seek to ${title}`);
    section.style.left = `${startPct}%`;
    section.style.width = `${Math.max(0, widthPct)}%`;
    const durationEl = document.createElement("span");
    durationEl.className = "player-seek-duration";
    durationEl.textContent = formatClock(trackDuration);
    section.appendChild(durationEl);
    marksEl.appendChild(section);

    const label = document.createElement("span");
    label.className = "player-seek-label";
    label.dataset.trackIndex = String(i);
    label.textContent = title;
    label.style.left = `${Math.max(0, Math.min(100, midPct))}%`;
    marksEl.appendChild(label);

    cumulative += trackDuration;
    if (i < list.length - 1 && cumulative > 0 && cumulative < total) {
      const mark = document.createElement("span");
      mark.className = "player-seek-mark";
      mark.style.left = `${(cumulative / total) * 100}%`;
      marksEl.appendChild(mark);
    }
  }
  if (playerSeekHotIndex >= 0) {
    setSeekTrackHighlight(playerSeekHotIndex);
  }
}

function seekSecondsAtClientX(seekbar, clientX) {
  const rect = seekbar.getBoundingClientRect();
  if (rect.width <= 0) return 0;
  const min = Number(seekbar.min) || 0;
  const max = Number(seekbar.max) || 0;
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  return min + ratio * (max - min);
}

function highlightSeekTrackAtClientX(seekbar, clientX) {
  if (playerSeekTracks.length < 2) {
    clearSeekTrackHighlight();
    return;
  }
  const index = trackIndexAtTimelineSeconds(
    playerSeekTracks,
    seekSecondsAtClientX(seekbar, clientX),
  );
  if (index < 0) {
    clearSeekTrackHighlight();
    return;
  }
  setSeekTrackHighlight(index);
}

function updateSeekBar(data) {
  const seekbar = document.getElementById("player-seekbar");
  const currentEl = document.getElementById("player-time-current");
  const totalEl = document.getElementById("player-time-total");
  if (!seekbar || !currentEl || !totalEl) return;
  const duration = Math.max(0, Math.round(data.duration_seconds || 0));
  const pos = Math.max(0, Math.min(duration, Math.round(data.position_seconds || 0)));
  seekbar.max = String(duration);
  if (!playerSeekDragging) {
    seekbar.value = String(pos);
  }
  syncSeekProgress(seekbar);
  const displayPos = playerSeekDragging ? Number(seekbar.value) : pos;
  currentEl.textContent = formatClock(displayPos);
  totalEl.textContent = formatClock(duration);
  const hasMix = Boolean(data.current_mix_id);
  seekbar.disabled = !hasMix;
  renderSeekMarks(
    hasMix && data.kind === "album" ? data.tracks || [] : [],
    duration,
    hasMix ? data.artist || "" : "",
  );
}

function cacheGroupKey(group) {
  return group.id == null ? "other" : String(group.id);
}

function buildCacheOverviewEl(overview) {
  const wrap = document.createElement("span");
  wrap.className = "cache-intent-overview";
  const statuses = [
    { key: "cached", className: "cache-stat-cached", showSize: true },
    { key: "loading", className: "cache-stat-loading", showSize: false },
    { key: "pending", className: "cache-stat-pending", showSize: false },
  ];
  for (const status of statuses) {
    const bucket = overview?.[status.key] || {
      count: 0,
      duration_seconds: 0,
      size_bytes: 0,
    };
    const count = Number(bucket.count) || 0;
    const el = document.createElement("span");
    el.className = `cache-stat ${status.className}`;
    if (count <= 0) el.classList.add("is-empty");

    const countEl = document.createElement("span");
    countEl.className = "cache-stat-count";
    countEl.textContent = String(count);
    el.appendChild(countEl);

    const pipe1 = document.createElement("span");
    pipe1.className = "cache-stat-pipe";
    pipe1.textContent = "|";
    el.appendChild(pipe1);

    const durationEl = document.createElement("span");
    durationEl.className = "cache-stat-duration";
    durationEl.textContent = formatDuration(bucket.duration_seconds);
    el.appendChild(durationEl);

    if (status.showSize) {
      const pipe2 = document.createElement("span");
      pipe2.className = "cache-stat-pipe";
      pipe2.textContent = "|";
      el.appendChild(pipe2);

      const sizeEl = document.createElement("span");
      sizeEl.className = "cache-stat-size";
      const parts = formatBytesParts(bucket.size_bytes);
      const valueEl = document.createElement("span");
      valueEl.className = "cache-stat-size-value";
      valueEl.textContent = parts.value;
      sizeEl.appendChild(valueEl);
      const unitEl = document.createElement("span");
      unitEl.className = "cache-stat-size-unit";
      unitEl.textContent = parts.unit;
      sizeEl.appendChild(unitEl);
      el.appendChild(sizeEl);
    }

    wrap.appendChild(el);
  }
  return wrap;
}

function formatBytesParts(bytes) {
  const n = Math.max(0, Number(bytes) || 0);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) {
    return { value: String(Math.round(value)), unit: units[unit] };
  }
  return { value: value.toFixed(1), unit: units[unit] };
}

function formatBytes(bytes) {
  const parts = formatBytesParts(bytes);
  return `${parts.value}${parts.unit}`;
}

function formatMb(bytes) {
  const n = Number(bytes) || 0;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatCacheSummary(summary) {
  const count = Number(summary?.count) || 0;
  if (count <= 0) {
    return "0";
  }
  const duration = formatDuration(summary?.duration_seconds || 0);
  const size = formatBytes(summary?.size_bytes || 0);
  return `${count}, ${duration}, ${size}`;
}

function renderDownloadProgress(file) {
  const wrap = document.createElement("div");
  wrap.className = "cache-progress";
  const downloaded = Number(file.downloaded_bytes) || 0;
  const total =
    file.total_bytes == null || file.total_bytes === ""
      ? null
      : Number(file.total_bytes);
  const known = total != null && Number.isFinite(total) && total > 0;

  const label = document.createElement("span");
  label.className = "cache-progress-label";
  label.textContent = known
    ? `${formatMb(downloaded)} / ${formatMb(total)}`
    : downloaded > 0
      ? formatMb(downloaded)
      : "downloading…";
  wrap.appendChild(label);

  const track = document.createElement("div");
  track.className = "cache-progress-track";
  track.setAttribute("role", "progressbar");
  track.setAttribute("aria-valuemin", "0");
  if (known) {
    const pct = Math.max(0, Math.min(100, (downloaded / total) * 100));
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(Math.round(pct)));
    const fill = document.createElement("div");
    fill.className = "cache-progress-fill";
    fill.style.width = `${pct}%`;
    track.appendChild(fill);
  } else {
    track.classList.add("indeterminate");
    track.setAttribute("aria-valuetext", "download in progress");
    const fill = document.createElement("div");
    fill.className = "cache-progress-fill";
    track.appendChild(fill);
  }
  wrap.appendChild(track);
  return wrap;
}

function setCacheGroupExpanded(groupKey, expanded) {
  const header = document.querySelector(
    `#cache-body .cache-intent-header[data-group-id="${CSS.escape(groupKey)}"]`,
  );
  if (!header) return;
  header.dataset.expanded = expanded ? "true" : "false";
  header.setAttribute("aria-expanded", expanded ? "true" : "false");
  const toggle = header.querySelector(".cache-intent-toggle");
  if (toggle) toggle.textContent = expanded ? "▼" : "▶";
  document
    .querySelectorAll(
      `#cache-body .cache-mix-row[data-group-id="${CSS.escape(groupKey)}"]`,
    )
    .forEach((row) => {
      row.hidden = !expanded;
    });
  if (expanded) expandedCacheIntents.add(groupKey);
  else expandedCacheIntents.delete(groupKey);
}

function artistGroupStats(mixes) {
  let durationSeconds = 0;
  let rejected = 0;
  let played = 0;
  let rated = 0;
  let tagged = 0;
  let starsSum = 0;
  for (const mix of mixes) {
    durationSeconds += Number(mix.duration_seconds) || 0;
    if (mix.rejected) rejected += 1;
    if (mix.played) played += 1;
    if (Array.isArray(mix.tags) && mix.tags.length > 0) tagged += 1;
    if (mix.stars != null) {
      rated += 1;
      starsSum += Number(mix.stars) || 0;
    }
  }
  const count = mixes.length;
  if (count <= 0) {
    return {
      count: 0,
      durationSeconds: 0,
      avgStars: null,
      ratedPct: 0,
      taggedPct: 0,
      rejectedPct: 0,
      playedPct: 0,
    };
  }
  const pct = (n) => Math.round((100 * n) / count);
  return {
    count,
    durationSeconds,
    avgStars: rated > 0 ? starsSum / rated : null,
    ratedPct: pct(rated),
    taggedPct: pct(tagged),
    rejectedPct: pct(rejected),
    playedPct: pct(played),
  };
}

function appendArtistFoldName(artistLabel, artistName, mixes) {
  const stats = artistGroupStats(mixes);
  artistLabel.appendChild(document.createTextNode(`${artistName} (`));
  if (stats.count <= 0) {
    artistLabel.appendChild(document.createTextNode("0)"));
    return;
  }
  artistLabel.appendChild(
    document.createTextNode(
      `${stats.count}, ${formatDuration(stats.durationSeconds)})`,
    ),
  );
}

/** Pct first, then symbol (+ optional suffix); fixed-width digits keep columns aligned. */
function buildArtistStatEl(className, symbol, pct, suffix = null) {
  const el = document.createElement("span");
  el.className = `artist-stat ${className}`;
  const pctEl = document.createElement("span");
  pctEl.className = "artist-stat-pct";
  pctEl.textContent = String(pct);
  el.appendChild(pctEl);
  const pctSign = document.createElement("span");
  pctSign.className = "artist-stat-pct-sign";
  pctSign.textContent = "%";
  el.appendChild(pctSign);
  el.appendChild(document.createTextNode(symbol));
  if (suffix != null) {
    const suffixEl = document.createElement("span");
    suffixEl.className = "artist-stat-avg";
    suffixEl.textContent = suffix;
    el.appendChild(suffixEl);
  }
  return el;
}

function buildArtistStatsEl(mixes) {
  const stats = artistGroupStats(mixes);
  if (stats.count <= 0) return null;
  const wrap = document.createElement("span");
  wrap.className = "artist-stats";
  const avgSuffix =
    stats.avgStars != null ? stats.avgStars.toFixed(1) : "0.0";
  const ratingEl = buildArtistStatEl(
    "artist-stat-rating",
    "★",
    stats.ratedPct,
    avgSuffix,
  );
  if (stats.avgStars == null) {
    ratingEl.querySelector(".artist-stat-avg")?.classList.add("is-empty");
  }
  wrap.appendChild(ratingEl);
  wrap.appendChild(
    buildArtistStatEl("artist-stat-tagged", "#", stats.taggedPct),
  );
  wrap.appendChild(
    buildArtistStatEl("artist-stat-reject", "✕", stats.rejectedPct),
  );
  wrap.appendChild(
    buildArtistStatEl("artist-stat-played", "▶", stats.playedPct),
  );
  return wrap;
}

function groupMixesByArtist(mixes) {
  const groups = new Map();
  for (const mix of mixes) {
    const artistId = mix.artist_id || "unknown";
    const artistName = mix.artist || "Unknown";
    let group = groups.get(artistId);
    if (!group) {
      group = {
        artistId,
        artistName,
        artistUrl: mix.artist_url || null,
        platform: mix.platform || null,
        mixes: [],
      };
      groups.set(artistId, group);
    } else {
      if (!group.artistUrl && mix.artist_url) {
        group.artistUrl = mix.artist_url;
      }
      if (!group.platform && mix.platform) {
        group.platform = mix.platform;
      }
    }
    group.mixes.push(mix);
  }
  const sorted = [...groups.values()].sort((a, b) =>
    a.artistName.localeCompare(b.artistName, undefined, { sensitivity: "base" }),
  );
  for (const group of sorted) {
    group.mixes.sort((a, b) =>
      (a.title || "").localeCompare(b.title || "", undefined, { sensitivity: "base" }),
    );
  }
  return sorted;
}

function setArtistExpanded(artistId, expanded) {
  const header = document.querySelector(
    `#catalog-body tr.artist-row[data-artist-id="${CSS.escape(artistId)}"]`,
  );
  if (!header) return;
  header.dataset.expanded = expanded ? "true" : "false";
  header.setAttribute("aria-expanded", expanded ? "true" : "false");
  const toggle = header.querySelector(".artist-toggle");
  if (toggle) toggle.textContent = expanded ? "▼" : "▶";
  document
    .querySelectorAll(
      `#catalog-body tr.mix-row[data-artist-id="${CSS.escape(artistId)}"]`,
    )
    .forEach((row) => {
      row.hidden = !expanded;
    });
  if (expanded) expandedCatalogArtists.add(artistId);
  else expandedCatalogArtists.delete(artistId);
}

function clearCatalogRejectTimer(mixId) {
  const handle = catalogRejectTimers.get(mixId);
  if (handle != null) {
    clearTimeout(handle);
    catalogRejectTimers.delete(mixId);
  }
}

function scheduleCatalogRejectRefresh(mixId, untilIso) {
  clearCatalogRejectTimer(mixId);
  if (!untilIso) return;
  const untilMs = Date.parse(untilIso);
  if (Number.isNaN(untilMs)) return;
  const delay = Math.max(0, untilMs - Date.now()) + 50;
  const handle = setTimeout(async () => {
    catalogRejectTimers.delete(mixId);
    await refreshMixes({ force: true });
    await refreshPlayer();
  }, delay);
  catalogRejectTimers.set(mixId, handle);
}

function mixMatchesCatalogFilters(mix) {
  if (!showRejectedCatalog && mix.rejected) return false;
  if (
    catalogFilterPlatforms.length &&
    !catalogFilterPlatforms.includes(mix.platform)
  ) {
    return false;
  }
  if (catalogFilterMinStars != null) {
    if (mix.stars == null || Number(mix.stars) < catalogFilterMinStars) {
      return false;
    }
  }
  if (
    catalogFilterTags.length &&
    !catalogFilterTags.every((t) => (mix.tags || []).includes(t))
  ) {
    return false;
  }
  return true;
}

/**
 * Catalog toolbar: click N★ to keep rating ≥ N; click again to clear.
 * @param {HTMLElement} root
 * @param {{ floor?: number|null, onChange: (floor: number|null) => Promise<void>|void }} options
 */
function mountCatalogStarFloor(root, options) {
  let floor =
    options.floor != null && options.floor !== ""
      ? Number(options.floor)
      : null;
  root.classList.add("star-rating");
  root.setAttribute("role", "group");

  function paint() {
    root.dataset.stars = floor != null ? String(floor) : "";
    root.setAttribute(
      "aria-label",
      floor != null ? `${floor}★ and up` : "Any rating",
    );
    root.replaceChildren();
    for (let s = 1; s <= 5; s += 1) {
      const filled = floor != null && s <= floor;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `star-rating-star ${filled ? "is-filled" : "is-empty"}`;
      btn.textContent = filled ? "★" : "☆";
      btn.setAttribute("aria-pressed", floor === s ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        floor === s ? `Clear ${s}★ minimum` : `${s}★ and up`,
      );
      btn.title = floor === s ? "Clear rating filter" : `${s}★ and up`;
      btn.addEventListener("click", async (event) => {
        event.stopPropagation();
        floor = floor === s ? null : s;
        paint();
        await options.onChange(floor);
      });
      root.appendChild(btn);
    }
  }

  paint();
  return {
    setFloor(value) {
      floor = value != null && value !== "" ? Number(value) : null;
      paint();
    },
    getFloor() {
      return floor;
    },
  };
}

function syncRejectedToggle(btn, on) {
  if (!btn) return;
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.textContent = on ? "♻" : "♲";
}

function mountCatalogFilters() {
  const sourcesRoot = document.getElementById("catalog-source-filters");
  if (sourcesRoot) {
    sourcesRoot.replaceChildren();
    const platformsRoot = document.createElement("div");
    platformsRoot.className = "source-toggles";
    platformsRoot.setAttribute("role", "group");
    platformsRoot.setAttribute("aria-label", "Catalog sources");
    for (const platform of DEFAULT_INTENT_PLATFORMS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "source-toggle";
      btn.dataset.platform = platform;
      btn.setAttribute("aria-pressed", "false");
      btn.title = PLATFORM_LABELS[platform] || platform;
      btn.setAttribute("aria-label", PLATFORM_LABELS[platform] || platform);
      btn.innerHTML = PLATFORM_SVG[platform] || "";
      platformsRoot.appendChild(btn);
    }
    sourcesRoot.appendChild(platformsRoot);
    // Empty = any source (same as empty tag filter).
    catalogFilterPlatforms = [];

    function readPlatforms() {
      return Array.from(platformsRoot.querySelectorAll(".source-toggle"))
        .filter((btn) => btn.getAttribute("aria-pressed") === "true")
        .map((btn) => btn.dataset.platform)
        .filter(Boolean);
    }

    platformsRoot.addEventListener("click", async (event) => {
      const btn = event.target.closest(".source-toggle");
      if (!btn || !platformsRoot.contains(btn)) return;
      const pressed = btn.getAttribute("aria-pressed") === "true";
      btn.setAttribute("aria-pressed", pressed ? "false" : "true");
      catalogFilterPlatforms = readPlatforms();
      await refreshMixes({ force: true });
    });
  }

  const starsRoot = document.getElementById("catalog-star-filters");
  if (starsRoot) {
    starsRoot.replaceChildren();
    catalogFilterMinStars = null;
    catalogStarFilter = mountCatalogStarFloor(starsRoot, {
      floor: null,
      async onChange(floor) {
        catalogFilterMinStars = floor;
        await refreshMixes({ force: true });
      },
    });
  }

  const tagsRoot = document.getElementById("catalog-tag-filters");
  if (tagsRoot) {
    tagsRoot.replaceChildren();
    catalogFilterTags = [];
    catalogTagFilterEditor = mountTagEditor(tagsRoot, {
      tags: [],
      confirmRemove: false,
      getCatalogTags: () => catalogTagsCache,
      async onAdd(tag) {
        catalogFilterTags = [...catalogFilterTags, tag];
        await refreshMixes({ force: true });
      },
      async onRemove(tag) {
        catalogFilterTags = catalogFilterTags.filter((t) => t !== tag);
        await refreshMixes({ force: true });
      },
    });
    tagsRoot.setAttribute("aria-label", "Catalog filter tags");
  }
}

function resetCatalogFilters() {
  catalogFilterPlatforms = [];
  catalogFilterMinStars = null;
  catalogFilterTags = [];
  showRejectedCatalog = false;
  syncRejectedToggle(document.getElementById("catalog-show-rejected"), false);
  const sourcesRoot = document.getElementById("catalog-source-filters");
  if (sourcesRoot) {
    for (const btn of sourcesRoot.querySelectorAll(".source-toggle")) {
      btn.setAttribute("aria-pressed", "false");
    }
  }
  catalogStarFilter?.setFloor(null);
  catalogTagFilterEditor?.setTags([]);
}

async function refreshMixes({ force = false } = {}) {
  const body = document.getElementById("catalog-body");
  const res = await fetch("/api/mixes");
  const data = await res.json();
  // Keep in-progress catalog tag edits; still refresh Play history below.
  const skipCatalog = !force && focusInside(body);
  if (!skipCatalog) {
    body.innerHTML = "";
    if (!data.mixes.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 4;
      td.className = "muted";
      td.textContent = "No releases yet";
      tr.appendChild(td);
      body.appendChild(tr);
      await refreshTagSuggestions();
      await refreshPlayHistory(data.mixes);
      return;
    }

    for (const group of groupMixesByArtist(data.mixes)) {
      const visibleMixes = group.mixes.filter(mixMatchesCatalogFilters);
      if (!visibleMixes.length) continue;
      const expanded = expandedCatalogArtists.has(group.artistId);
      const header = document.createElement("tr");
      header.className = "artist-row";
      header.dataset.artistId = group.artistId;
      header.dataset.expanded = expanded ? "true" : "false";
      header.setAttribute("aria-expanded", expanded ? "true" : "false");
      header.tabIndex = 0;
      header.setAttribute("role", "button");

      const artistCell = document.createElement("td");
      artistCell.colSpan = 4;
      const artistInner = document.createElement("div");
      artistInner.className = "artist-row-inner";
      const foldMain = document.createElement("div");
      foldMain.className = "artist-fold-main";
      const artistLabel = document.createElement("span");
      artistLabel.className = "artist-label";
      const toggle = document.createElement("span");
      toggle.className = "artist-toggle";
      toggle.setAttribute("aria-hidden", "true");
      toggle.textContent = expanded ? "▼" : "▶";
      artistLabel.appendChild(toggle);
      appendArtistFoldName(artistLabel, group.artistName, group.mixes);
      if (group.artistUrl) {
        const link = createSourcePageLink(group.platform, group.artistUrl, {
          page: "artist",
        });
        if (link) {
          artistLabel.appendChild(document.createTextNode(" "));
          link.addEventListener("click", (event) => {
            event.stopPropagation();
          });
          artistLabel.appendChild(link);
        }
      }
      foldMain.appendChild(artistLabel);
      const statsEl = buildArtistStatsEl(group.mixes);
      if (statsEl) foldMain.appendChild(statsEl);
      artistInner.appendChild(foldMain);
      const refreshBtn = document.createElement("button");
      refreshBtn.type = "button";
      refreshBtn.className = "artist-refresh";
      setSymbolButton(refreshBtn, BTN.refresh, "Refresh artist");
      refreshBtn.addEventListener("click", async (event) => {
        event.stopPropagation();
        const status = document.getElementById("artists-status");
        status.textContent = `Refreshing “${group.artistName}”…`;
        try {
          const data = await postRefreshArtists([group.artistId]);
          if (!data.ok) {
            status.textContent = data.detail || "Refresh artist failed";
            return;
          }
          status.textContent = `Refreshed “${group.artistName}” · ${data.added} new release(s)`;
          await refreshMixes();
        } catch (err) {
          status.textContent = "Refresh artist request failed";
          console.error(err);
        }
      });
      artistInner.appendChild(refreshBtn);
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "artist-delete";
      bindConfirmDelete(deleteBtn, {
        label: "Delete artist",
        stopPropagation: true,
        onConfirm: async () => {
          const status = document.getElementById("artists-status");
          status.textContent = "Deleting…";
          try {
            const res = await fetch(`/api/artists/${group.artistId}`, {
              method: "DELETE",
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              status.textContent = data.detail || "Delete artist failed";
              return;
            }
            expandedCatalogArtists.delete(group.artistId);
            status.textContent = `Deleted “${group.artistName}”`;
            await refreshMixes();
            await refreshIntents();
            await refreshFiles();
          } catch (err) {
            status.textContent = "Delete artist request failed";
            console.error(err);
          }
        },
      });
      artistInner.appendChild(deleteBtn);
      artistCell.appendChild(artistInner);
      header.appendChild(artistCell);

      const toggleGroup = () => {
        setArtistExpanded(
          group.artistId,
          header.dataset.expanded !== "true",
        );
      };
      header.addEventListener("click", toggleGroup);
      header.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggleGroup();
        }
      });
      body.appendChild(header);

      for (const mix of visibleMixes) {
        const tr = document.createElement("tr");
        tr.className = "mix-row";
        if (mix.rejected) tr.classList.add("mix-rejected");
        tr.dataset.artistId = group.artistId;
        tr.dataset.mixId = mix.id;
        tr.hidden = !expanded;

        const title = document.createElement("td");
        title.textContent = mix.title || "";
        tr.appendChild(title);

        const length = document.createElement("td");
        length.textContent = formatDuration(mix.duration_seconds || 0);
        tr.appendChild(length);

        const rating = document.createElement("td");
        const starsRoot = document.createElement("div");
        rating.appendChild(starsRoot);
        tr.appendChild(rating);

        const tagsCell = document.createElement("td");
        const tagRow = document.createElement("div");
        tagRow.className = "tag-cell";
        // Catalog stars stay display-only (interactive: false) until ui-actions 03.
        mountAnnotateKit({
          surface: "catalog",
          mix,
          starsRoot,
          actionsRoot: tagRow,
          rateInteractive: false,
          allowUnreject: true,
          refreshAfterTag: false,
          starsClass: "stars-display",
          tagEditorClass: "tag-editor catalog-tag-editor",
        });
        tagsCell.appendChild(tagRow);
        tr.appendChild(tagsCell);
        body.appendChild(tr);
      }
    }
    if (!body.children.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 4;
      td.className = "muted";
      td.textContent = "No releases match these filters";
      tr.appendChild(td);
      body.appendChild(tr);
    }
    await refreshTagSuggestions();
  }
  await refreshPlayHistory(data.mixes);
}

function formatLastHeard(ts) {
  if (!ts) return "";
  const match = String(ts).match(/^(\d{2})(\d{2}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
  if (match) return `${match[2]} ${match[3]}`;
  return String(ts);
}

async function refreshPlayHistory(mixes) {
  const body = document.getElementById("play-history-body");
  if (!body) return;
  // Tag/star editors live in this table; remounting clears focus and drafts.
  if (focusInside(body)) return;
  let rows = mixes;
  if (!Array.isArray(rows)) {
    const res = await fetch("/api/mixes");
    const data = await res.json();
    rows = data.mixes || [];
  }
  const heard = rows
    .filter((mix) => mix.last_heard_at)
    .filter((mix) => showRejectedHistory || !mix.rejected)
    .slice()
    .sort((a, b) => String(b.last_heard_at).localeCompare(String(a.last_heard_at)));
  body.replaceChildren();
  if (!heard.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.className = "muted";
    td.textContent = "No listens yet";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const mix of heard) {
    const tr = document.createElement("tr");
    tr.className = "play-history-row";
    if (mix.rejected) tr.classList.add("mix-rejected");
    tr.dataset.mixId = mix.id;

    const heardCell = document.createElement("td");
    heardCell.textContent = formatLastHeard(mix.last_heard_at);
    tr.appendChild(heardCell);
    const artistCell = document.createElement("td");
    artistCell.textContent = mix.artist || "Unknown";
    tr.appendChild(artistCell);
    const titleCell = document.createElement("td");
    titleCell.textContent = mix.title || "";
    tr.appendChild(titleCell);
    const lengthCell = document.createElement("td");
    lengthCell.textContent = formatDuration(mix.duration_seconds || 0);
    tr.appendChild(lengthCell);

    const ratingCell = document.createElement("td");
    const starsRoot = document.createElement("div");
    ratingCell.appendChild(starsRoot);
    tr.appendChild(ratingCell);

    const tagsCell = document.createElement("td");
    const tagRow = document.createElement("div");
    tagRow.className = "tag-cell history-tag-cell";
    mountAnnotateKit({
      surface: "history",
      mix,
      starsRoot,
      actionsRoot: tagRow,
      rateInteractive: true,
      allowUnreject: true,
      refreshAfterTag: true,
      starsClass: "history-stars",
      tagEditorClass: "tag-editor history-tag-editor",
    });
    tagsCell.appendChild(tagRow);
    tr.appendChild(tagsCell);

    const actionsCell = document.createElement("td");
    const resumeBtn = document.createElement("button");
    resumeBtn.type = "button";
    resumeBtn.className = "history-resume";
    setSymbolButton(resumeBtn, BTN.resume, "Resume at Catalog Playhead");
    resumeBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const intentId = document.getElementById("player-intent")?.value;
      const status = document.getElementById("player-status");
      if (!intentId) {
        if (status) status.textContent = "Choose an intent";
        return;
      }
      if (status) status.textContent = "Resuming…";
      try {
        const res = await fetch("/api/player/play", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ intent_id: intentId, mix_id: mix.id }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (status) status.textContent = data.detail || "Resume failed";
          return;
        }
        if (status) status.textContent = "";
        lastPlayheadCommitAt = Date.now();
        playheadPlayedNotifiedForMix = null;
        await refreshPlayer();
        await refreshFiles();
      } catch (err) {
        if (status) status.textContent = "Resume request failed";
        console.error(err);
      }
    });
    actionsCell.appendChild(resumeBtn);
    tr.appendChild(actionsCell);

    body.appendChild(tr);
  }
}

async function refreshTagSuggestions() {
  const res = await fetch("/api/tags");
  const data = await res.json().catch(() => ({ tags: [] }));
  catalogTagsCache = data.tags || [];
}

async function refreshPlayerIntents() {
  const res = await fetch("/api/intents");
  const data = await res.json();
  const select = document.getElementById("player-intent");
  if (!select) return;
  const previous = select.value;
  select.innerHTML = "";
  if (!data.intents.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No intents";
    select.appendChild(option);
    return;
  }
  for (const intent of data.intents) {
    const option = document.createElement("option");
    option.value = intent.id;
    option.textContent = intent.name;
    select.appendChild(option);
  }
  if (previous && [...select.options].some((o) => o.value === previous)) {
    select.value = previous;
  }
}

function clearRejectUndoTimer() {
  if (rejectUndoTimer != null) {
    clearTimeout(rejectUndoTimer);
    rejectUndoTimer = null;
  }
}

function updateRejectControls(data) {
  if (playerAnnotateKit?.updateRejectControls) {
    playerAnnotateKit.updateRejectControls(data);
    return;
  }
  // Fallback before kit mounts (should be rare).
  const undoBtn = document.getElementById("player-undo-reject");
  const rejectBtn = document.getElementById("player-reject");
  const status = document.getElementById("player-reject-status");
  if (!undoBtn || !rejectBtn || !status) return;
  undoBtn.hidden = true;
  rejectBtn.hidden = false;
  status.hidden = true;
  status.textContent = "";
}

async function maybeCommitPlayhead(playing) {
  if (!playing || playheadCommitInFlight) return;
  const now = Date.now();
  if (now - lastPlayheadCommitAt < PLAYHEAD_COMMIT_MS) return;
  playheadCommitInFlight = true;
  lastPlayheadCommitAt = now;
  try {
    const res = await fetch("/api/player/playhead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_seconds: lastKnownPositionSeconds }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return;
    if (data.played) {
      const mixId = data.mix_id || null;
      if (mixId !== playheadPlayedNotifiedForMix) {
        playheadPlayedNotifiedForMix = mixId;
        const status = document.getElementById("player-status");
        if (status) {
          status.textContent = `Playhead ${Math.round(lastKnownPositionSeconds)}s · marked played`;
        }
        await refreshMixes();
        await refreshFiles();
        await refreshIntents();
      }
    }
  } catch (err) {
    console.error(err);
  } finally {
    playheadCommitInFlight = false;
  }
}

function updatePlayPauseButton(playing) {
  const btn = document.getElementById("player-play");
  if (!btn) return;
  const label = playing ? "Pause" : "Play";
  setSymbolButton(btn, playing ? BTN.pause : BTN.play, label);
  btn.dataset.playing = playing ? "true" : "false";
}

function setIntentPlayButton(btn, playingThis) {
  const label = playingThis ? "Pause" : "Play";
  setSymbolButton(btn, playingThis ? BTN.pause : BTN.play, label);
  btn.dataset.playing = playingThis ? "true" : "false";
}

function syncPlayerIntentSelect(intentId) {
  const select = document.getElementById("player-intent");
  if (!select || !intentId) return;
  if ([...select.options].some((o) => o.value === intentId)) {
    select.value = intentId;
  }
}

function updateIntentPlayButtons(playing, intentId) {
  lastPlayerPlaying = Boolean(playing);
  lastPlayerIntentId = intentId || null;
  if (lastPlayerIntentId) {
    syncPlayerIntentSelect(lastPlayerIntentId);
  }
  for (const btn of document.querySelectorAll("#intent-list .intent-play")) {
    const playingThis =
      lastPlayerPlaying &&
      lastPlayerIntentId != null &&
      btn.dataset.intentId === lastPlayerIntentId;
    setIntentPlayButton(btn, playingThis);
  }
}

function isIntentCurrentlyPlaying(intentId) {
  return (
    lastPlayerPlaying &&
    lastPlayerIntentId != null &&
    intentId != null &&
    intentId === lastPlayerIntentId
  );
}

async function pausePlayback() {
  const status = document.getElementById("player-status");
  if (status) status.textContent = "Pausing…";
  // Keep the player intent on whatever is actually playing so resume stays correct.
  if (lastPlayerIntentId) {
    syncPlayerIntentSelect(lastPlayerIntentId);
  }
  const res = await fetch("/api/player/pause", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      position_seconds: Math.max(0, lastKnownPositionSeconds),
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (status) status.textContent = data.detail || "Pause failed";
    return false;
  }
  if (status) status.textContent = data.played ? "Paused · marked played" : "Paused";
  lastPlayheadCommitAt = Date.now();
  await refreshPlayer();
  if (data.played) {
    await refreshMixes();
    await refreshFiles();
    await refreshIntents();
  }
  return true;
}

async function playIntent(intentId) {
  const status = document.getElementById("player-status");
  if (!intentId) {
    if (status) status.textContent = "Choose an intent";
    return false;
  }
  syncPlayerIntentSelect(intentId);
  if (status) status.textContent = "Starting playback…";
  const res = await fetch("/api/player/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent_id: intentId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (status) status.textContent = data.detail || "Play failed";
    return false;
  }
  if (status) status.textContent = "";
  lastPlayheadCommitAt = Date.now();
  playheadPlayedNotifiedForMix = null;
  await refreshPlayer();
  await refreshFiles();
  return true;
}

function renderPlayerCover(data) {
  const cover = document.getElementById("player-cover");
  if (!cover) return;
  const mixId = data.current_mix_id || null;
  const show = Boolean(mixId && data.has_cover);
  if (!show) {
    if (playerCoverMixId != null) {
      cover.hidden = true;
      cover.removeAttribute("src");
      cover.alt = "";
      playerCoverMixId = null;
      syncPlayerChrome();
    }
    return;
  }
  if (playerCoverMixId === mixId) {
    cover.hidden = false;
    requestAnimationFrame(() => syncPlayerNowStack());
    return;
  }
  playerCoverMixId = mixId;
  cover.alt = data.title ? `Cover art for ${data.title}` : "Release cover art";
  cover.src = `/api/mixes/${mixId}/cover`;
  cover.hidden = false;
  // Cover size changes now-row height; refresh stack + raised clip after paint.
  requestAnimationFrame(() => syncPlayerChrome());
}

function renderPlayerNow(data) {
  const now = document.getElementById("player-now");
  if (!now) return;
  renderPlayerCover(data);
  if (!data.current_mix_id) {
    if (playerNowKey !== "idle") {
      now.replaceChildren();
      now.textContent = "Nothing playing";
      playerNowKey = "idle";
    }
    return;
  }
  const title = data.title || "Untitled";
  const artist = data.artist || "Unknown";
  const sizePart =
    data.size_bytes != null && Number(data.size_bytes) > 0
      ? ` (${formatBytes(data.size_bytes)})`
      : "";
  const label = `${artist} - ${title}${sizePart}`;
  const platform = data.platform || "";
  const releaseUrl = data.url || "";
  const artistUrl = data.artist_url || "";
  const href = releaseUrl || artistUrl;
  const page = releaseUrl ? "release" : "artist";
  const key = `${data.current_mix_id}|${label}|${platform}|${href}|${page}`;
  if (key === playerNowKey) return;
  playerNowKey = key;
  now.replaceChildren();
  now.appendChild(document.createTextNode(label));
  const link = createSourcePageLink(platform, href, { page });
  if (link) {
    now.appendChild(document.createTextNode(" "));
    now.appendChild(link);
  }
  requestAnimationFrame(() => syncPlayerNowStack());
}

async function refreshPlayer() {
  const res = await fetch("/api/player");
  const data = await res.json();
  const now = document.getElementById("player-now");
  if (!now) return;
  currentMixId = data.current_mix_id || null;
  if (!data.current_mix_id) {
    renderPlayerNow(data);
    lastKnownPositionSeconds = 0;
    lastPlayheadCommitAt = 0;
    playheadPlayedNotifiedForMix = null;
    if (playerTagEditor && !playerTagEditor.isBusy()) {
      playerTagEditor.setTags([]);
    }
    updateSeekBar({});
    setPlayerPolling(false);
    updateRejectControls({});
    updatePlayPauseButton(false);
    updateIntentPlayButtons(false, null);
    return;
  }
  const pos = Math.round(data.position_seconds || 0);
  if (!playerSeekDragging) {
    lastKnownPositionSeconds = pos;
  }
  renderPlayerNow(data);
  if (playerStarRating && !playerStarRating.isBusy()) {
    playerStarRating.setStars(data.stars);
  }
  if (playerTagEditor && !playerTagEditor.isBusy()) {
    playerTagEditor.setTags(data.tags || []);
  }
  updateSeekBar(data);
  setPlayerPolling(Boolean(data.playing));
  updateRejectControls(data);
  updatePlayPauseButton(Boolean(data.playing));
  updateIntentPlayButtons(Boolean(data.playing), data.intent_id);
  if (data.playing) {
    await maybeCommitPlayhead(true);
  } else {
    lastPlayheadCommitAt = 0;
  }
}

async function refreshFiles({ force = false } = {}) {
  const body = document.getElementById("cache-body");
  if (!force && focusInside(body)) return;
  const res = await fetch("/api/files");
  const data = await res.json();
  const countEl = document.getElementById("cache-count");
  if (countEl) {
    countEl.textContent = formatCacheSummary(
      data.cache_summary || {
        count: data.files.length,
        duration_seconds: 0,
        size_bytes: 0,
      },
    );
  }
  body.innerHTML = "";
  const groups = Array.isArray(data.groups) ? data.groups : [];
  if (!groups.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "muted";
    td.textContent =
      "No assigned audio yet — create an intent with hours, or press Fill caches";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }

  for (const group of groups) {
    const groupKey = cacheGroupKey(group);
    const expanded = expandedCacheIntents.has(groupKey);

    const header = document.createElement("tr");
    header.className = "cache-intent-header";
    header.dataset.groupId = groupKey;
    header.dataset.expanded = expanded ? "true" : "false";
    header.setAttribute("aria-expanded", expanded ? "true" : "false");
    header.tabIndex = 0;
    header.setAttribute("role", "button");

    const intentCell = document.createElement("td");
    intentCell.colSpan = 6;
    const foldMain = document.createElement("div");
    foldMain.className = "cache-intent-fold-main";
    const intentLabel = document.createElement("span");
    intentLabel.className = "cache-intent-label";
    const toggle = document.createElement("span");
    toggle.className = "cache-intent-toggle";
    toggle.setAttribute("aria-hidden", "true");
    toggle.textContent = expanded ? "▼" : "▶";
    intentLabel.appendChild(toggle);
    const heading = document.createElement("span");
    heading.className = "cache-intent-name";
    heading.textContent = group.name || "Intent";
    intentLabel.appendChild(heading);
    foldMain.appendChild(intentLabel);
    foldMain.appendChild(buildCacheOverviewEl(group.overview));
    intentCell.appendChild(foldMain);
    header.appendChild(intentCell);

    const toggleGroup = () => {
      setCacheGroupExpanded(groupKey, header.dataset.expanded !== "true");
    };
    header.addEventListener("click", toggleGroup);
    header.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggleGroup();
      }
    });
    body.appendChild(header);

    for (const file of group.mixes || []) {
      const tr = document.createElement("tr");
      tr.className = "cache-mix-row";
      tr.dataset.groupId = groupKey;
      tr.hidden = !expanded;

      const artist = document.createElement("td");
      artist.textContent = file.artist || "Unknown";
      tr.appendChild(artist);

      const title = document.createElement("td");
      title.textContent = file.title || "";
      tr.appendChild(title);

      const length = document.createElement("td");
      length.textContent = formatDuration(file.duration_seconds || 0);
      tr.appendChild(length);

      const size = document.createElement("td");
      size.textContent =
        file.size_bytes != null && Number(file.size_bytes) > 0
          ? formatBytes(file.size_bytes)
          : "—";
      tr.appendChild(size);

      const statusCell = document.createElement("td");
      const isCurrent = currentMixId === file.id;
      if (file.status === "loading") {
        statusCell.appendChild(renderDownloadProgress(file));
      } else {
        statusCell.textContent =
          (file.status || "") + (isCurrent ? " · current" : "");
      }
      tr.appendChild(statusCell);

      const actionCell = document.createElement("td");
      if (file.status === "cached") {
        const currentBtn = document.createElement("button");
        currentBtn.type = "button";
        if (isCurrent) {
          setSymbolButton(currentBtn, BTN.clearCurrent, "Clear current");
        } else {
          setSymbolButton(currentBtn, BTN.setCurrent, "Set current");
        }
        currentBtn.addEventListener("click", async (event) => {
          event.stopPropagation();
          const status = document.getElementById("fill-status");
          try {
            const res = await fetch("/api/current-mix", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ mix_id: isCurrent ? null : file.id }),
            });
            const bodyJson = await res.json().catch(() => ({}));
            if (!res.ok) {
              status.textContent = bodyJson.detail || "Could not set current release";
              return;
            }
            currentMixId = bodyJson.current_mix_id || null;
            status.textContent = currentMixId
              ? `Current release set · metered cap uses this + one ahead`
              : "Current release cleared · metered cap uses assignment head";
            await refreshFiles();
          } catch (err) {
            status.textContent = "Current release request failed";
            console.error(err);
          }
        });
        actionCell.appendChild(currentBtn);
      }
      tr.appendChild(actionCell);
      body.appendChild(tr);
    }
  }
}

async function saveDeviceHours(intentId, deviceId, hoursValue, expiresValue) {
  const status = document.getElementById("intent-status");
  const hours = Number(hoursValue);
  if (!Number.isFinite(hours) || hours <= 0) {
    status.textContent = "Hours must be greater than 0";
    return false;
  }
  let expires_at = null;
  if (expiresValue !== "" && expiresValue != null) {
    const until = Number(expiresValue);
    if (!Number.isFinite(until) || until < 0) {
      status.textContent = "Expires in must be a non-negative number of hours";
      return false;
    }
    if (until > 0) {
      expires_at = new Date(Date.now() + until * 3600 * 1000).toISOString();
    }
  }
  status.textContent = "Saving device hours…";
  try {
    const res = await fetch(`/api/intents/${intentId}/hours`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_id: deviceId,
        budget_seconds: Math.round(hours * 3600),
        expires_at,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Save device hours failed";
      return false;
    }
    const filling = data.fill_in_progress ? " · filling caches…" : "";
    status.textContent = `Saved hours for ${deviceName(deviceId)}${filling}`;
    hoursEditorState.delete(intentId);
    await refreshIntents();
    await refreshFiles();
    return true;
  } catch (err) {
    status.textContent = "Save device hours request failed";
    console.error(err);
    return false;
  }
}

async function deleteDeviceHours(intent, deviceId) {
  const status = document.getElementById("intent-status");
  const name = deviceName(deviceId);
  const remaining = (intent.device_hours || [])
    .filter((dh) => dh.device_id !== deviceId)
    .map((dh) => ({
      device_id: dh.device_id,
      budget_seconds: dh.budget_seconds,
      expires_at: dh.expires_at,
    }));
  status.textContent = "Removing device hours…";
  try {
    const res = await fetch(`/api/intents/${intent.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_hours: remaining }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      status.textContent =
        typeof detail === "string"
          ? detail
          : detail?.[0]?.msg || "Remove device hours failed";
      return;
    }
    const filling = data.fill_in_progress ? " · filling caches…" : "";
    status.textContent = `Removed hours for ${name}${filling}`;
    hoursEditorState.delete(intent.id);
    await refreshIntents();
    await refreshFiles();
  } catch (err) {
    status.textContent = "Remove device hours request failed";
    console.error(err);
  }
}

function buildHoursEditor(intent, editor) {
  const wrap = document.createElement("div");
  wrap.className = "form-row hours-editor";

  const assigned = new Set((intent.device_hours || []).map((dh) => dh.device_id));
  let devices = knownDevices();
  let defaultHours = "8";
  let defaultExpires = "";
  let fixedDeviceId = null;

  if (editor.mode === "edit") {
    fixedDeviceId = editor.deviceId;
    const existing = (intent.device_hours || []).find(
      (dh) => dh.device_id === editor.deviceId,
    );
    if (existing) {
      defaultHours = String(existing.budget_seconds / 3600);
      defaultExpires = hoursUntilExpiry(existing.expires_at);
    }
    if (!devices.some((d) => d.id === fixedDeviceId)) {
      devices = [
        ...devices,
        { id: fixedDeviceId, name: deviceName(fixedDeviceId), defaultHours },
      ];
    }
  } else {
    devices = devices.filter((d) => !assigned.has(d.id));
    if (devices.length) {
      defaultHours = devices[0].defaultHours;
    }
  }

  if (editor.mode === "add" && !devices.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = localDeviceId
      ? "All known devices already have hours"
      : "Waiting for this device’s id…";
    wrap.appendChild(empty);
    const cancel = document.createElement("button");
    cancel.type = "button";
    setSymbolButton(cancel, BTN.cancel, "Cancel");
    cancel.addEventListener("click", () => {
      hoursEditorState.delete(intent.id);
      void refreshIntents();
    });
    wrap.appendChild(cancel);
    return wrap;
  }

  let deviceSelect = null;
  if (editor.mode === "add") {
    deviceSelect = document.createElement("select");
    deviceSelect.setAttribute("aria-label", "Device");
    deviceSelect.dataset.tip = "Device";
    for (const device of devices) {
      const option = document.createElement("option");
      option.value = device.id;
      option.textContent = device.name;
      deviceSelect.appendChild(option);
    }
    deviceSelect.addEventListener("change", () => {
      const chosen = devices.find((d) => d.id === deviceSelect.value);
      if (chosen) hoursInput.value = chosen.defaultHours;
    });
    wrap.appendChild(deviceSelect);
  } else {
    const fixed = document.createElement("input");
    fixed.type = "text";
    fixed.value = deviceName(fixedDeviceId);
    fixed.readOnly = true;
    fixed.setAttribute("aria-label", "Device");
    wrap.appendChild(fixed);
  }

  const hoursInput = document.createElement("input");
  hoursInput.type = "number";
  hoursInput.min = "0.5";
  hoursInput.step = "0.5";
  hoursInput.value = defaultHours;
  hoursInput.placeholder = "hours";
  hoursInput.setAttribute("aria-label", "Hours");
  hoursInput.dataset.tip = "Hours";
  wrap.appendChild(hoursInput);

  const expiresInput = document.createElement("input");
  expiresInput.type = "number";
  expiresInput.min = "0";
  expiresInput.step = "0.5";
  expiresInput.placeholder = "expires";
  expiresInput.value = defaultExpires;
  expiresInput.setAttribute("aria-label", "Expires in (hours)");
  expiresInput.dataset.tip = "Expires in (hours)";
  wrap.appendChild(expiresInput);

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  if (editor.mode === "edit") {
    setSymbolButton(saveBtn, BTN.save, "Save hours");
  } else {
    setSymbolButton(saveBtn, BTN.add, "Add hours");
  }
  saveBtn.addEventListener("click", async () => {
    const deviceId = editor.mode === "edit" ? fixedDeviceId : deviceSelect.value;
    await saveDeviceHours(intent.id, deviceId, hoursInput.value, expiresInput.value);
  });
  wrap.appendChild(saveBtn);

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  setSymbolButton(cancelBtn, BTN.cancel, "Cancel");
  cancelBtn.addEventListener("click", () => {
    hoursEditorState.delete(intent.id);
    void refreshIntents();
  });
  wrap.appendChild(cancelBtn);

  return wrap;
}

function assignmentOutcomeText(asg, durationByMixId) {
  if (!asg) return "";
  const mixIds = asg.mix_ids || [];
  let durationSeconds = 0;
  for (const mixId of mixIds) {
    durationSeconds += Number(durationByMixId.get(String(mixId))) || 0;
  }
  return ` (${mixIds.length}→${formatDuration(durationSeconds)})`;
}

function renderDeviceHoursPanel(intent, assignments = [], durationByMixId = new Map()) {
  const panel = document.createElement("div");
  panel.className = "device-hours";

  const assignmentByDevice = new Map();
  for (const asg of assignments) {
    assignmentByDevice.set(String(asg.device_id), asg);
  }

  const editor = hoursEditorState.get(intent.id);
  const hours = intent.device_hours || [];
  if (hours.length) {
    const list = document.createElement("ul");
    list.className = "device-hours-list";
    for (const dh of hours) {
      const editingThis =
        editor && editor.mode === "edit" && editor.deviceId === dh.device_id;
      if (editingThis) continue;
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.className = "hours-label";
      const until = hoursUntilExpiry(dh.expires_at);
      let expiryText = "";
      if (dh.expires_at) {
        expiryText =
          until === "" || until === "0"
            ? " · expired"
            : ` · expires in ${until}h`;
      }
      const asg = assignmentByDevice.get(String(dh.device_id));
      const outcomeText = assignmentOutcomeText(asg, durationByMixId);
      label.textContent = `${deviceName(dh.device_id)}: ${formatDuration(
        dh.budget_seconds,
      )}${outcomeText}${expiryText}`;
      item.appendChild(label);

      if (!editor) {
        const editBtn = document.createElement("button");
        editBtn.type = "button";
        setSymbolButton(editBtn, BTN.edit, "Edit hours");
        editBtn.addEventListener("click", () => {
          hoursEditorState.set(intent.id, {
            mode: "edit",
            deviceId: dh.device_id,
          });
          void refreshIntents();
        });
        item.appendChild(editBtn);

        const deleteBtn = document.createElement("button");
        deleteBtn.type = "button";
        bindConfirmDelete(deleteBtn, {
          label: "Remove hours",
          onConfirm: () => deleteDeviceHours(intent, dh.device_id),
        });
        item.appendChild(deleteBtn);
      }
      list.appendChild(item);
    }
    if (list.childElementCount) {
      panel.appendChild(list);
    }
  }

  if (editor) {
    panel.appendChild(buildHoursEditor(intent, editor));
  }

  return panel;
}

async function refreshIntents({ force = false } = {}) {
  const list = document.getElementById("intent-list");
  if (!force && focusInside(list)) return;
  await refreshIntentArtistOptions();
  const res = await fetch("/api/intents");
  const data = await res.json();
  if (editComposer) {
    editComposer.destroy();
    editComposer = null;
  }
  list.innerHTML = "";
  if (
    editingIntentId &&
    !(data.intents || []).some((intent) => intent.id === editingIntentId)
  ) {
    editingIntentId = null;
  }
  if (!data.intents.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No intents yet";
    list.appendChild(li);
    await refreshPlayerIntents();
    return;
  }

  for (const intent of data.intents) {
    const li = document.createElement("li");
    const isEditing = editingIntentId === intent.id;

    if (isEditing) {
      const composerMount = document.createElement("div");
      composerMount.className = "intent-composer intent-composer-edit";
      li.appendChild(composerMount);
      editComposer = mountIntentComposer(composerMount, {
        saveLabel: "Save changes",
        values: {
          name: intent.name,
          tags: intent.tags || [],
          artist_ids: intent.artist_ids || [],
          platforms: intent.platforms || DEFAULT_INTENT_PLATFORMS,
          distribution: intent.distribution,
        },
        async onSave(values) {
          const status = document.getElementById("intent-status");
          status.textContent = "Saving intent…";
          try {
            const res = await fetch(`/api/intents/${intent.id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(values),
            });
            const data = await res.json();
            if (!res.ok) {
              const detail = data.detail;
              status.textContent =
                typeof detail === "string"
                  ? detail
                  : detail?.[0]?.msg || "Update intent failed";
              return;
            }
            const filling = data.fill_in_progress ? " · filling caches…" : "";
            status.textContent = `Updated “${data.intent.name}”${filling}`;
            editingIntentId = null;
            if (editComposer) {
              editComposer.destroy();
              editComposer = null;
            }
            await refreshIntents({ force: true });
            await refreshFiles();
          } catch (err) {
            status.textContent = "Update intent request failed";
            console.error(err);
          }
        },
        onCancel() {
          document.getElementById("intent-status").textContent = "";
          cancelInlineIntentEdit();
        },
      });
      editComposer.focusName();
    } else {
      const headingRow = document.createElement("div");
      headingRow.className = "controls";
      const heading = document.createElement("h3");
      heading.textContent = intent.name;
      heading.style.flex = "1";
      headingRow.appendChild(heading);
      const playBtn = document.createElement("button");
      playBtn.type = "button";
      playBtn.className = "intent-play";
      playBtn.dataset.intentId = intent.id;
      const playingThis =
        lastPlayerPlaying && lastPlayerIntentId != null && lastPlayerIntentId === intent.id;
      setIntentPlayButton(playBtn, playingThis);
      playBtn.addEventListener("click", async () => {
        const status = document.getElementById("intent-status");
        try {
          // Pause only the intent that is actually playing right now.
          if (isIntentCurrentlyPlaying(intent.id)) {
            const ok = await pausePlayback();
            if (status) {
              status.textContent = ok
                ? `Paused “${intent.name}”`
                : document.getElementById("player-status")?.textContent || "Pause failed";
            }
            return;
          }
          const ok = await playIntent(intent.id);
          if (status) {
            status.textContent = ok
              ? `Playing “${intent.name}”`
              : document.getElementById("player-status")?.textContent || "Play failed";
          }
        } catch (err) {
          if (status) status.textContent = "Play request failed";
          console.error(err);
        }
      });
      headingRow.appendChild(playBtn);
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      setSymbolButton(editBtn, BTN.edit, "Edit intent");
      editBtn.addEventListener("click", () => beginEditIntent(intent));
      headingRow.appendChild(editBtn);
      const refreshBtn = document.createElement("button");
      refreshBtn.type = "button";
      setSymbolButton(refreshBtn, BTN.refresh, "Refresh");
      refreshBtn.addEventListener("click", async () => {
        const status = document.getElementById("intent-status");
        status.textContent = `Refreshing sequence “${intent.name}”…`;
        try {
          const res = await fetch(`/api/intents/${intent.id}/refresh-sequence`, {
            method: "POST",
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            status.textContent = data.detail || "Refresh sequence failed";
            return;
          }
          status.textContent = data.fill_in_progress
            ? `Refreshed “${intent.name}” · fill started`
            : `Refreshed “${intent.name}”`;
          await refreshIntents();
          await refreshFiles();
        } catch (err) {
          status.textContent = "Refresh sequence request failed";
          console.error(err);
        }
      });
      headingRow.appendChild(refreshBtn);
      const fillNowBtn = document.createElement("button");
      fillNowBtn.type = "button";
      setSymbolButton(fillNowBtn, BTN.fill, "Fill");
      fillNowBtn.addEventListener("click", async () => {
        const status = document.getElementById("intent-status");
        status.textContent = `Fill “${intent.name}”…`;
        try {
          const res = await fetch(`/api/intents/${intent.id}/fill-now`, { method: "POST" });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            status.textContent = data.detail || "Fill failed";
            return;
          }
          status.textContent = data.fill_in_progress
            ? `Fill “${intent.name}” started · ${data.files} cached so far`
            : `Fill “${intent.name}” · ${data.files} cached`;
          await refreshFiles();
        } catch (err) {
          status.textContent = "Fill request failed";
          console.error(err);
        }
      });
      headingRow.appendChild(fillNowBtn);
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      bindConfirmDelete(deleteBtn, {
        label: "Delete intent",
        onConfirm: async () => {
          const status = document.getElementById("intent-status");
          status.textContent = "Deleting…";
          try {
            const res = await fetch(`/api/intents/${intent.id}`, { method: "DELETE" });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              status.textContent = data.detail || "Delete intent failed";
              return;
            }
            if (editingIntentId === intent.id) {
              editingIntentId = null;
              if (editComposer) {
                editComposer.destroy();
                editComposer = null;
              }
            }
            hoursEditorState.delete(intent.id);
            status.textContent = `Deleted “${intent.name}”`;
            await refreshIntents({ force: true });
          } catch (err) {
            status.textContent = "Delete intent request failed";
            console.error(err);
          }
        },
      });
      headingRow.appendChild(deleteBtn);
      li.appendChild(headingRow);

      const meta = document.createElement("div");
      meta.className = "intent-meta muted";
      const tagsEl = document.createElement("span");
      tagsEl.className = "intent-meta-tags";
      const tagsLabel = document.createElement("span");
      tagsLabel.textContent = "Tags:";
      tagsEl.appendChild(tagsLabel);
      tagsEl.appendChild(
        renderTagChipsDisplay(intent.tags || [], catalogTagsCache),
      );
      const artistsEl = document.createElement("span");
      artistsEl.className = "intent-meta-artists";
      const artistIds = intent.artist_ids || [];
      const artistNames = artistIds.map((id) => artistNameById.get(id) || id);
      artistsEl.textContent = `Artists: ${artistNames.length ? artistNames.join(", ") : "-"}`;
      const platformsEl = document.createElement("span");
      platformsEl.className = "intent-meta-platforms";
      const platformsLabel = document.createElement("span");
      platformsLabel.textContent = "Sources:";
      platformsEl.appendChild(platformsLabel);
      const platforms = intent.platforms || DEFAULT_INTENT_PLATFORMS;
      for (const platform of platforms) {
        const icon = document.createElement("span");
        icon.className = "source-toggle";
        icon.setAttribute("aria-pressed", "true");
        icon.title = PLATFORM_LABELS[platform] || platform;
        if (PLATFORM_SVG[platform]) {
          icon.innerHTML = PLATFORM_SVG[platform];
        } else {
          icon.textContent = PLATFORM_LABELS[platform] || platform;
        }
        platformsEl.appendChild(icon);
      }
      const chancesEl = document.createElement("span");
      chancesEl.className = "intent-meta-chances has-tip";
      chancesEl.textContent = `Rating chances: ${formatChanceBlocks(intent.distribution)}`;
      chancesEl.dataset.tip = formatChancePercents(intent.distribution);
      meta.appendChild(tagsEl);
      meta.appendChild(artistsEl);
      meta.appendChild(platformsEl);
      meta.appendChild(chancesEl);
      li.appendChild(meta);
    }

    let assignments = [];
    let seq = null;
    const durationByMixId = new Map();
    const seqRes = await fetch(`/api/intents/${intent.id}/sequence`);
    if (seqRes.ok) {
      seq = await seqRes.json();
      assignments = seq.assignments || [];
      for (const entry of seq.entries || []) {
        if (entry.mix_id != null && entry.duration_seconds != null) {
          durationByMixId.set(
            String(entry.mix_id),
            Number(entry.duration_seconds) || 0,
          );
        }
      }
    }

    li.appendChild(renderDeviceHoursPanel(intent, assignments, durationByMixId));

    const footer = document.createElement("div");
    footer.className = "intent-footer";

    if (seq) {
      const seqKey = `${intent.id}:sequence`;
      const seqExpanded = expandedIntentPanes.has(seqKey);
      const seqFoldLabel = (open) =>
        `${open ? "▾" : "▸"} Shared sequence`;
      const seqPane = document.createElement("div");
      seqPane.className = "intent-pane intent-pane-sequence";
      const seqToggle = document.createElement("button");
      seqToggle.type = "button";
      seqToggle.className = "intent-pane-toggle";
      seqToggle.setAttribute("aria-expanded", seqExpanded ? "true" : "false");
      seqToggle.textContent = seqFoldLabel(seqExpanded);
      const seqBody = document.createElement("div");
      seqBody.className = "intent-pane-body";
      seqBody.hidden = !seqExpanded;
      if (seq.entries.length) {
        const table = document.createElement("table");
        table.className = "intent-seq-table";
        const thead = document.createElement("thead");
        const headRow = document.createElement("tr");
        for (const label of ["#", "Artist", "Title", "Bucket", "Duration"]) {
          const th = document.createElement("th");
          th.textContent = label;
          headRow.appendChild(th);
        }
        thead.appendChild(headRow);
        table.appendChild(thead);
        const tbody = document.createElement("tbody");
        for (const entry of seq.entries) {
          const tr = document.createElement("tr");
          const pos = document.createElement("td");
          pos.textContent = String(entry.position + 1);
          tr.appendChild(pos);
          const artist = document.createElement("td");
          artist.textContent = entry.artist || "Unknown";
          tr.appendChild(artist);
          const title = document.createElement("td");
          title.textContent = entry.title || entry.mix_id;
          tr.appendChild(title);
          const bucket = document.createElement("td");
          bucket.textContent = entry.bucket;
          tr.appendChild(bucket);
          const dur = document.createElement("td");
          dur.textContent =
            entry.duration_seconds != null ? formatDuration(entry.duration_seconds) : "—";
          tr.appendChild(dur);
          tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        seqBody.appendChild(table);
      } else {
        const empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "Empty sequence";
        seqBody.appendChild(empty);
      }
      seqToggle.addEventListener("click", () => {
        const open = seqBody.hidden;
        seqBody.hidden = !open;
        seqToggle.setAttribute("aria-expanded", open ? "true" : "false");
        seqToggle.textContent = seqFoldLabel(open);
        if (open) expandedIntentPanes.add(seqKey);
        else expandedIntentPanes.delete(seqKey);
      });
      seqPane.appendChild(seqToggle);
      seqPane.appendChild(seqBody);
      footer.appendChild(seqPane);
    }

    const editor = hoursEditorState.get(intent.id);
    if (!editor) {
      const assignBtn = document.createElement("button");
      assignBtn.type = "button";
      setSymbolButton(assignBtn, BTN.add, "Assign hours");
      assignBtn.addEventListener("click", () => {
        hoursEditorState.set(intent.id, { mode: "add" });
        // Peers may have landed while a long fill held SSE; refresh before render.
        void (async () => {
          await refreshPeers();
          await refreshIntents({ force: true });
        })();
      });
      footer.appendChild(assignBtn);
    }

    li.appendChild(footer);

    list.appendChild(li);
  }
  await refreshPlayerIntents();
}

function markPairPinCopied(copyBtn) {
  setSymbolButton(copyBtn, BTN.copy, "Copied");
  if (actionTipActive === copyBtn) showActionTip(copyBtn);
  setTimeout(() => {
    if (copyBtn.dataset.tip === "Copied") {
      setSymbolButton(copyBtn, BTN.copy, "Copy PIN");
      if (actionTipActive === copyBtn) showActionTip(copyBtn);
    }
  }, 1500);
}

async function copyPairPin() {
  const pinEl = document.getElementById("pair-pin");
  const copyBtn = document.getElementById("pair-pin-copy-btn");
  const pin = (pinEl?.value || "").trim();
  if (!pin) return;

  pinEl.focus();
  pinEl.select();

  let ok = false;
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(pin);
      ok = true;
    } catch (err) {
      console.error(err);
    }
  }
  if (!ok) {
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      console.error(err);
    }
  }

  if (ok) {
    markPairPinCopied(copyBtn);
  } else {
    const status = document.getElementById("pair-status");
    if (status) status.textContent = "Could not copy PIN — select and copy manually";
  }
}

async function startPairSession() {
  const status = document.getElementById("pair-status");
  status.textContent = "Starting pairing session…";
  try {
    const res = await fetch("/api/pair/session/start", { method: "POST" });
    let data = null;
    try {
      data = await res.json();
    } catch (parseErr) {
      status.textContent = `Could not start pairing (HTTP ${res.status})`;
      console.error(parseErr);
      return;
    }
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`;
      status.textContent = detail || "Could not start pairing";
      return;
    }
    status.textContent = "Share the PIN (or QR) with the other device";
    renderPairSession(data);
    startPairPoll();
  } catch (err) {
    status.textContent = "Could not start pairing";
    console.error(err);
  }
}

async function cancelPairSession() {
  const status = document.getElementById("pair-status");
  try {
    await fetch("/api/pair/session/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    status.textContent = "Pairing cancelled";
    renderPairSession({ active: false });
  } catch (err) {
    status.textContent = "Cancel failed";
    console.error(err);
  }
}

async function confirmPairSession() {
  const status = document.getElementById("pair-status");
  status.textContent = "Confirming…";
  try {
    const res = await fetch("/api/pair/session/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.detail || "Confirm failed";
      return;
    }
    if (data.complete && data.peer) {
      status.textContent = `Paired with ${data.peer.name}`;
      renderPairSession(data.session || { active: false });
      collapsePairForm();
      await refreshPeers();
      await refreshIntents({ force: true });
      stopPairPoll();
      return;
    }
    status.textContent = "Waiting for the other device to Confirm…";
    if (data.session) {
      renderPairSession(data.session);
    }
    startPairPoll();
  } catch (err) {
    status.textContent = "Confirm failed";
    console.error(err);
  }
}

async function joinPairSession({ peer_url, pin, session_id }) {
  const status = document.getElementById("pair-status");
  status.textContent = "Joining…";
  try {
    const res = await fetch("/api/pair/session/join-remote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ peer_url, pin, session_id: session_id || null }),
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.detail || "Join failed";
      return false;
    }
    status.textContent = "Compare the confirm code, then Confirm on both devices";
    renderPairSession(data);
    startPairPoll();
    return true;
  } catch (err) {
    status.textContent = "Join failed";
    console.error(err);
    return false;
  }
}

pairCollapsible = bindCollapsibleAdd(document.getElementById("pair-form"), {
  button: "#pair-join-btn",
  expandLabel: "Join peer",
  submitLabel: "Join peer",
  cancelButton: "#pair-form-cancel",
  focusSelector: "#peer-url",
  onCancel: () => {
    document.getElementById("peer-url").value = "";
    document.getElementById("pair-code").value = "";
    const candidate = document.getElementById("pair-candidate");
    if (candidate) candidate.value = "";
    document.getElementById("pair-status").textContent = "";
    stopPairScan();
    const sessionCancel = document.getElementById("pair-cancel-btn");
    if (sessionCancel && !sessionCancel.hidden) {
      void cancelPairSession();
    }
  },
});

document.getElementById("pair-start-btn").addEventListener("click", () => {
  void startPairSession();
});
document.getElementById("pair-cancel-btn").addEventListener("click", () => {
  void cancelPairSession();
});
document.getElementById("pair-confirm-btn").addEventListener("click", () => {
  void confirmPairSession();
});
document.getElementById("pair-pin-copy-btn").addEventListener("click", () => {
  void copyPairPin();
});
document.getElementById("pair-candidate").addEventListener("change", (event) => {
  const value = event.target.value;
  if (value) {
    document.getElementById("peer-url").value = value;
  }
});
document.getElementById("pair-candidate").addEventListener("mousedown", () => {
  void refreshPairCandidatesFromDiscovery();
});
document.getElementById("pair-candidate").addEventListener("focus", () => {
  void refreshPairCandidatesFromDiscovery();
});

document.getElementById("pair-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("pair-status");
  const peerUrl = document.getElementById("peer-url").value.trim();
  const pin = document.getElementById("pair-code").value.trim();
  if (!peerUrl || !pin) {
    status.textContent = "Peer URL and PIN are required";
    return;
  }
  await joinPairSession({ peer_url: peerUrl, pin });
});

let pairScanStream = null;
let pairScanTimer = null;
let pairScanBusy = false;

function setPairScanUi(active) {
  document.getElementById("pair-scan").hidden = !active;
  document.getElementById("pair-scan-btn").disabled = active;
}

function stopPairScan() {
  if (pairScanTimer != null) {
    clearTimeout(pairScanTimer);
    pairScanTimer = null;
  }
  pairScanBusy = false;
  const video = document.getElementById("pair-scan-video");
  video.pause();
  video.srcObject = null;
  if (pairScanStream) {
    for (const track of pairScanStream.getTracks()) {
      track.stop();
    }
    pairScanStream = null;
  }
  setPairScanUi(false);
}

async function handleScannedPairPayload(rawText) {
  const status = document.getElementById("pair-status");
  let payload;
  try {
    payload = JSON.parse(rawText);
  } catch (err) {
    status.textContent = "Scanned QR is not a pairing offer";
    return;
  }
  if (!payload || typeof payload !== "object" || payload.v !== 2 || !payload.pin || !payload.url) {
    status.textContent = "Scanned QR is not an ephemeral pairing offer";
    return;
  }
  document.getElementById("peer-url").value = payload.url;
  document.getElementById("pair-code").value = payload.pin;
  stopPairScan();
  await joinPairSession({
    peer_url: payload.url,
    pin: payload.pin,
    session_id: payload.session_id || null,
  });
}

async function tickPairScan(detector) {
  if (!pairScanStream || pairScanBusy) {
    return;
  }
  const video = document.getElementById("pair-scan-video");
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
    pairScanTimer = setTimeout(() => tickPairScan(detector), 250);
    return;
  }
  pairScanBusy = true;
  try {
    const codes = await detector.detect(video);
    const raw = codes.find((code) => code.rawValue)?.rawValue;
    if (raw) {
      await handleScannedPairPayload(raw);
      return;
    }
  } catch (err) {
    console.error(err);
  } finally {
    pairScanBusy = false;
  }
  if (pairScanStream) {
    pairScanTimer = setTimeout(() => tickPairScan(detector), 250);
  }
}

async function startPairScan() {
  const status = document.getElementById("pair-status");
  if (!window.isSecureContext) {
    status.textContent = "Camera scan needs HTTPS or localhost; use short code instead";
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    status.textContent = "Camera not available; use short code instead";
    return;
  }
  if (typeof BarcodeDetector === "undefined") {
    status.textContent = "QR scan not supported in this browser; use short code instead";
    return;
  }
  let detector;
  try {
    detector = new BarcodeDetector({ formats: ["qr_code"] });
  } catch (err) {
    status.textContent = "QR scan not supported in this browser; use short code instead";
    console.error(err);
    return;
  }
  stopPairScan();
  status.textContent = "Starting camera…";
  try {
    pairScanStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: "environment" } },
    });
  } catch (err) {
    status.textContent = "Camera permission denied; use short code instead";
    console.error(err);
    return;
  }
  const video = document.getElementById("pair-scan-video");
  video.srcObject = pairScanStream;
  setPairScanUi(true);
  try {
    await video.play();
  } catch (err) {
    stopPairScan();
    status.textContent = "Could not start camera preview";
    console.error(err);
    return;
  }
  status.textContent = "Point at the other device's QR…";
  tickPairScan(detector);
}

document.getElementById("pair-scan-btn").addEventListener("click", () => {
  startPairScan();
});
document.getElementById("pair-scan-stop").addEventListener("click", () => {
  stopPairScan();
  document.getElementById("pair-status").textContent = "Scan stopped";
});

function minDurationSecondsFromForm() {
  const minutes = Number(document.getElementById("min-duration-minutes").value);
  return Number.isFinite(minutes) ? Math.max(0, Math.round(minutes * 60)) : 1200;
}

async function postRefreshArtists(artistIds) {
  const body = { min_duration_seconds: minDurationSecondsFromForm() };
  if (artistIds != null) {
    body.artist_ids = artistIds;
  }
  const res = await fetch("/api/artists/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return { ok: false, detail: data.detail || "Refresh artists failed" };
  }
  return { ok: true, ...data };
}

artistsCollapsible = bindCollapsibleAdd(document.getElementById("artists-form"), {
  button: "#artists-submit",
  expandLabel: "Add artists",
  submitLabel: "Add artists",
  cancelButton: "#artists-cancel",
  focusSelector: "#artist-urls",
  onCancel: () => {
    document.getElementById("artist-urls").value = "";
    document.getElementById("artists-status").textContent = "";
  },
});

document.getElementById("artists-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("artists-status");
  const raw = document.getElementById("artist-urls").value;
  const urls = raw
    .split(/[\s,]+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const min_duration_seconds = minDurationSecondsFromForm();
  status.textContent = "Adding artists…";
  try {
    const res = await fetch("/api/artists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls, min_duration_seconds }),
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.detail || "Add artists failed";
      return;
    }
    status.textContent = `Added ${data.added} releases · ${data.artists} artists`;
    document.getElementById("artist-urls").value = "";
    artistsCollapsible?.collapse();
    await refreshMixes();
    await refreshIntentArtistOptions();
  } catch (err) {
    status.textContent = "Add artists request failed";
    console.error(err);
  }
});

document.getElementById("refresh-all-artists").addEventListener("click", async () => {
  const status = document.getElementById("artists-status");
  status.textContent = "Refreshing all artists…";
  try {
    const data = await postRefreshArtists(null);
    if (!data.ok) {
      status.textContent = data.detail || "Refresh artists failed";
      return;
    }
    status.textContent = `Refreshed · ${data.added} new release(s) · ${data.artists} artists`;
    await refreshMixes();
    await refreshIntentArtistOptions();
  } catch (err) {
    status.textContent = "Refresh artists request failed";
    console.error(err);
  }
});

document.getElementById("intent-expand")?.addEventListener("click", () => {
  expandCreateForm();
});
document.getElementById("intent-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
});

document.getElementById("sync-btn").addEventListener("click", async () => {
  const status = document.getElementById("sync-status");
  status.textContent = "Syncing…";
  try {
    const res = await fetch("/api/sync", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.detail || "Sync failed";
      return;
    }
    status.textContent = data.fill_in_progress
      ? `Synced · ${data.peers} peers · ${data.mixes} releases · filling caches…`
      : `Synced · ${data.peers} peers · ${data.mixes} releases · ${data.files} cached`;
    await refreshPeers();
    await refreshMixes();
    await refreshIntents();
    await refreshFiles();
  } catch (err) {
    status.textContent = "Sync request failed";
    console.error(err);
  }
});

document.getElementById("metered-toggle").addEventListener("change", async (event) => {
  const status = document.getElementById("fill-status");
  const metered = event.target.checked;
  status.textContent = metered ? "Marking link metered…" : "Marking link unmetered…";
  try {
    const res = await fetch("/api/metered", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metered }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Metered switch failed";
      event.target.checked = !metered;
      return;
    }
    status.textContent = data.metered
      ? "Metered · origin capped to current + one ahead"
      : "Unmetered · standing fill uses full hours";
  } catch (err) {
    status.textContent = "Metered switch request failed";
    event.target.checked = !metered;
    console.error(err);
  }
});

document.getElementById("fill-btn").addEventListener("click", async () => {
  const status = document.getElementById("fill-status");
  status.textContent = "Starting fill…";
  try {
    const res = await fetch("/api/fill", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.detail || "Fill failed";
      return;
    }
    status.textContent = data.fill_in_progress
      ? `Filling caches… (${data.files} cached so far)`
      : `Filled · ${data.files} cached`;
    await refreshFiles();
    await refreshIntents();
  } catch (err) {
    status.textContent = "Fill request failed";
    console.error(err);
  }
});

document.getElementById("player-play").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  const btn = document.getElementById("player-play");
  try {
    if (btn.dataset.playing === "true" || lastPlayerPlaying) {
      // Pause whatever intent is actually playing, independent of the dropdown.
      await pausePlayback();
      return;
    }
    await playIntent(document.getElementById("player-intent").value);
  } catch (err) {
    if (status) status.textContent = "Play request failed";
    console.error(err);
  }
});

document.getElementById("player-skip").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  const intentId = document.getElementById("player-intent").value;
  status.textContent = "Skipping…";
  try {
    const body = intentId ? { intent_id: intentId } : {};
    const res = await fetch("/api/player/skip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Skip failed";
      return;
    }
    status.textContent = "";
    lastPlayheadCommitAt = Date.now();
    playheadPlayedNotifiedForMix = null;
    await refreshPlayer();
    await refreshFiles();
  } catch (err) {
    status.textContent = "Skip request failed";
    console.error(err);
  }
});

document.getElementById("player-stop").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  try {
    await fetch("/api/player/stop", { method: "POST" });
    status.textContent = "Stopped (release left in place if under 75%)";
    lastPlayheadCommitAt = 0;
    playheadPlayedNotifiedForMix = null;
    await refreshPlayer();
  } catch (err) {
    status.textContent = "Stop request failed";
    console.error(err);
  }
});

const playerSeekbar = document.getElementById("player-seekbar");
const playerSeekRail = playerSeekbar?.closest(".player-seek-rail");
if (playerSeekbar) {
  playerSeekbar.addEventListener("pointerdown", () => {
    playerSeekDragging = true;
  });
  playerSeekbar.addEventListener("pointerup", () => {
    playerSeekDragging = false;
  });
  playerSeekbar.addEventListener("pointercancel", () => {
    playerSeekDragging = false;
  });
  const seekHoverTarget = playerSeekRail || playerSeekbar;
  seekHoverTarget.addEventListener("pointermove", (event) => {
    const hit = event.target instanceof Element
      ? event.target.closest(".player-seek-section")
      : null;
    if (hit && playerSeekRail?.contains(hit)) {
      setSeekTrackHighlight(Number(hit.dataset.trackIndex));
      return;
    }
    highlightSeekTrackAtClientX(playerSeekbar, event.clientX);
  });
  seekHoverTarget.addEventListener("pointerleave", () => {
    clearSeekTrackHighlight();
  });
  seekHoverTarget.addEventListener("click", (event) => {
    const hit = event.target instanceof Element
      ? event.target.closest(".player-seek-section")
      : null;
    if (!hit || !playerSeekRail?.contains(hit)) return;
    event.preventDefault();
    event.stopPropagation();
    void seekToTrackStart(Number(hit.dataset.trackIndex));
  });
  playerSeekbar.addEventListener("input", (event) => {
    playerSeekDragging = true;
    const position = Math.round(Number(playerSeekbar.value || 0));
    lastKnownPositionSeconds = position;
    syncSeekProgress(playerSeekbar);
    const currentEl = document.getElementById("player-time-current");
    if (currentEl) {
      currentEl.textContent = formatClock(position);
    }
    if (event instanceof PointerEvent) {
      highlightSeekTrackAtClientX(playerSeekbar, event.clientX);
    } else {
      const index = trackIndexAtTimelineSeconds(playerSeekTracks, position);
      if (index >= 0) {
        setSeekTrackHighlight(index);
      }
    }
  });
  playerSeekbar.addEventListener("change", async () => {
    playerSeekDragging = false;
    const position = Math.round(Number(playerSeekbar.value || 0));
    await seekToPlayerPosition(position);
  });
}

document.getElementById("player-mark").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  status.textContent = "Marking played…";
  try {
    const res = await fetch("/api/player/mark-played", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Mark played failed";
      return;
    }
    status.textContent = "Marked played";
    if (data.mix?.id) {
      playheadPlayedNotifiedForMix = data.mix.id;
    }
    await refreshPlayer();
    await refreshMixes();
    await refreshFiles();
    await refreshIntents();
  } catch (err) {
    status.textContent = "Mark played request failed";
    console.error(err);
  }
});

async function rateCurrentPlayerMix(stars) {
  const status = document.getElementById("player-status");
  const player = await (await fetch("/api/player")).json();
  if (!player.current_mix_id) {
    status.textContent = "Nothing to rate";
    throw new Error("Nothing to rate");
  }
  const res = await fetch(`/api/mixes/${player.current_mix_id}/rate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stars: Number(stars) }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    status.textContent = data.detail || "Rate failed";
    throw new Error(data.detail || "Rate failed");
  }
  status.textContent = "";
  await refreshMixes();
  await refreshPlayer();
}

document.getElementById("catalog-show-rejected")?.addEventListener("click", async (event) => {
  const btn = event.currentTarget;
  showRejectedCatalog = btn.getAttribute("aria-pressed") !== "true";
  syncRejectedToggle(btn, showRejectedCatalog);
  await refreshMixes({ force: true });
});

document.getElementById("play-history-show-rejected")?.addEventListener("click", async (event) => {
  const btn = event.currentTarget;
  showRejectedHistory = btn.getAttribute("aria-pressed") !== "true";
  syncRejectedToggle(btn, showRejectedHistory);
  await refreshPlayHistory();
});

/** Notice section taxonomy mirrored from DeviceAgent UI view notices. */
const VIEW_NOTICE_SECTIONS = ["mixes", "play_history", "intents", "peers", "cache"];

async function refreshAllViewSurfaces() {
  await refreshPeers();
  // No force: respect focusInside so tag/hours editors are not remounted mid-edit.
  await refreshMixes();
  await refreshPlayHistory();
  await refreshIntents();
  await refreshFiles();
}

async function refreshViewSections(sections) {
  const wanted = new Set(sections);
  // Independent branches: a burst may name both mixes and play_history.
  // Live notices must not force-rebuild while a tag input has focus.
  if (wanted.has("mixes")) {
    await refreshMixes();
  }
  if (wanted.has("play_history") && !wanted.has("mixes")) {
    // refreshMixes already refreshes Play history when mixes are included.
    await refreshPlayHistory();
  }
  if (wanted.has("intents")) {
    await refreshIntents();
  }
  if (wanted.has("peers")) {
    await refreshPeers();
    // Device picker for Assign hours is derived from peersCache.
    if (hoursEditorState.size) {
      await refreshIntents();
    }
  }
  if (wanted.has("cache")) {
    await refreshFiles();
  }
}

function connectViewNotices() {
  const es = new EventSource("/api/view-notices");
  es.addEventListener("open", () => {
    void refreshAllViewSurfaces();
  });
  es.addEventListener("notice", (event) => {
    let section = null;
    try {
      const payload = JSON.parse(event.data);
      section = payload?.section;
    } catch (err) {
      console.error("view notice parse failed", err);
      return;
    }
    if (!section || !VIEW_NOTICE_SECTIONS.includes(section)) return;
    void refreshViewSections([section]);
  });
  return es;
}

(async () => {
  markStaticSymbolButtons();
  initSectionInfo();
  initSectionNav();
  initActionTips();
  const expandBtn = document.getElementById("intent-expand");
  if (expandBtn) setSymbolButton(expandBtn, BTN.add, "Create intent");
  const playerStarsRoot = document.getElementById("player-stars");
  const playerTagRoot = document.getElementById("player-tag-editor");
  const playerRejectBtn = document.getElementById("player-reject");
  const playerUndoBtn = document.getElementById("player-undo-reject");
  if (playerStarsRoot && playerTagRoot && playerRejectBtn && playerUndoBtn) {
    playerAnnotateKit = mountAnnotateKit({
      surface: "player",
      starsRoot: playerStarsRoot,
      tagRoot: playerTagRoot,
      rejectBtn: playerRejectBtn,
      undoBtn: playerUndoBtn,
      statusEl: document.getElementById("player-reject-status"),
      getMixId: () => currentMixId,
      async onRate(stars) {
        try {
          await rateCurrentPlayerMix(stars);
        } catch (err) {
          const status = document.getElementById("player-status");
          if (status && !status.textContent) {
            status.textContent = "Rate request failed";
          }
          console.error(err);
          throw err;
        }
      },
    });
    playerStarRating = playerAnnotateKit.starRating;
    playerTagEditor = playerAnnotateKit.tagEditor;
  }
  mountCatalogFilters();
  resetCatalogFilters();
  showRejectedHistory = false;
  syncRejectedToggle(document.getElementById("play-history-show-rejected"), false);
  await refreshHealth();
  await refreshActivity();
  await refreshPairing();
  await refreshPeers();
  await refreshMixes();
  await refreshFiles();
  await refreshIntents();
  await refreshPlayerIntents();
  await refreshPlayer();
  syncPlayerChrome();
  window.addEventListener("resize", () => syncPlayerChrome());
  if (typeof ResizeObserver === "function") {
    const chromeObserver = new ResizeObserver(() => syncPlayerChrome());
    const playerNowRow = document.querySelector("#player .player-now-row");
    const playerHeading = document.querySelector("#player .player-heading-row");
    if (playerNowRow) chromeObserver.observe(playerNowRow);
    if (playerHeading) chromeObserver.observe(playerHeading);
  }
  connectViewNotices();
  setInterval(refreshActivity, 1000);
})();
