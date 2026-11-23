let localDeviceId = null;
let localFingerprint = null;
let localPriority = null;
let currentMixId = null;
let peersCache = [];
const expandedCatalogArtists = new Set();
const expandedCacheIntents = new Set();
/** Intent ids whose shared sequence rows are expanded in the Intents table. */
const expandedIntentSequences = new Set();
/** @type {Map<string, {mode: "add"|"edit", deviceId?: string}>} */
const hoursEditorState = new Map();
/** Catalog Rejected filter (default off). */
let showRejectedCatalog = false;
/** Catalog source filter (OR); empty = any. */
let catalogFilterPlatforms = [];
/** Catalog minimum stars filter; null = any rating (incl. unrated). */
let catalogFilterMinStars = null;
/** Catalog tag filter (AND); empty = no tag constraint. */
let catalogFilterTags = [];
/** Catalog name filter (title or artist substring); empty = any. */
let catalogNameFilter = "";
/** @type {ReturnType<typeof mountTagEditor> | null} */
let catalogTagFilterEditor = null;
/** @type {{ setFloor: (n: number|null) => void, getFloor: () => number|null } | null} */
let catalogStarFilter = null;
/** Intent list tag filter (AND); empty = any. */
let intentListFilterTags = [];
/** Intent list artist filter (OR); empty = any. */
let intentListFilterArtistIds = [];
/** Intent list source filter (OR); empty = any.
 * Named apart from helper intentFilterPlatforms(). */
let intentListFilterPlatforms = [];
/** Intent list name filter (substring); empty = any. */
let intentNameFilter = "";
/** Cache name filter (title or artist substring); empty = any. */
let cacheNameFilter = "";
/** @type {ReturnType<typeof setTimeout> | null} */
let catalogNameFilterTimer = null;
/** @type {ReturnType<typeof setTimeout> | null} */
let intentNameFilterTimer = null;
/** @type {ReturnType<typeof setTimeout> | null} */
let cacheNameFilterTimer = null;
const NAME_FILTER_DEBOUNCE_MS = 150;
/** @type {ReturnType<typeof mountTagEditor> | null} */
let intentTagFilterEditor = null;
/** @type {ReturnType<typeof mountArtistEditor> | null} */
let intentArtistFilterEditor = null;
/** Soft Rejected window (matches backend SOFT_REJECT_SECONDS). */
const SOFT_REJECT_MS = 5 * 60 * 1000;
/** Player notice overlay auto-clear. */
const PLAYER_NOTICE_MS = 5 * 1000;
/** @type {ReturnType<typeof setTimeout> | null} */
let playerNoticeTimer = null;
/** @type {Map<string, number>} mixId → timeout when Soft ages to Hard (list refresh) */
const softRejectTimers = new Map();
let lastPlayheadCommitAt = 0;
let lastKnownPositionSeconds = 0;
let playheadCommitInFlight = false;
/** Heartbeat only; pause/stop/seek/skip/track boundaries commit immediately. */
const PLAYHEAD_COMMIT_MS = 5 * 60 * 1000;
/** Local seekbar/clock refresh; player state comes from view notices. */
const PLAYER_UI_TICK_MS = 250;
/** Cache SSE can storm during fill; coalesce so the newest snapshot wins. */
let filesRefreshEpoch = 0;
let filesRefreshTail = Promise.resolve();
let filesRefreshForcePending = false;
/** Mix id already announced as marked played during this play session. */
let playheadPlayedNotifiedForMix = null;
/** Last player poll: used so intent-table play buttons stay in sync. */
let lastPlayerPlaying = false;
let lastPlayerIntentId = null;
/** Intent id Playlog last used for default / preserved scroll. */
let playlogScrollIntentId = null;
/** In-flight Drop keys (`intentId:mixId`) — grey row, hide Drop until refresh. */
const pendingSequenceDrops = new Set();
/** In-flight Reject mix ids — mute row until refresh. */
const pendingRejects = new Set();
/** In-flight Un-reject mix ids — clear mute until refresh. */
const pendingUnrejects = new Set();
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
  drop: "⊖",
  queue: "↪",
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
  expandSeq: "▼",
  collapseSeq: "▲",
  scrollHome: "⌃",
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

/** Intent-only sentinel: tags=["—"] means untagged-only. Not a catalog/mix tag. */
const UNTAGGED_TAG = "—";

function normalizeTag(tag) {
  return String(tag || "")
    .trim()
    .toLowerCase();
}

/**
 * Normalize intent filter tags: real tags OR-only; bare UNTAGGED_TAG kept;
 * sentinel dropped when any real tag is present.
 * @param {string[]} tags
 * @returns {string[]}
 */
function normalizeIntentTags(tags) {
  const out = [];
  let hasUntagged = false;
  for (const tag of tags || []) {
    const cleaned = normalizeTag(tag);
    if (!cleaned) continue;
    if (cleaned === UNTAGGED_TAG) {
      hasUntagged = true;
      continue;
    }
    if (!out.includes(cleaned)) out.push(cleaned);
  }
  if (out.length) return out;
  if (hasUntagged) return [UNTAGGED_TAG];
  return [];
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
  const cleaned = normalizeIntentTags(tags || []);
  const chipsEl = document.createElement("div");
  chipsEl.className = "tag-chips";
  if (!cleaned.length) {
    const empty = document.createElement("span");
    empty.className = "intent-meta-empty";
    empty.textContent = "-";
    chipsEl.appendChild(empty);
    return chipsEl;
  }
  const realTags = cleaned.filter((tag) => tag !== UNTAGGED_TAG);
  const context =
    allTags != null ? [...allTags, ...realTags] : realTags;
  const slots = assignTagChipSlots(context);
  for (const tag of cleaned) {
    const chip = document.createElement("span");
    chip.className = "tag-chip";
    chip.dataset.tag = tag;
    if (tag === UNTAGGED_TAG) {
      chip.classList.add("is-untagged");
      chip.title = "Untagged only";
    } else {
      const slot = slots.get(tag) ?? tagChipHash(tag) % TAG_CHIP_PALETTE.length;
      const [border, fill] = tagChipSwatchCss(TAG_CHIP_PALETTE[slot]);
      chip.style.setProperty("--tag-chip-border", border);
      chip.style.setProperty("--tag-chip-fill", fill);
    }
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
 *   untaggedSentinel?: boolean,
 * }} options
 */
function mountTagEditor(root, options) {
  const getCatalogTags = options.getCatalogTags || (() => catalogTagsCache);
  const confirmRemove = options.confirmRemove !== false;
  const untaggedSentinel = options.untaggedSentinel === true;
  const addLabel = options.addLabel || "Add tag";
  let tags = untaggedSentinel
    ? normalizeIntentTags(options.tags || [])
    : (options.tags || [])
        .map(normalizeTag)
        .filter((tag) => tag && tag !== UNTAGGED_TAG);
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
    if (untaggedSentinel && needle === UNTAGGED_TAG) {
      return [];
    }
    const catalog = getCatalogTags()
      .map(normalizeTag)
      .filter((tag) => tag && tag !== UNTAGGED_TAG);
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
    if (needle && needle !== UNTAGGED_TAG && !owned.has(needle)) {
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
    if (cleaned === UNTAGGED_TAG) return;
    const prev = [...tags];
    tags = untaggedSentinel
      ? [...tags.filter((t) => t !== UNTAGGED_TAG), cleaned]
      : [...tags, cleaned];
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
    if (
      untaggedSentinel &&
      tags.length === 0 &&
      cleaned !== UNTAGGED_TAG
    ) {
      tags = [UNTAGGED_TAG];
    }
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
    ].filter((tag) => tag && tag !== UNTAGGED_TAG);
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
      const chip = document.createElement("span");
      chip.className = "tag-chip";
      chip.dataset.tag = tag;
      if (tag === UNTAGGED_TAG) {
        chip.classList.add("is-untagged");
        chip.title = "Untagged only";
      } else {
        const slot =
          slots.get(tag) ?? tagChipHash(tag) % TAG_CHIP_PALETTE.length;
        const [border, fill] = tagChipSwatchCss(TAG_CHIP_PALETTE[slot]);
        chip.style.setProperty("--tag-chip-border", border);
        chip.style.setProperty("--tag-chip-fill", fill);
      }
      const label = document.createElement("span");
      label.className = "tag-chip-label";
      label.textContent = tag;
      chip.appendChild(label);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "tag-chip-x";
      // pointerdown (not click): player poll remounts chips between mousedown and
      // click, which can deliver the click to a different tag's ×.
      const removeLabel =
        tag === UNTAGGED_TAG ? "Clear untagged-only filter" : `Remove “${tag}”`;
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
        remove.setAttribute("aria-label", removeLabel);
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
    addBtn.setAttribute("aria-label", addLabel);
    addBtn.dataset.tip = addLabel;
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
      const normalized = untaggedSentinel
        ? normalizeIntentTags(next || [])
        : (next || [])
            .map(normalizeTag)
            .filter((tag) => tag && tag !== UNTAGGED_TAG);
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
 * Chip artist picker: plain chips, confirm-to-remove (optional), + search (catalog only).
 * @param {HTMLElement} root
 * @param {{
 *   artists?: {id: string, name: string}[],
 *   onAdd: (artist: {id: string, name: string}) => Promise<void> | void,
 *   onRemove: (artist: {id: string, name: string}) => Promise<void> | void,
 *   getCatalogArtists?: () => {id: string, name: string}[],
 *   confirmRemove?: boolean,
 * }} options
 */
function mountArtistEditor(root, options) {
  const getCatalogArtists =
    options.getCatalogArtists || (() => catalogArtistsCache);
  const confirmRemove = options.confirmRemove !== false;
  const addLabel = options.addLabel || "Add artist";
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
      if (confirmRemove && confirming === artist.id) {
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
          if (confirmRemove) armConfirm(artist.id);
          else void removeArtist(artist.id);
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
    addBtn.setAttribute("aria-label", addLabel);
    addBtn.dataset.tip = addLabel;
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

/** First click arms; second click runs onConfirm. */
function bindConfirmClick(
  btn,
  {
    idleSymbol,
    idleLabel,
    armedSymbol = BTN.confirmDelete,
    armedLabel = "really?",
    onConfirm,
    stopPropagation = false,
  },
) {
  setSymbolButton(btn, idleSymbol, idleLabel);
  let armed = false;
  let resetTimer = null;

  const reset = () => {
    armed = false;
    btn.classList.remove("confirm-pending");
    setSymbolButton(btn, idleSymbol, idleLabel);
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
      setSymbolButton(btn, armedSymbol, armedLabel);
      if (actionTipActive === btn) showActionTip(btn);
      resetTimer = setTimeout(reset, 4000);
      return;
    }
    reset();
    await onConfirm(event);
  });
}

/** First click arms (💥); second click runs onConfirm. */
function bindConfirmDelete(btn, { label, onConfirm, stopPropagation = false }) {
  bindConfirmClick(btn, {
    idleSymbol: BTN.delete,
    idleLabel: label,
    armedSymbol: BTN.confirmDelete,
    armedLabel: "really delete?",
    onConfirm,
    stopPropagation,
  });
}

function isSoftRejected(mix, nowMs = Date.now()) {
  if (!mix || !mix.rejected || !mix.rejected_at) return false;
  const at = Date.parse(mix.rejected_at);
  if (!Number.isFinite(at)) return false;
  return nowMs - at < SOFT_REJECT_MS;
}

function isHardRejected(mix, nowMs = Date.now()) {
  return !!(mix && mix.rejected && !isSoftRejected(mix, nowMs));
}

/**
 * Important action outcome on the player overlay (latest-wins, 5s timeout).
 * @param {string} message
 * @param {"ok"|"warn"|"error"} [kind="ok"]
 */
function showNotice(message, kind = "ok") {
  const el = document.getElementById("player-notice");
  if (!el) return;
  const text = String(message || "").trim();
  if (!text) {
    clearNotice();
    return;
  }
  const safeKind = kind === "warn" || kind === "error" ? kind : "ok";
  el.textContent = text;
  el.dataset.kind = safeKind;
  el.hidden = false;
  if (playerNoticeTimer != null) clearTimeout(playerNoticeTimer);
  playerNoticeTimer = setTimeout(() => {
    playerNoticeTimer = null;
    clearNotice();
  }, PLAYER_NOTICE_MS);
}

function clearNotice() {
  if (playerNoticeTimer != null) {
    clearTimeout(playerNoticeTimer);
    playerNoticeTimer = null;
  }
  const el = document.getElementById("player-notice");
  if (!el) return;
  el.textContent = "";
  el.removeAttribute("data-kind");
  el.hidden = true;
}

/** Durable pairing-session choreography hint (not the player overlay). */
function setPairSessionHint(text) {
  const el = document.getElementById("pair-session-hint");
  if (!el) return;
  const value = String(text || "").trim();
  el.textContent = value;
  el.hidden = !value;
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

const FOCUS_TABS = ["playlog", "intents", "catalog", "cache", "peers", "activity"];
const SCROLL_HASHES = new Set(["player"]);

/** Active focus tab id (explicit; avoids DOM races during pane swaps). */
let activeFocusTab = "playlog";
/** Per-tab .focus-pane-scroll scrollTop (also drives player soft-collapse). */
const focusTabScrollTop = Object.create(null);

function closeAppMenu() {
  const menu = document.querySelector(".app-menu");
  if (menu) menu.open = false;
}

/** Pane list scroller for a focus tab. */
function focusPaneScrollEl(tabId) {
  const pane = document.querySelector(`[data-focus-pane="${tabId}"]`);
  return pane?.querySelector(".focus-pane-scroll") || null;
}

/** Snapshot pane scrollTop for a focus tab. */
function saveFocusTabScroll(tabId) {
  if (!FOCUS_TABS.includes(tabId)) return;
  const el = focusPaneScrollEl(tabId);
  if (!el) return;
  if (tabId === "playlog") {
    // Skip until Playlog has landed once, else a pre-data leave stashes 0.
    if (!Object.prototype.hasOwnProperty.call(focusTabScrollTop, "playlog")) {
      return;
    }
  }
  focusTabScrollTop[tabId] = el.scrollTop;
}

/** Remember Playlog pane scrollTop after −2 land or in-tab restore. */
function rememberPlaylogScroll() {
  const el = focusPaneScrollEl("playlog");
  if (el) focusTabScrollTop.playlog = el.scrollTop;
}

/**
 * Restore pane scrollTop for a focus tab. Saved positions do not rewrite
 * player collapse (avoids resize on switch); first Playlog −2 land does.
 */
function restoreFocusTabScroll(tabId) {
  const el = focusPaneScrollEl(tabId);
  if (!el) return;
  const hasSaved = Object.prototype.hasOwnProperty.call(
    focusTabScrollTop,
    tabId,
  );
  if (tabId === "playlog" && !hasSaved) {
    scrollPlaylogDefaultView();
    if (document.querySelector("#playlog-body .playlog-row")) {
      rememberPlaylogScroll();
    }
    expandPlayerCollapseFully();
    paneCollapseLastScrollTop = el.scrollTop;
    return;
  }
  suppressPlayerCollapseFromPane = true;
  try {
    if (tabId === "playlog") {
      el.scrollTop = focusTabScrollTop.playlog;
      updatePlaylogStickyMetrics();
      syncPlaylogCurrentStuck();
      paneCollapseLastScrollTop = el.scrollTop;
      return;
    }
    el.scrollTop = hasSaved ? focusTabScrollTop[tabId] : 0;
    paneCollapseLastScrollTop = el.scrollTop;
  } finally {
    suppressPlayerCollapseFromPane = false;
  }
}

function setFocusTab(tabId, { updateHash = true } = {}) {
  const id = FOCUS_TABS.includes(tabId) ? tabId : "playlog";
  const switching = activeFocusTab !== id;
  if (switching) {
    saveFocusTabScroll(activeFocusTab);
  }
  for (const pane of document.querySelectorAll("[data-focus-pane]")) {
    const active = pane.dataset.focusPane === id;
    pane.hidden = !active;
  }
  for (const tab of document.querySelectorAll(".focus-tab")) {
    const active = tab.dataset.focusTab === id;
    tab.setAttribute("aria-selected", active ? "true" : "false");
    tab.tabIndex = active ? 0 : -1;
  }
  if (updateHash) {
    const next = `#${id}`;
    if (location.hash !== next) {
      history.replaceState(null, "", next);
    }
  }
  closeAppMenu();
  activeFocusTab = id;
  requestAnimationFrame(() => {
    syncFocusTabsHeightVar();
    if (switching) {
      restoreFocusTabScroll(id);
    }
    if (id === "playlog") {
      updatePlaylogStickyMetrics();
      syncPlaylogCurrentStuck();
    }
    syncFocusScrollHomeBtn();
  });
}

function applyLocationHash() {
  const raw = (location.hash || "").replace(/^#/, "");
  if (FOCUS_TABS.includes(raw)) {
    setFocusTab(raw, { updateHash: false });
    return;
  }
  if (SCROLL_HASHES.has(raw)) {
    if (raw === "player") {
      requestAnimationFrame(() => jumpFocusScrollHome());
    }
    return;
  }
  if (!raw) {
    setFocusTab("playlog", { updateHash: false });
  }
}

function initFocusTabs() {
  const tablist = document.querySelector(".focus-tabs");
  if (!tablist) return;
  tablist.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-focus-tab]");
    if (!tab || !tablist.contains(tab)) return;
    event.preventDefault();
    const id = tab.dataset.focusTab;
    // Re-click active tab → same as ⌃ / #player (pane home + expand player).
    if (id === activeFocusTab) {
      jumpFocusScrollHome();
      return;
    }
    setFocusTab(id);
  });
  tablist.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const tabs = [...tablist.querySelectorAll(".focus-tab")];
    const current = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
    if (current < 0) return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 1 : -1;
    const next = tabs[(current + delta + tabs.length) % tabs.length];
    next?.focus();
    if (next?.dataset.focusTab) setFocusTab(next.dataset.focusTab);
  });
  window.addEventListener("hashchange", () => applyLocationHash());
  applyLocationHash();
}

function initAppMenu() {
  const menu = document.querySelector(".app-menu");
  if (!menu) return;
  menu.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (!link || !menu.contains(link)) return;
    const href = link.getAttribute("href") || "";
    if (href.startsWith("#")) {
      const id = href.slice(1);
      if (FOCUS_TABS.includes(id)) {
        event.preventDefault();
        setFocusTab(id);
        return;
      }
      if (SCROLL_HASHES.has(id)) {
        event.preventDefault();
        closeAppMenu();
        history.replaceState(null, "", href);
        if (id === "player") {
          jumpFocusScrollHome();
        }
      }
    } else {
      closeAppMenu();
    }
  });
  document.addEventListener("click", (event) => {
    if (!menu.open) return;
    if (menu.contains(event.target)) return;
    closeAppMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAppMenu();
  });
}

function updateStatusPeersChrome() {
  const countEl = document.getElementById("peer-count");
  const mid = document.getElementById("status-peers");
  if (countEl) countEl.textContent = String(peersCache.length);
  if (!mid) return;
  const device =
    document.getElementById("device-name")?.textContent?.trim() || "device";
  const version =
    document.getElementById("health")?.textContent?.trim() || "";
  const names = peersCache.map((p) => p.name).filter(Boolean);
  const peerPart = names.length
    ? `${peersCache.length} peer${peersCache.length === 1 ? "" : "s"}: ${names.join(", ")}`
    : "0 peers";
  mid.title = [device, version, `⇄ ${peerPart}`].filter(Boolean).join(" ");
}

function updateStatusCacheChrome(summary) {
  const count = Number(summary?.count) || 0;
  const duration = formatDuration(summary?.duration_seconds || 0);
  const size = formatBytes(summary?.size_bytes || 0);
  const countEl = document.getElementById("cache-count");
  const durationEl = document.getElementById("cache-duration");
  const sizeEl = document.getElementById("cache-size");
  const wrap = document.getElementById("status-cache");
  if (countEl) countEl.textContent = count > 0 ? `${count} ♪` : "0 ♪";
  if (durationEl) durationEl.textContent = count > 0 ? duration : "0:00";
  if (sizeEl) sizeEl.textContent = count > 0 ? size : "0 B";
  if (wrap) {
    wrap.title =
      count > 0
        ? `${count} ♪ · ${duration} · ${size}`
        : "No cached audio";
  }
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

function intentMetaSep() {
  const sep = document.createElement("span");
  sep.className = "intent-meta-sep";
  sep.setAttribute("aria-hidden", "true");
  sep.textContent = "|";
  return sep;
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
 * Platform icon link to an artist or release page (catalog + player + playlog).
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
 * Shared create/edit intent composer: short name + ✓×, then one filter line
 * (tags | artists | sources | rating blocks) with rating click toggling the chance grid.
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

  const filterLine = document.createElement("div");
  filterLine.className = "intent-form-filter-line";

  const tagsMount = document.createElement("div");
  tagsMount.className = "tag-editor";
  tagsMount.setAttribute("aria-label", "Intent filter tags");
  tagsMount.title =
    "— = untagged only (default). Add a tag to filter by tags. Clear — for no tag filter.";

  const artistsMount = document.createElement("div");
  artistsMount.className = "tag-editor";
  artistsMount.setAttribute("aria-label", "Intent artist filter");
  artistsMount.title =
    "Optional. Leave empty for no artist filter. Selected artists match by OR.";

  const platformsRoot = document.createElement("div");
  platformsRoot.className = "source-toggles";
  platformsRoot.setAttribute("role", "group");
  platformsRoot.setAttribute("aria-label", "Sources");
  platformsRoot.title =
    "Sources start on. Grey one out to exclude it. At least one must stay active.";
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

  const chancesToggle = document.createElement("button");
  chancesToggle.type = "button";
  chancesToggle.className = "intent-chances-toggle has-tip";
  chancesToggle.setAttribute("aria-expanded", "false");
  chancesToggle.setAttribute("aria-label", "Rating chances");
  chancesToggle.title = "Rating chances";

  const chancePanel = document.createElement("div");
  chancePanel.className = "intent-chances-panel";
  chancePanel.hidden = true;
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
  chancePanel.appendChild(chanceGrid);

  filterLine.appendChild(tagsMount);
  filterLine.appendChild(intentMetaSep());
  filterLine.appendChild(artistsMount);
  filterLine.appendChild(intentMetaSep());
  filterLine.appendChild(platformsRoot);
  filterLine.appendChild(intentMetaSep());
  filterLine.appendChild(chancesToggle);
  meta.appendChild(filterLine);
  meta.appendChild(chancePanel);
  root.appendChild(nameRow);
  root.appendChild(meta);

  const tagEditor = mountTagEditor(tagsMount, {
    tags:
      initial.tags != null ? initial.tags : [UNTAGGED_TAG],
    confirmRemove: false,
    untaggedSentinel: true,
    addLabel: "Filter tags",
    async onAdd() {},
    async onRemove() {},
  });
  const artistEditor = mountArtistEditor(artistsMount, {
    artists: [],
    confirmRemove: false,
    addLabel: "Filter artists",
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
    chancesToggle.textContent = formatChanceBlocksFromPct(chances);
    chancesToggle.removeAttribute("title");
    chancesToggle.classList.add("has-tip");
    chancesToggle.dataset.tip = formatChancePercentsFromPct(chances);
  }

  function setChancePanelOpen(open) {
    chancePanel.hidden = !open;
    chancesToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  chancesToggle.addEventListener("click", () => {
    setChancePanelOpen(chancePanel.hidden);
  });

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
    tagEditor.setTags(
      Array.isArray(next.tags) ? next.tags : [UNTAGGED_TAG],
    );
    artistEditor.setIds(next.artist_ids || []);
    writePlatforms(next.platforms || DEFAULT_INTENT_PLATFORMS);
    if (next.distribution) writeChances(chancesFromDist(next.distribution));
    else writeChances({ ...CHANCE_DEFAULTS });
    setChancePanelOpen(false);
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
      showNotice(
        `Rating chances must sum to 100% (got ${sumChances(values.chancePcts)})`,
        "warn",
      );
      return;
    }
    if (!values.platforms.length) {
      showNotice("Keep at least one source active", "warn");
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
      nameInput.focus({ preventScroll: true });
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
      tags: [UNTAGGED_TAG],
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
      try {
        const res = await fetch("/api/intents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(values),
        });
        const data = await res.json();
        if (!res.ok) {
          const detail = data.detail;
          showNotice(
            typeof detail === "string"
              ? detail
              : detail?.[0]?.msg || "Create intent failed",
            "error",
          );
          return;
        }
        const filling = data.fill_in_progress ? " · filling caches…" : "";
        showNotice(`Created “${data.intent.name}”${filling}`, "ok");
        collapseCreateForm();
        await refreshIntents({ force: true });
        await refreshFiles();
      } catch (err) {
        showNotice("Create intent request failed", "error");
        console.error(err);
      }
    },
    onCancel() {
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
    const version = data.version != null ? `v${data.version}` : "v?";
    if (el) {
      el.textContent = version;
      el.classList.toggle("is-degraded", !data.ok);
      el.title = data.ok ? `API ok (${version})` : `API degraded (${version})`;
    }
    if (nameEl) nameEl.textContent = data.device || "unknown";
    localDeviceId = data.device_id || null;
    currentMixId = data.current_mix_id || null;
    if (meteredToggle) {
      meteredToggle.checked = Boolean(data.metered);
    }
    applyTrustedPeersList(peersCache);
  } catch (err) {
    if (el) {
      el.textContent = "offline";
      el.classList.add("is-degraded");
      el.title = "API unreachable";
    }
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
  setPairSessionHint("");
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
    setPairSessionHint("");
    stopPairPoll();
    return;
  }
  pairCollapsible?.expand();
  cancelBtn.hidden = false;
  // Only poll while waiting on the other device's Confirm; host waiting
  // and other local transitions are pushed via pairing_session notices.
  if (session.state === "pending_confirm") {
    startPairPoll();
  } else {
    stopPairPoll();
  }
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
      showNotice(`Paired with ${data.peer.name}`, "ok");
      setPairSessionHint("");
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
  updateStatusPeersChrome();
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
        try {
          const res = await fetch(`/api/peers/${peer.id}/unpair`, {
            method: "POST",
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            const detail = data.detail;
            showNotice(
              typeof detail === "string"
                ? detail
                : detail?.[0]?.msg || "Unpair failed",
              "error",
            );
            return;
          }
          applyPeersPayload(data);
          showNotice(`Unpaired ${peer.name}`, "ok");
        } catch (err) {
          showNotice("Unpair request failed", "error");
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
  let pending = false;

  function paint() {
    const filled = current != null ? current : 0;
    root.dataset.stars = current != null ? String(current) : "";
    root.classList.toggle("is-pending", pending);
    root.replaceChildren();
    root.setAttribute(
      "aria-label",
      current != null ? `${current} of 5 stars` : "Unrated",
    );
    if (pending) {
      root.setAttribute("aria-busy", "true");
    } else {
      root.removeAttribute("aria-busy");
    }
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
        const previous = current;
        current = s;
        busy = true;
        pending = true;
        paint();
        try {
          await onRate(s);
          pending = false;
        } catch (err) {
          current = previous;
          pending = false;
          console.error(err);
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
      if (busy) return;
      current = value != null && value !== "" ? Number(value) : null;
      pending = false;
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
 * Shared annotate control kit (Rate, Tag, Reject confirm-click / Un-reject).
 * Used by Player, Playlog, and Catalog so later tickets edit one mount.
 *
 * Row mode (`surface` catalog|history): builds stars + reject chrome + tag editor.
 * Player mode (`surface` "player"): binds long-lived roots from index.html.
 *
 * @param {{
 *   surface: "catalog"|"playlog"|"player",
 *   mix?: { id: string, stars?: number|null, tags?: string[], rejected?: boolean, rejected_at?: string|null },
 *   starsRoot: HTMLElement,
 *   actionsRoot?: HTMLElement,
 *   tagRoot?: HTMLElement,
 *   rejectBtn?: HTMLElement,
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
 *   surface: "catalog"|"playlog",
 *   mix: { id: string, stars?: number|null, tags?: string[], rejected?: boolean, rejected_at?: string|null },
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
      void refreshAfterAnnotateMutation();
    },
  });

  const rejectClass =
    surface === "catalog" ? "catalog-reject" : "playlog-reject";
  const unRejectClass =
    surface === "catalog" ? "catalog-un-reject" : "playlog-un-reject";
  const rejectBtn = document.createElement("button");
  rejectBtn.type = "button";
  rejectBtn.className = rejectClass;
  const unRejectBtn = document.createElement("button");
  unRejectBtn.type = "button";
  unRejectBtn.className = unRejectClass;
  setSymbolButton(unRejectBtn, BTN.unreject, "Un-reject release");

  bindConfirmClick(rejectBtn, {
    idleSymbol: BTN.reject,
    idleLabel: "Reject release",
    armedSymbol: BTN.confirmDelete,
    armedLabel: "really reject?",
    stopPropagation: true,
    async onConfirm() {
      const row = actionsRoot.closest("tr");
      markRejectPending(mix.id, row);
      rejectBtn.hidden = true;
      rejectBtn.disabled = true;
      try {
        const res = await fetch(`/api/mixes/${mix.id}/reject`, {
          method: "POST",
        });
        if (!res.ok) {
          clearRejectPending(mix.id, { restore: true });
          rejectBtn.hidden = false;
          rejectBtn.disabled = false;
          return;
        }
        void refreshAfterAnnotateMutation().finally(() => {
          clearRejectPending(mix.id);
        });
      } catch (err) {
        clearRejectPending(mix.id, { restore: true });
        rejectBtn.hidden = false;
        rejectBtn.disabled = false;
        console.error(err);
      }
    },
  });

  syncRowAnnotateRejectButtons({
    rejectBtn,
    unRejectBtn,
    mix,
    allowUnreject,
  });

  if (allowUnreject) {
    unRejectBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const row = actionsRoot.closest("tr");
      markUnrejectPending(mix.id, row);
      unRejectBtn.hidden = true;
      unRejectBtn.disabled = true;
      try {
        const res = await fetch(`/api/mixes/${mix.id}/un-reject`, {
          method: "POST",
        });
        if (!res.ok) {
          clearUnrejectPending(mix.id, { restore: true });
          unRejectBtn.hidden = false;
          unRejectBtn.disabled = false;
          return;
        }
        clearSoftRejectTimer(mix.id);
        void refreshAfterAnnotateMutation({ intents: true }).finally(() => {
          clearUnrejectPending(mix.id);
        });
      } catch (err) {
        clearUnrejectPending(mix.id, { restore: true });
        unRejectBtn.hidden = false;
        unRejectBtn.disabled = false;
        console.error(err);
      }
    });
  } else {
    unRejectBtn.hidden = true;
  }

  actionsRoot.appendChild(rejectBtn);
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
        void refreshAfterAnnotateMutation();
      }
    },
    async onRemove(tag) {
      await handlers.onRemove(tag);
      if (refreshAfterTag) {
        void refreshAfterAnnotateMutation();
      }
    },
  });
  actionsRoot.appendChild(tagEditorRoot);

  return { starRating, tagEditor, rejectBtn, unRejectBtn };
}

/**
 * Visibility + Soft-window refresh for Catalog / Playlog reject chrome.
 */
function syncRowAnnotateRejectButtons({
  rejectBtn,
  unRejectBtn,
  mix,
  allowUnreject = true,
}) {
  const rejectPending = isRejectPending(mix.id);
  const unrejectPending = isUnrejectPending(mix.id);
  if (rejectPending || (mix.rejected && !unrejectPending)) {
    rejectBtn.hidden = true;
    if (unRejectBtn) {
      unRejectBtn.hidden = !allowUnreject || rejectPending || unrejectPending;
    }
    if (!rejectPending && isSoftRejected(mix)) {
      scheduleSoftRejectRefresh(mix.id, mix.rejected_at);
    } else {
      clearSoftRejectTimer(mix.id);
    }
  } else {
    rejectBtn.hidden = unrejectPending;
    if (unRejectBtn) unRejectBtn.hidden = true;
    clearSoftRejectTimer(mix.id);
  }
}

/**
 * Player annotate kit: long-lived stars / tags / Reject confirm (no Un-reject).
 * @param {{
 *   starsRoot: HTMLElement,
 *   tagRoot: HTMLElement,
 *   rejectBtn: HTMLElement,
 *   getMixId: () => string|null,
 *   onRate: (stars: number) => void|Promise<void>,
 * }} options
 */
function mountPlayerAnnotateKit({
  starsRoot,
  tagRoot,
  rejectBtn,
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

  bindConfirmClick(rejectBtn, {
    idleSymbol: BTN.reject,
    idleLabel: "Reject release",
    armedSymbol: BTN.confirmDelete,
    armedLabel: "really reject?",
    async onConfirm() {
      const mixId = getMixId();
      if (!mixId) {
        showNotice("Nothing to reject", "warn");
        return;
      }
      markRejectPending(mixId);
      rejectBtn.hidden = true;
      rejectBtn.disabled = true;
      try {
        const res = await fetch(`/api/mixes/${mixId}/reject`, {
          method: "POST",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          clearRejectPending(mixId, { restore: true });
          rejectBtn.hidden = false;
          rejectBtn.disabled = false;
          showNotice(data.detail || "Reject failed", "error");
          return;
        }
        showNotice("Rejected", "ok");
        void refreshAfterAnnotateMutation().finally(() => {
          clearRejectPending(mixId);
        });
      } catch (err) {
        clearRejectPending(mixId, { restore: true });
        rejectBtn.hidden = false;
        rejectBtn.disabled = false;
        showNotice("Reject request failed", "error");
        console.error(err);
      }
    },
  });

  function updateRejectControls(data) {
    if (!rejectBtn) return;
    if (data.rejected) {
      rejectBtn.hidden = true;
      if (isSoftRejected(data) && data.current_mix_id) {
        scheduleSoftRejectRefresh(data.current_mix_id, data.rejected_at);
      }
    } else {
      rejectBtn.hidden = false;
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
let playerUiTickTimer = null;
/** Wall-clock sync for local seekbar extrapolation between server polls. */
let playerPositionSyncedAt = 0;
let playerPositionSyncedSeconds = 0;
let playerDurationSeconds = 0;
let playerLocalPlaying = false;
let playerSeekTracks = [];
let playerSeekArtist = "";
/** Stable key for current marks layout; skip DOM rebuild while unchanged. */
let playerSeekMarksKey = "";
/** Track index currently highlighted (−1 = none). Survives poll refreshes. */
let playerSeekHotIndex = -1;
/** Playing track index (−1 = none). Separate from ephemeral hover/drag is-hot. */
let playerSeekCurrentIndex = -1;
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

function extrapolatedPlayerPosition() {
  if (!playerLocalPlaying || playerDurationSeconds <= 0) {
    return playerPositionSyncedSeconds;
  }
  const elapsed = (Date.now() - playerPositionSyncedAt) / 1000;
  return Math.max(
    0,
    Math.min(playerDurationSeconds, playerPositionSyncedSeconds + elapsed),
  );
}

function tickPlayerUi() {
  if (!playerLocalPlaying || playerSeekDragging) return;
  const pos = extrapolatedPlayerPosition();
  lastKnownPositionSeconds = pos;
  // Position/clock only — do not call updateSeekBar (that rebuilds marks and
  // would clear album titles when tracks are omitted).
  const seekbar = document.getElementById("player-seekbar");
  const currentEl = document.getElementById("player-time-current");
  if (!seekbar || !currentEl) return;
  const duration = playerDurationSeconds;
  const clamped = Math.max(0, Math.min(duration, Math.round(pos)));
  seekbar.value = String(clamped);
  syncSeekProgress(seekbar);
  currentEl.textContent = formatClock(clamped);
  syncPlayerCurrentTrackFromPosition(pos);
  // 5‑minute playhead heartbeat (throttled inside maybeCommitPlayhead).
  void maybeCommitPlayhead(true);
}

/** Local seekbar clock while playing; transport state comes from player notices. */
function setPlayerLocalClock(playing) {
  playerLocalPlaying = Boolean(playing);
  if (playing) {
    if (playerUiTickTimer == null) {
      playerUiTickTimer = setInterval(() => {
        tickPlayerUi();
      }, PLAYER_UI_TICK_MS);
    }
  } else if (playerUiTickTimer != null) {
    clearInterval(playerUiTickTimer);
    playerUiTickTimer = null;
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
  if (marksEl) {
    for (const el of marksEl.querySelectorAll(
      ".player-seek-section, .player-seek-section-fill, .player-seek-label",
    )) {
      const hot = Number(el.dataset.trackIndex) === index;
      el.classList.toggle("is-hot", hot);
    }
  }
  // Collapsed chrome: swap compact title for the hovered segment.
  syncPlayerCurrentTrackChrome();
}

function clearSeekTrackHighlight() {
  playerSeekHotIndex = -1;
  const marksEl = document.getElementById("player-seek-marks");
  if (marksEl) {
    for (const el of marksEl.querySelectorAll(
      ".player-seek-section.is-hot, .player-seek-section-fill.is-hot, .player-seek-label.is-hot",
    )) {
      el.classList.remove("is-hot");
    }
  }
  syncPlayerCurrentTrackChrome();
}

/** Persist playing-track accent; does not clear ephemeral is-hot. */
function setSeekTrackCurrent(index) {
  const next = Number.isFinite(index) ? Number(index) : -1;
  playerSeekCurrentIndex = next;
  const marksEl = document.getElementById("player-seek-marks");
  if (marksEl) {
    for (const el of marksEl.querySelectorAll(
      ".player-seek-section, .player-seek-section-fill, .player-seek-label",
    )) {
      const current = Number(el.dataset.trackIndex) === next;
      el.classList.toggle("is-current", current);
    }
  }
  syncPlayerCurrentTrackChrome();
}

function syncPlayerCurrentTrackFromPosition(seconds) {
  if (playerSeekTracks.length < 2) {
    setSeekTrackCurrent(-1);
    return;
  }
  setSeekTrackCurrent(trackIndexAtTimelineSeconds(playerSeekTracks, seconds));
}

/** Compact title under stars/tags; CSS crossfades it in as angled labels fade.
 * While a seek segment is hot, preview that title in place of the playing track. */
function syncPlayerCurrentTrackChrome() {
  const el = document.getElementById("player-current-track");
  if (!el) return;
  if (playerSeekTracks.length < 2) {
    el.hidden = true;
    el.textContent = "";
    el.classList.remove("is-preview");
    return;
  }
  const previewing = playerSeekHotIndex >= 0;
  const index = previewing ? playerSeekHotIndex : playerSeekCurrentIndex;
  if (index < 0 || index >= playerSeekTracks.length) {
    el.hidden = true;
    el.textContent = "";
    el.classList.remove("is-preview");
    return;
  }
  const track = playerSeekTracks[index];
  const title =
    displayTrackTitle(track?.title, playerSeekArtist) || `Track ${index + 1}`;
  el.textContent = title;
  el.hidden = false;
  el.classList.toggle(
    "is-preview",
    previewing && playerSeekHotIndex !== playerSeekCurrentIndex,
  );
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
  syncPlayerCurrentTrackFromPosition(position);
  try {
    const res = await fetch("/api/player/seek", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_seconds: position }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showNotice(data.detail || "Seek failed", "error");
      await refreshPlayer();
      return false;
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
    showNotice("Seek request failed", "error");
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
const PLAYER_COVER_MAX_REM = 12.5;
/** Target share of now-row width for the cover (title always stays beside). */
const PLAYER_COVER_SIDE_FRACTION = 0.35;
/** Soft scroll ranges (px): cover+annotate, then seek-label fade — fold before rows move. */
const PLAYER_COLLAPSE_COVER_RANGE_PX = 72;
const PLAYER_COLLAPSE_LABEL_RANGE_PX = 96;
/** Scroll delta consumed to fully soft-collapse the player (fold-first). */
const PLAYER_COLLAPSE_FULL_RANGE_PX =
  PLAYER_COLLAPSE_COVER_RANGE_PX + PLAYER_COLLAPSE_LABEL_RANGE_PX;
/** @type {HTMLElement | null} */
let playerCollapseSpacer = null;
let playerCollapseRaf = 0;
/**
 * Soft-collapse depth (px). Fold-first: scroll/wheel delta collapses the player
 * while the pane stays at its home top; only then does table content move.
 * Kept across tab switches until the active pane is scrolled.
 */
let playerCollapseScrollPx = 0;
/**
 * Playlog pane scrollTop where offset −2 sits under thead (home top; player fully shown).
 */
let playlogCollapseOriginScrollTop = 0;
let playlogCollapseOriginReady = false;
/** Last pane scrollTop used for fold-first delta accounting. */
let paneCollapseLastScrollTop = 0;
/** Skip collapse sync while restoring a tab’s pane scrollTop. */
let suppressPlayerCollapseFromPane = false;
/** Expanded player height captured while unstuck (spacer baseline). */
let playerExpandedHeightPx = 0;
/** Last soft collapse key to limit chrome work. */
let playerCollapseKey = "";
/** Last focus-tabs / toolbar heights written (avoid thrash). */
let focusTabsHeightPx = -1;
let focusToolbarHeightPx = -1;

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

function playerRootFontPx() {
  return (
    Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
  );
}

/**
 * Natural cover size with title always beside (ellipsis if tight). Sets
 * --player-cover-natural; CSS multiplies by #player --player-cover-scale.
 * Frozen while sticky-collapsing so mid-scroll reflow doesn’t snap.
 */
function syncPlayerNowStack() {
  const player = document.getElementById("player");
  const row = document.querySelector("#player .player-now-row");
  const cover = document.getElementById("player-cover");
  const title = document.getElementById("player-now");
  if (!row || !title) return;
  row.classList.remove("is-stacked");
  const coverVisible = Boolean(cover && !cover.hidden);
  if (!coverVisible) {
    row.style.removeProperty("--player-cover-natural");
    row.style.removeProperty("--player-cover-size");
    return;
  }
  // Keep natural size stable while soft-collapsing under sticky.
  if (
    player?.classList.contains("is-stuck") &&
    row.style.getPropertyValue("--player-cover-natural")
  ) {
    return;
  }
  const rootFont = playerRootFontPx();
  const pxToRem = (px) => px / rootFont;
  const remToPx = (rem) => rem * rootFont;
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

  const styles = getComputedStyle(row);
  const gap = Number.parseFloat(styles.columnGap || styles.gap) || 0;
  const rowWidth = row.clientWidth;
  const titleNeeds = measurePlayerTitleIntrinsicWidth(title);
  // Floor cover to title + rating/tags height so small clients don’t shrink
  // the art below the chrome stack beside it. Omit meta only when narrow
  // soft-fold has collapsed annotate (wider UI keeps meta in the floor).
  const meta = row.querySelector(".player-meta");
  const annotateCollapsed = player?.classList.contains("is-annotate-collapsed");
  const titleMarginBottom =
    Number.parseFloat(getComputedStyle(title).marginBottom) || 0;
  const metaHeight =
    !annotateCollapsed && meta ? meta.getBoundingClientRect().height : 0;
  const chromeMinPx =
    title.getBoundingClientRect().height + titleMarginBottom + metaHeight;
  const minRem = clamp(
    Math.max(PLAYER_COVER_MIN_REM, pxToRem(chromeMinPx)),
    PLAYER_COVER_MIN_REM,
    PLAYER_COVER_MAX_REM,
  );
  const desiredRem = clamp(
    pxToRem(rowWidth * PLAYER_COVER_SIDE_FRACTION),
    minRem,
    PLAYER_COVER_MAX_REM,
  );
  const maxSidePx = rowWidth - gap - titleNeeds;
  const minPx = remToPx(minRem);
  // Always beside: shrink toward min if the title needs room, else ellipsis.
  const sizeRem = clamp(
    maxSidePx >= minPx - 0.5
      ? Math.min(desiredRem, pxToRem(maxSidePx))
      : minRem,
    minRem,
    PLAYER_COVER_MAX_REM,
  );
  row.style.setProperty("--player-cover-natural", `${sizeRem}rem`);
}

function syncPlayerChrome() {
  syncPlayerNowStack();
  syncPlayerSeekClipRise();
  syncPlayerStickyHeightVar();
}

/** Publish live player height (flex shell chrome / scroll-padding). */
function syncPlayerStickyHeightVar() {
  const player = document.getElementById("player");
  const root = document.documentElement;
  if (!player) {
    root.style.setProperty("--player-sticky-height", "0px");
    return;
  }
  const h = Math.round(player.getBoundingClientRect().height);
  root.style.setProperty("--player-sticky-height", `${h}px`);
}

/** Read collapse depth from the shared fold-first value (not per-tab restore). */
function activeFocusPaneScrollTop() {
  return playerCollapseScrollPx;
}

/** Home scrollTop for a tab: Playlog −2 origin, else 0. */
function paneScrollHomeTop(tabId) {
  if (tabId === "playlog" && playlogCollapseOriginReady) {
    return playlogCollapseOriginScrollTop;
  }
  return 0;
}

function setPlayerCollapseDepthPx(depthPx) {
  playerCollapseScrollPx = Math.min(
    PLAYER_COLLAPSE_FULL_RANGE_PX,
    Math.max(0, depthPx),
  );
  schedulePlayerCollapse();
}

/** Fully expand the player (e.g. land on Playlog −2). */
function expandPlayerCollapseFully() {
  setPlayerCollapseDepthPx(0);
}

function wheelDeltaYPx(event) {
  let dy = event.deltaY;
  if (event.deltaMode === 1) dy *= 16;
  else if (event.deltaMode === 2) dy *= window.innerHeight || 800;
  return dy;
}

/**
 * Fold-first wheel accounting for a pane scrollport. Returns true when the
 * delta was consumed by player collapse/expand (caller should not scroll).
 * @param {HTMLElement} pane
 * @param {WheelEvent} event
 */
function applyFocusPaneWheelFold(pane, event) {
  if (suppressPlayerCollapseFromPane) return false;
  const dy = wheelDeltaYPx(event);
  if (!dy) return false;

  const home = paneScrollHomeTop(activeFocusTab);
  const atHome = pane.scrollTop <= home + 1;

  if (dy > 0 && playerCollapseScrollPx < PLAYER_COLLAPSE_FULL_RANGE_PX) {
    event.preventDefault();
    setPlayerCollapseDepthPx(playerCollapseScrollPx + dy);
    paneCollapseLastScrollTop = pane.scrollTop;
    return true;
  }

  if (dy < 0 && atHome && playerCollapseScrollPx > 0) {
    event.preventDefault();
    setPlayerCollapseDepthPx(playerCollapseScrollPx + dy);
    paneCollapseLastScrollTop = pane.scrollTop;
    return true;
  }

  return false;
}

/**
 * Wheel fold-first: collapse/expand the player before the table scrolls, so the
 * first row stays put while more rows appear as the player shrinks.
 */
function onFocusPaneWheelFold(event) {
  const pane = event.currentTarget;
  if (!(pane instanceof HTMLElement)) return;
  if (pane !== focusPaneScrollEl(activeFocusTab)) return;
  applyFocusPaneWheelFold(pane, event);
}

/**
 * ⌃ overlay sits above the scrollport — forward wheel so the table still
 * scrolls (and fold-first still runs) while the chip stays clickable.
 */
function onFocusScrollHomeWheel(event) {
  const pane = focusPaneScrollEl(activeFocusTab);
  if (!pane) return;
  if (applyFocusPaneWheelFold(pane, event)) return;
  const dy = wheelDeltaYPx(event);
  if (!dy) return;
  event.preventDefault();
  pane.scrollTop += dy;
}

/**
 * Scroll/touch fold-first: convert downward scroll into collapse while pinning
 * the pane at home until the player is fully folded.
 */
function syncPlayerCollapseFromActivePane() {
  if (suppressPlayerCollapseFromPane) return;
  const el = focusPaneScrollEl(activeFocusTab);
  if (!el) return;

  const home = paneScrollHomeTop(activeFocusTab);
  const top = el.scrollTop;
  const delta = top - paneCollapseLastScrollTop;

  if (delta > 0 && playerCollapseScrollPx < PLAYER_COLLAPSE_FULL_RANGE_PX) {
    const room = PLAYER_COLLAPSE_FULL_RANGE_PX - playerCollapseScrollPx;
    const fold = Math.min(delta, room);
    setPlayerCollapseDepthPx(playerCollapseScrollPx + fold);
    // Undo the part of the scroll that folded the player (keep first row fixed).
    const nextTop = top - fold;
    if (Math.abs(el.scrollTop - nextTop) >= 0.5) {
      el.scrollTop = nextTop;
    }
    paneCollapseLastScrollTop = el.scrollTop;
    return;
  }

  if (
    delta < 0 &&
    top <= home + 1 &&
    playerCollapseScrollPx > 0 &&
    paneCollapseLastScrollTop <= home + 1
  ) {
    // Rare: scroll engine reported upward delta while pinned at home.
    setPlayerCollapseDepthPx(playerCollapseScrollPx + delta);
    el.scrollTop = home;
    paneCollapseLastScrollTop = home;
    return;
  }

  // Past home with content scrolling: keep player fully collapsed.
  if (top > home + 1 && playerCollapseScrollPx < PLAYER_COLLAPSE_FULL_RANGE_PX) {
    setPlayerCollapseDepthPx(PLAYER_COLLAPSE_FULL_RANGE_PX);
  }

  paneCollapseLastScrollTop = el.scrollTop;
}

/** Spacer after #player (kept at 0 height in the flex shell). */
function ensurePlayerCollapseSpacer() {
  const player = document.getElementById("player");
  if (!player || !player.parentNode) return null;
  if (playerCollapseSpacer?.isConnected) return playerCollapseSpacer;
  const el = document.createElement("div");
  el.className = "player-collapse-spacer";
  el.setAttribute("aria-hidden", "true");
  player.parentNode.insertBefore(el, player.nextSibling);
  playerCollapseSpacer = el;
  return el;
}

function clamp01(t) {
  return Math.min(1, Math.max(0, t));
}

function smoothstep01(t) {
  const x = clamp01(t);
  return x * x * (3 - 2 * x);
}

/**
 * Soft-collapse from the active focus pane scrollTop (sole scrollport):
 * cover scale 1→0.5 (+ narrow annotate 1→0), then label factor 1→0.
 */
function syncPlayerCollapse() {
  const player = document.getElementById("player");
  if (!player) return;

  const collapseDepth = Math.min(
    PLAYER_COLLAPSE_FULL_RANGE_PX,
    Math.max(0, activeFocusPaneScrollTop()),
  );
  const stuck = collapseDepth > 0;

  let coverScale = 1;
  let annotateFactor = 1;
  let labelFactor = 1;
  if (collapseDepth > 0) {
    const coverT = smoothstep01(collapseDepth / PLAYER_COLLAPSE_COVER_RANGE_PX);
    coverScale = 1 - 0.5 * coverT;
    // Narrow annotate lands with cover shrink; seek titles fade in the next phase.
    annotateFactor = 1 - coverT;
    const labelT = smoothstep01(
      (collapseDepth - PLAYER_COLLAPSE_COVER_RANGE_PX) /
        PLAYER_COLLAPSE_LABEL_RANGE_PX,
    );
    labelFactor = 1 - labelT;
  }

  player.style.setProperty("--player-cover-scale", coverScale.toFixed(4));
  player.style.setProperty("--player-annotate-factor", annotateFactor.toFixed(4));
  player.style.setProperty("--player-label-factor", labelFactor.toFixed(4));
  player.classList.toggle("is-stuck", stuck);
  // Annotate fold only on narrow layouts (larger UI / cover keeps Rate/Reject/Tag).
  const narrowAnnotateFold = window.matchMedia("(max-width: 40rem)").matches;
  const annotateCollapsed = narrowAnnotateFold && annotateFactor < 0.05;
  player.classList.toggle("is-annotate-collapsed", annotateCollapsed);
  player.classList.remove(
    "is-beside",
    "is-labels-collapsed",
    "is-compact-cover",
    "is-compact-no-labels",
  );

  const meta = player.querySelector(".player-meta");
  if (meta) {
    if (annotateCollapsed) {
      meta.setAttribute("aria-hidden", "true");
      meta.inert = true;
    } else {
      meta.removeAttribute("aria-hidden");
      meta.inert = false;
    }
  }

  // Keep collapse spacer at 0 — flex shell absorbs player height changes.
  const spacer = playerCollapseSpacer;
  if (spacer?.isConnected) spacer.style.height = "0px";
  if (!stuck) {
    playerExpandedHeightPx = Math.round(player.getBoundingClientRect().height);
  }

  const key = `${stuck ? 1 : 0}:${coverScale.toFixed(3)}:${annotateFactor.toFixed(3)}:${labelFactor.toFixed(3)}`;
  if (key === playerCollapseKey) {
    syncPlayerStickyHeightVar();
    syncFocusScrollHomeBtn();
    return;
  }
  playerCollapseKey = key;
  syncPlayerStickyHeightVar();
  syncFocusTabsHeightVar();
  syncFocusScrollHomeBtn();
}

function schedulePlayerCollapse() {
  if (playerCollapseRaf) return;
  playerCollapseRaf = requestAnimationFrame(() => {
    playerCollapseRaf = 0;
    syncPlayerCollapse();
  });
}

/** @type {HTMLButtonElement | null} */
let focusScrollHomeBtn = null;

/** True when active pane is past home or the player is soft-collapsed. */
function focusScrollHomeNeeded() {
  const el = focusPaneScrollEl(activeFocusTab);
  if (!el) return false;
  if (playerCollapseScrollPx > 0) return true;
  return el.scrollTop > paneScrollHomeTop(activeFocusTab) + 1;
}

/** Jump active pane to home scroll and fully expand the player. */
function jumpFocusScrollHome() {
  const el = focusPaneScrollEl(activeFocusTab);
  if (!el) return;
  const home = paneScrollHomeTop(activeFocusTab);
  suppressPlayerCollapseFromPane = true;
  try {
    el.scrollTop = home;
    paneCollapseLastScrollTop = home;
    expandPlayerCollapseFully();
    saveFocusTabScroll(activeFocusTab);
    if (activeFocusTab === "playlog") {
      syncPlaylogCurrentStuck();
    }
  } finally {
    suppressPlayerCollapseFromPane = false;
  }
  syncFocusScrollHomeBtn();
}

/** ⌃ chip: same as menu Player / #player. */
function onFocusScrollHomeClick(event) {
  event.preventDefault();
  jumpFocusScrollHome();
}

/**
 * Create/reparent the shared ⌃ chip as a bottom-center overlay on the active
 * table scrollport (same grid cell; no layout space). Mini face mimics player
 * cover + seek.
 */
function ensureFocusScrollHomeBtn() {
  let btn = focusScrollHomeBtn;
  if (!btn) {
    btn = document.createElement("button");
    btn.type = "button";
    btn.className = "focus-scroll-home-btn symbol-btn";
    btn.hidden = true;
    btn.setAttribute("aria-label", "Scroll to top");
    btn.dataset.tip = "Scroll to top";

    const face = document.createElement("span");
    face.className = "focus-scroll-home-face";
    face.setAttribute("aria-hidden", "true");

    const row = document.createElement("span");
    row.className = "focus-scroll-home-row";

    const cover = document.createElement("span");
    cover.className = "focus-scroll-home-cover";

    const caret = document.createElement("span");
    caret.className = "focus-scroll-home-caret";
    caret.textContent = BTN.scrollHome;

    const seek = document.createElement("span");
    seek.className = "focus-scroll-home-seek";

    row.append(cover, caret);
    face.append(row, seek);
    btn.appendChild(face);
    btn.addEventListener("click", onFocusScrollHomeClick);
    btn.addEventListener("wheel", onFocusScrollHomeWheel, { passive: false });
    focusScrollHomeBtn = btn;
  }
  const pane = document.querySelector(`[data-focus-pane="${activeFocusTab}"]`);
  if (pane && btn.parentElement !== pane) {
    pane.appendChild(btn);
  }
  return btn;
}

/** Show/hide ⌃ from active pane scroll + player collapse depth. */
function syncFocusScrollHomeBtn() {
  const btn = ensureFocusScrollHomeBtn();
  btn.hidden = !focusScrollHomeNeeded();
}

/** Publish focus-tabs (+ active toolbar) height for layout metrics. */
function syncFocusTabsHeightVar() {
  const root = document.documentElement;
  const tabs = document.querySelector("#focus .focus-tabs");
  const toolbar = document.querySelector(
    "#focus .focus-pane:not([hidden]) .focus-toolbar",
  );

  const tabsH = tabs ? Math.round(tabs.getBoundingClientRect().height) : 0;
  if (tabsH !== focusTabsHeightPx) {
    focusTabsHeightPx = tabsH;
    root.style.setProperty("--focus-tabs-height", `${tabsH}px`);
  }

  const toolbarH = toolbar
    ? Math.round(toolbar.getBoundingClientRect().height)
    : 0;
  if (toolbarH !== focusToolbarHeightPx) {
    focusToolbarHeightPx = toolbarH;
    root.style.setProperty("--focus-toolbar-height", `${toolbarH}px`);
  }
}

/** Viewport Y where sticky shell chrome ends (status + player + tabs + toolbar). */
function focusChromeTopPx() {
  const root = document.documentElement;
  const styles = getComputedStyle(root);
  const parse = (name, fallback) => {
    const raw = styles.getPropertyValue(name).trim();
    if (!raw) return fallback;
    if (raw.endsWith("rem")) {
      return (Number.parseFloat(raw) || 0) * playerRootFontPx();
    }
    return Number.parseFloat(raw) || fallback;
  };
  return (
    parse("--status-bar-height", 2.75 * playerRootFontPx()) +
    parse("--player-sticky-height", 0) +
    parse("--focus-tabs-height", 0) +
    parse("--focus-toolbar-height", 0)
  );
}

/** Current soft-collapse depth from the active pane scrollTop. */
function playerCollapseDepthPx() {
  return Math.min(
    PLAYER_COLLAPSE_FULL_RANGE_PX,
    Math.max(0, activeFocusPaneScrollTop()),
  );
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
    setSeekTrackCurrent(-1);
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
    if (playerSeekCurrentIndex >= 0) {
      setSeekTrackCurrent(playerSeekCurrentIndex);
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
  if (playerSeekCurrentIndex >= 0) {
    setSeekTrackCurrent(playerSeekCurrentIndex);
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
  syncPlayerCurrentTrackFromPosition(displayPos);
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

function clearSoftRejectTimer(mixId) {
  const handle = softRejectTimers.get(mixId);
  if (handle != null) {
    clearTimeout(handle);
    softRejectTimers.delete(mixId);
  }
}

function scheduleSoftRejectRefresh(mixId, rejectedAtIso) {
  clearSoftRejectTimer(mixId);
  if (!rejectedAtIso) return;
  const at = Date.parse(rejectedAtIso);
  if (Number.isNaN(at)) return;
  const delay = Math.max(0, at + SOFT_REJECT_MS - Date.now()) + 50;
  const handle = setTimeout(async () => {
    softRejectTimers.delete(mixId);
    await refreshAfterAnnotateMutation();
  }, delay);
  softRejectTimers.set(mixId, handle);
}

/**
 * Case-insensitive substring match across non-empty string parts.
 * Empty / whitespace-only query matches everything.
 * @param {string} query
 * @param {...(string|null|undefined)} parts
 */
function matchesNameFilter(query, ...parts) {
  const needle = String(query || "")
    .trim()
    .toLowerCase();
  if (!needle) return true;
  return parts.some((part) =>
    String(part || "")
      .toLowerCase()
      .includes(needle),
  );
}

function mixMatchesCatalogFilters(mix) {
  if (!showRejectedCatalog && isHardRejected(mix)) return false;
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
  if (!matchesNameFilter(catalogNameFilter, mix.title, mix.artist)) {
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
  const nameInput = document.getElementById("catalog-name-filter");
  if (nameInput) {
    catalogNameFilter = String(nameInput.value || "");
    nameInput.addEventListener("input", () => {
      catalogNameFilter = String(nameInput.value || "");
      if (catalogNameFilterTimer != null) clearTimeout(catalogNameFilterTimer);
      catalogNameFilterTimer = setTimeout(() => {
        catalogNameFilterTimer = null;
        void refreshAffectedSurfaces(["mixes"], { force: true });
      }, NAME_FILTER_DEBOUNCE_MS);
    });
  }

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
      await refreshAffectedSurfaces(["mixes"], { force: true });
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
        await refreshAffectedSurfaces(["mixes"], { force: true });
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
      addLabel: "Filter tags",
      getCatalogTags: () => catalogTagsCache,
      async onAdd(tag) {
        catalogFilterTags = [...catalogFilterTags, tag];
        await refreshAffectedSurfaces(["mixes"], { force: true });
      },
      async onRemove(tag) {
        catalogFilterTags = catalogFilterTags.filter((t) => t !== tag);
        await refreshAffectedSurfaces(["mixes"], { force: true });
      },
    });
    tagsRoot.setAttribute("aria-label", "Catalog filter tags");
  }
}

function resetCatalogFilters() {
  catalogFilterPlatforms = [];
  catalogFilterMinStars = null;
  catalogFilterTags = [];
  catalogNameFilter = "";
  showRejectedCatalog = false;
  syncRejectedToggle(document.getElementById("catalog-show-rejected"), false);
  const nameInput = document.getElementById("catalog-name-filter");
  if (nameInput) nameInput.value = "";
  if (catalogNameFilterTimer != null) {
    clearTimeout(catalogNameFilterTimer);
    catalogNameFilterTimer = null;
  }
  const sourcesRoot = document.getElementById("catalog-source-filters");
  if (sourcesRoot) {
    for (const btn of sourcesRoot.querySelectorAll(".source-toggle")) {
      btn.setAttribute("aria-pressed", "false");
    }
  }
  catalogStarFilter?.setFloor(null);
  catalogTagFilterEditor?.setTags([]);
}

/**
 * Intent list toolbar filters: tags (AND), artists (OR), sources (OR).
 * Empty selection = no constraint for that dimension.
 * @param {{ id?: string, tags?: string[], artist_ids?: string[], platforms?: string[] }} intent
 */
function intentMatchesListFilters(intent) {
  if (editingIntentId && intent.id === editingIntentId) return true;
  if (
    intentListFilterTags.length &&
    !intentListFilterTags.every((t) => (intent.tags || []).includes(t))
  ) {
    return false;
  }
  if (intentListFilterArtistIds.length) {
    const ids = new Set((intent.artist_ids || []).map(String));
    if (!intentListFilterArtistIds.some((id) => ids.has(String(id)))) {
      return false;
    }
  }
  if (intentListFilterPlatforms.length) {
    const platforms = new Set(intent.platforms || []);
    if (!intentListFilterPlatforms.some((p) => platforms.has(p))) {
      return false;
    }
  }
  if (!matchesNameFilter(intentNameFilter, intent.name)) {
    return false;
  }
  return true;
}

function mountIntentListFilters() {
  const nameInput = document.getElementById("intent-name-filter");
  if (nameInput) {
    intentNameFilter = String(nameInput.value || "");
    nameInput.addEventListener("input", () => {
      intentNameFilter = String(nameInput.value || "");
      if (intentNameFilterTimer != null) clearTimeout(intentNameFilterTimer);
      intentNameFilterTimer = setTimeout(() => {
        intentNameFilterTimer = null;
        void refreshIntents({ force: true });
      }, NAME_FILTER_DEBOUNCE_MS);
    });
  }

  const tagsRoot = document.getElementById("intent-tag-filters");
  if (tagsRoot) {
    tagsRoot.replaceChildren();
    intentListFilterTags = [];
    intentTagFilterEditor = mountTagEditor(tagsRoot, {
      tags: [],
      confirmRemove: false,
      addLabel: "Filter tags",
      getCatalogTags: () => catalogTagsCache,
      async onAdd(tag) {
        intentListFilterTags = [...intentListFilterTags, tag];
        await refreshIntents({ force: true });
      },
      async onRemove(tag) {
        intentListFilterTags = intentListFilterTags.filter((t) => t !== tag);
        await refreshIntents({ force: true });
      },
    });
    tagsRoot.setAttribute("aria-label", "Intent filter tags");
  }

  const artistsRoot = document.getElementById("intent-artist-filters");
  if (artistsRoot) {
    artistsRoot.replaceChildren();
    intentListFilterArtistIds = [];
    intentArtistFilterEditor = mountArtistEditor(artistsRoot, {
      artists: [],
      confirmRemove: false,
      addLabel: "Filter artists",
      getCatalogArtists: () => catalogArtistsCache,
      async onAdd(artist) {
        intentListFilterArtistIds = [...intentListFilterArtistIds, artist.id];
        await refreshIntents({ force: true });
      },
      async onRemove(artist) {
        intentListFilterArtistIds = intentListFilterArtistIds.filter(
          (id) => id !== artist.id,
        );
        await refreshIntents({ force: true });
      },
    });
    artistsRoot.setAttribute("aria-label", "Intent filter artists");
  }

  const sourcesRoot = document.getElementById("intent-source-filters");
  if (sourcesRoot) {
    sourcesRoot.replaceChildren();
    const platformsRoot = document.createElement("div");
    platformsRoot.className = "source-toggles";
    platformsRoot.setAttribute("role", "group");
    platformsRoot.setAttribute("aria-label", "Intent sources");
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
    intentListFilterPlatforms = [];

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
      intentListFilterPlatforms = readPlatforms();
      await refreshIntents({ force: true });
    });
  }
}

function resetIntentListFilters() {
  intentListFilterTags = [];
  intentListFilterArtistIds = [];
  intentListFilterPlatforms = [];
  intentNameFilter = "";
  intentTagFilterEditor?.setTags([]);
  intentArtistFilterEditor?.setIds([]);
  const nameInput = document.getElementById("intent-name-filter");
  if (nameInput) nameInput.value = "";
  if (intentNameFilterTimer != null) {
    clearTimeout(intentNameFilterTimer);
    intentNameFilterTimer = null;
  }
  const sourcesRoot = document.getElementById("intent-source-filters");
  if (sourcesRoot) {
    for (const btn of sourcesRoot.querySelectorAll(".source-toggle")) {
      btn.setAttribute("aria-pressed", "false");
    }
  }
}

function mountCacheNameFilter() {
  const nameInput = document.getElementById("cache-name-filter");
  if (!nameInput) return;
  cacheNameFilter = String(nameInput.value || "");
  nameInput.addEventListener("input", () => {
    cacheNameFilter = String(nameInput.value || "");
    if (cacheNameFilterTimer != null) clearTimeout(cacheNameFilterTimer);
    cacheNameFilterTimer = setTimeout(() => {
      cacheNameFilterTimer = null;
      void refreshFiles({ force: true });
    }, NAME_FILTER_DEBOUNCE_MS);
  });
}

function resetCacheNameFilter() {
  cacheNameFilter = "";
  const nameInput = document.getElementById("cache-name-filter");
  if (nameInput) nameInput.value = "";
  if (cacheNameFilterTimer != null) {
    clearTimeout(cacheNameFilterTimer);
    cacheNameFilterTimer = null;
  }
}

async function refreshMixes({ force = false } = {}) {
  const body = document.getElementById("catalog-body");
  const res = await fetch("/api/mixes");
  const data = await res.json();
  // Keep in-progress catalog tag edits; still refresh Playlog below.
  const skipCatalog = !force && focusInside(body);
  if (!skipCatalog) {
    body.innerHTML = "";
    if (!data.mixes.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.className = "muted";
      td.textContent = "No releases yet";
      tr.appendChild(td);
      body.appendChild(tr);
      await refreshTagSuggestions();
      await refreshPlaylog();
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
      artistCell.colSpan = 6;
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
        try {
          const data = await postRefreshArtists([group.artistId]);
          if (!data.ok) {
            showNotice(data.detail || "Refresh artist failed", "error");
            return;
          }
          showNotice(
            `Refreshed “${group.artistName}” · ${data.added} new release(s)`,
            "ok",
          );
          await refreshMixes();
        } catch (err) {
          showNotice("Refresh artist request failed", "error");
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
          try {
            const res = await fetch(`/api/artists/${group.artistId}`, {
              method: "DELETE",
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              showNotice(data.detail || "Delete artist failed", "error");
              return;
            }
            expandedCatalogArtists.delete(group.artistId);
            showNotice(`Deleted “${group.artistName}”`, "ok");
            await refreshMixes();
            await refreshIntents({ force: true });
            await refreshFiles();
          } catch (err) {
            showNotice("Delete artist request failed", "error");
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
        const rejectPending = isRejectPending(mix.id);
        const unrejectPending = isUnrejectPending(mix.id);
        if ((mix.rejected && !unrejectPending) || rejectPending) {
          tr.classList.add("mix-rejected");
        }
        if (rejectPending) {
          tr.classList.add("reject-pending");
          tr.setAttribute("aria-busy", "true");
        }
        if (unrejectPending) {
          tr.classList.add("unreject-pending");
          tr.setAttribute("aria-busy", "true");
        }
        tr.dataset.artistId = group.artistId;
        tr.dataset.mixId = mix.id;
        tr.hidden = !expanded;

        const queueCell = document.createElement("td");
        queueCell.className = "catalog-queue-cell";
        const showAsRejected =
          (mix.rejected && !unrejectPending) || rejectPending;
        if (!showAsRejected) {
          mountCatalogQueueControl({ cell: queueCell, mix });
        }
        tr.appendChild(queueCell);

        const coverCell = document.createElement("td");
        coverCell.className = "catalog-cover-cell";
        if (mix.has_cover) {
          const img = document.createElement("img");
          img.className = "catalog-cover";
          img.alt = mix.title
            ? `Cover art for ${mix.title}`
            : "Release cover art";
          img.width = 48;
          img.height = 48;
          img.loading = "lazy";
          img.src = `/api/mixes/${mix.id}/cover`;
          coverCell.appendChild(img);
        } else {
          const placeholder = document.createElement("span");
          placeholder.className = "catalog-cover-placeholder";
          placeholder.setAttribute("aria-hidden", "true");
          coverCell.appendChild(placeholder);
        }
        tr.appendChild(coverCell);

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
        mountAnnotateKit({
          surface: "catalog",
          mix,
          starsRoot,
          actionsRoot: tagRow,
          rateInteractive: true,
          allowUnreject: true,
          refreshAfterTag: true,
          starsClass: "catalog-stars",
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
      td.colSpan = 6;
      td.className = "muted";
      td.textContent = "No releases match these filters";
      tr.appendChild(td);
      body.appendChild(tr);
    }
    await refreshTagSuggestions();
  }
  await refreshPlaylog();
}

function formatPlaylogOffset(offset) {
  const n = Number(offset) || 0;
  if (n > 0) return String(n);
  return String(n);
}

function sequenceDropKey(intentId, mixId) {
  return `${intentId}:${mixId}`;
}

function isSequenceDropPending(intentId, mixId) {
  return pendingSequenceDrops.has(sequenceDropKey(intentId, mixId));
}

/** True when the UA has no hover (touch / coarse) — no hover-reveal Drop chrome. */
function isHoverNone() {
  return window.matchMedia("(hover: none)").matches;
}

/** POST Drop from sequence; throws Error with server detail on failure. */
async function dropFromSequence(intentId, mixId) {
  const res = await fetch(`/api/intents/${intentId}/sequence/drop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mix_id: mixId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string" ? detail : "Drop from sequence failed",
    );
  }
  return data;
}

/** POST Queue onto sequence (front|back); throws Error with server detail. */
async function queueOnSequence(intentId, mixId, position) {
  const res = await fetch(`/api/intents/${intentId}/sequence/queue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mix_id: mixId, position }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string" ? detail : "Queue on sequence failed",
    );
  }
  return data;
}

async function fetchMatchingIntents(mixId) {
  const res = await fetch(`/api/mixes/${mixId}/matching-intents`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string" ? detail : "Could not load matching intents",
    );
  }
  return data.intents || [];
}

let openCatalogQueuePicker = null;

function closeCatalogQueuePicker() {
  if (!openCatalogQueuePicker) return;
  openCatalogQueuePicker.close();
  openCatalogQueuePicker = null;
}

/**
 * Catalog split Queue control: prepend (↪ flipped) | append (↪).
 * @param {{ cell: HTMLElement, mix: object }} opts
 */
function mountCatalogQueueControl({ cell, mix }) {
  cell.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "catalog-queue-split";
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", "Queue");

  const frontBtn = document.createElement("button");
  frontBtn.type = "button";
  frontBtn.className = "catalog-queue-half catalog-queue-front";
  frontBtn.setAttribute("aria-label", "Queue at front");
  frontBtn.dataset.tip = "Queue at front";
  const frontGlyph = document.createElement("span");
  frontGlyph.className = "catalog-queue-glyph";
  frontGlyph.setAttribute("aria-hidden", "true");
  frontGlyph.textContent = BTN.queue;
  frontBtn.appendChild(frontGlyph);

  const backBtn = document.createElement("button");
  backBtn.type = "button";
  backBtn.className = "catalog-queue-half catalog-queue-back";
  backBtn.setAttribute("aria-label", "Queue at back");
  backBtn.dataset.tip = "Queue at back";
  const backGlyph = document.createElement("span");
  backGlyph.className = "catalog-queue-glyph";
  backGlyph.setAttribute("aria-hidden", "true");
  backGlyph.textContent = BTN.queue;
  backBtn.appendChild(backGlyph);

  wrap.appendChild(frontBtn);
  wrap.appendChild(backBtn);
  cell.appendChild(wrap);

  async function openPicker(position, anchorBtn) {
    closeCatalogQueuePicker();
    const pickerWrap = document.createElement("div");
    pickerWrap.className = "catalog-queue-picker tag-picker-wrap";
    pickerWrap.addEventListener("click", (event) => event.stopPropagation());
    pickerWrap.addEventListener("pointerdown", (event) =>
      event.stopPropagation(),
    );

    const filterInput = document.createElement("input");
    filterInput.type = "text";
    filterInput.className = "tag-picker-input";
    filterInput.placeholder = "intent";
    filterInput.autocomplete = "off";
    filterInput.spellcheck = false;

    const suggestList = document.createElement("div");
    suggestList.className = "tag-suggest-list";
    const loading = document.createElement("div");
    loading.className = "muted";
    loading.textContent = "Loading…";
    suggestList.appendChild(loading);

    pickerWrap.appendChild(filterInput);
    pickerWrap.appendChild(suggestList);
    cell.appendChild(pickerWrap);
    anchorBtn.setAttribute("aria-expanded", "true");

    let intents = [];
    let highlightIndex = 0;
    let closed = false;

    function close() {
      if (closed) return;
      closed = true;
      pickerWrap.remove();
      frontBtn.removeAttribute("aria-expanded");
      backBtn.removeAttribute("aria-expanded");
      document.removeEventListener("pointerdown", onDocPointer, true);
      document.removeEventListener("keydown", onDocKey, true);
      if (openCatalogQueuePicker === api) openCatalogQueuePicker = null;
    }

    const api = { close };
    openCatalogQueuePicker = api;

    function onDocPointer(event) {
      if (!pickerWrap.contains(event.target) && !wrap.contains(event.target)) {
        close();
      }
    }

    function onDocKey(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    }

    document.addEventListener("pointerdown", onDocPointer, true);
    document.addEventListener("keydown", onDocKey, true);

    function visibleIntents() {
      const q = (filterInput.value || "").trim().toLowerCase();
      if (!q) return intents;
      return intents.filter((intent) =>
        String(intent.name || "")
          .toLowerCase()
          .includes(q),
      );
    }

    function paintHighlight() {
      const rows = [...suggestList.querySelectorAll("button.tag-suggest")];
      rows.forEach((row, index) => {
        row.classList.toggle("is-active", index === highlightIndex);
      });
    }

    function renderSuggestions() {
      suggestList.innerHTML = "";
      const rows = visibleIntents();
      if (!rows.length) {
        const empty = document.createElement("div");
        empty.className = "muted";
        empty.textContent = "No matching intents";
        suggestList.appendChild(empty);
        return;
      }
      highlightIndex = Math.min(highlightIndex, rows.length - 1);
      rows.forEach((intent, index) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tag-suggest";
        btn.textContent = intent.name || "(unnamed)";
        if (index === highlightIndex) btn.classList.add("is-active");
        btn.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          void chooseIntent(intent);
        });
        suggestList.appendChild(btn);
      });
    }

    async function chooseIntent(intent) {
      close();
      wrap.classList.add("catalog-queue-pending");
      wrap.setAttribute("aria-busy", "true");
      frontBtn.disabled = true;
      backBtn.disabled = true;
      try {
        await queueOnSequence(intent.id, mix.id, position);
        const where = position === "front" ? "front" : "back";
        showNotice(`Queued at ${where} of ${intent.name || "intent"}`, "ok");
        await refreshAffectedSurfaces(["playlog", "intents"], { force: true });
        void refreshAffectedSurfaces(["cache"], { force: true });
      } catch (err) {
        showNotice(err?.message || "Queue failed", "warn");
        wrap.classList.remove("catalog-queue-pending");
        wrap.removeAttribute("aria-busy");
        frontBtn.disabled = false;
        backBtn.disabled = false;
      }
    }

    filterInput.addEventListener("input", () => {
      highlightIndex = 0;
      renderSuggestions();
    });
    filterInput.addEventListener("keydown", (event) => {
      const rows = visibleIntents();
      if (event.key === "Enter") {
        event.preventDefault();
        const intent = rows[highlightIndex] || rows[0];
        if (intent) void chooseIntent(intent);
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        highlightIndex = Math.min(
          highlightIndex + 1,
          Math.max(0, rows.length - 1),
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

    filterInput.focus();
    try {
      intents = await fetchMatchingIntents(mix.id);
      if (!closed) renderSuggestions();
    } catch (err) {
      if (closed) return;
      suggestList.innerHTML = "";
      const fail = document.createElement("div");
      fail.className = "muted";
      fail.textContent = err?.message || "Could not load intents";
      suggestList.appendChild(fail);
    }
  }

  frontBtn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    void openPicker("front", frontBtn);
  });
  backBtn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    void openPicker("back", backBtn);
  });
}

/**
 * Commit Drop with pending chrome (hover confirm-click or touch swipe).
 * @param {{ row: HTMLElement | null, intentId: string, mixId: string, dropBtn?: HTMLButtonElement | null }} opts
 */
/**
 * Commit Drop with pending chrome (hover confirm-click or touch swipe).
 * @param {{ row: HTMLElement | null, intentId: string, mixId: string, dropBtn?: HTMLButtonElement | null }} opts
 */
async function confirmDropFromSequence({
  row,
  intentId,
  mixId,
  dropBtn = null,
}) {
  pendingSequenceDrops.add(sequenceDropKey(intentId, mixId));
  if (row) {
    row.classList.add("seq-drop-pending");
    row.setAttribute("aria-busy", "true");
  }
  if (dropBtn) {
    dropBtn.hidden = true;
    dropBtn.disabled = true;
  }
  try {
    await dropFromSequence(intentId, mixId);
    showNotice("Dropped from sequence", "ok");
    // Playlog/intents first (row should vanish); Cache can lag behind.
    await refreshAffectedSurfaces(["playlog", "intents"], { force: true });
    void refreshAffectedSurfaces(["cache"], { force: true });
    pendingSequenceDrops.delete(sequenceDropKey(intentId, mixId));
  } catch (err) {
    pendingSequenceDrops.delete(sequenceDropKey(intentId, mixId));
    if (row) {
      row.classList.remove("seq-drop-pending");
      row.removeAttribute("aria-busy");
    }
    if (dropBtn) {
      dropBtn.hidden = false;
      dropBtn.disabled = false;
    }
    showNotice(
      err instanceof Error ? err.message : "Drop from sequence failed",
      "error",
    );
    console.error(err);
  }
}

/** @param {string} mixId */
function annotateRowsForMix(mixId) {
  if (!mixId) return [];
  return [
    ...document.querySelectorAll(
      `tr.mix-row[data-mix-id="${CSS.escape(mixId)}"], tr.playlog-row[data-mix-id="${CSS.escape(mixId)}"]`,
    ),
  ];
}

function isRejectPending(mixId) {
  return Boolean(mixId) && pendingRejects.has(mixId);
}

function isUnrejectPending(mixId) {
  return Boolean(mixId) && pendingUnrejects.has(mixId);
}

/** Mute Catalog/Playlog rows immediately while Reject POST is in flight. */
function markRejectPending(mixId, row = null) {
  if (!mixId) return;
  pendingRejects.add(mixId);
  pendingUnrejects.delete(mixId);
  const rows = new Set(annotateRowsForMix(mixId));
  if (row) rows.add(row);
  for (const el of rows) {
    el.classList.add("reject-pending", "mix-rejected");
    el.setAttribute("aria-busy", "true");
  }
  document.getElementById("player")?.classList.toggle(
    "reject-pending",
    currentMixId === mixId,
  );
}

/**
 * @param {string} mixId
 * @param {{ restore?: boolean }} [opts] restore=true removes optimistic mix-rejected (failed POST).
 */
function clearRejectPending(mixId, { restore = false } = {}) {
  if (!mixId) return;
  pendingRejects.delete(mixId);
  for (const el of annotateRowsForMix(mixId)) {
    el.classList.remove("reject-pending");
    el.removeAttribute("aria-busy");
    if (restore) el.classList.remove("mix-rejected");
  }
  if (currentMixId === mixId) {
    document.getElementById("player")?.classList.remove("reject-pending");
  }
}

/** Clear Reject mute immediately while Un-reject POST is in flight. */
function markUnrejectPending(mixId, row = null) {
  if (!mixId) return;
  pendingUnrejects.add(mixId);
  pendingRejects.delete(mixId);
  const rows = new Set(annotateRowsForMix(mixId));
  if (row) rows.add(row);
  for (const el of rows) {
    el.classList.add("unreject-pending");
    el.classList.remove("mix-rejected", "playlog-soft-rejected", "reject-pending");
    el.setAttribute("aria-busy", "true");
  }
}

/**
 * @param {string} mixId
 * @param {{ restore?: boolean }} [opts] restore=true re-applies Reject mute (failed Un-reject).
 */
function clearUnrejectPending(mixId, { restore = false } = {}) {
  if (!mixId) return;
  pendingUnrejects.delete(mixId);
  for (const el of annotateRowsForMix(mixId)) {
    el.classList.remove("unreject-pending");
    el.removeAttribute("aria-busy");
    if (restore) el.classList.add("mix-rejected");
  }
}

/**
 * Hover-reveal Drop on a sequence `#` slot (Playlog upcoming / Shared sequence).
 * Confirm-click (⊖ → 💥) like Reject / Delete. On confirm, grey the row immediately
 * and hide Drop until the backend refresh lands (or restore on failure).
 * Not mounted on `(hover: none)` — Playlog uses swipe Drop instead.
 * @param {{ cell: HTMLElement, intentId: string, mixId: string, labelText: string }} opts
 */
function mountSequenceDropControl({
  cell,
  intentId,
  mixId,
  labelText,
}) {
  cell.classList.add("seq-drop-cell");
  cell.replaceChildren();
  const stack = document.createElement("div");
  stack.className = "seq-drop-stack";
  const label = document.createElement("span");
  label.className = "seq-drop-label";
  label.textContent = labelText;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.classList.add("seq-drop-action");
  bindConfirmClick(btn, {
    idleSymbol: BTN.drop,
    idleLabel: "Drop from sequence",
    armedSymbol: BTN.confirmDelete,
    armedLabel: "really drop?",
    stopPropagation: true,
    async onConfirm() {
      await confirmDropFromSequence({
        row: cell.closest("tr"),
        intentId,
        mixId,
        dropBtn: btn,
      });
    },
  });
  stack.appendChild(label);
  stack.appendChild(btn);
  cell.appendChild(stack);
}

const PLAYLOG_SWIPE_THRESHOLD_PX = 56;
const PLAYLOG_SWIPE_AXIS_RATIO = 1.5;
const PLAYLOG_SWIPE_IGNORE_SEL =
  "button, a, input, select, textarea, .tag-picker-wrap, .star-rating, .seq-drop-stack, .playlog-cover-action, .playlog-swipe-confirm";

/** @type {HTMLElement | null} */
let playlogSwipeArmedRow = null;

/** Clear swipe preview / armed confirm chrome on a Playlog row. */
function clearPlaylogSwipePreview(tr) {
  if (!tr) return;
  tr.classList.remove(
    "playlog-row-swiping",
    "playlog-swipe-preview-drop",
    "playlog-swipe-preview-play",
    "playlog-swipe-armed",
    "playlog-swipe-armed-drop",
    "playlog-swipe-armed-play",
  );
  tr.style.removeProperty("--playlog-swipe-progress");
  tr.querySelector(".playlog-swipe-confirm")?.remove();
  tr.querySelector(".playlog-swipe-confirm-host")?.classList.remove(
    "playlog-swipe-confirm-host",
  );
  if (playlogSwipeArmedRow === tr) playlogSwipeArmedRow = null;
}

function clearOtherPlaylogSwipeArmed(except) {
  for (const row of document.querySelectorAll(
    "#playlog-table .playlog-row.playlog-swipe-armed",
  )) {
    if (row !== except) clearPlaylogSwipePreview(row);
  }
}

/** Drop confirm on lead (left); Play confirm on Length cell (right). */
function playlogSwipeConfirmHost(tr, kind) {
  if (kind === "play") {
    return (
      tr.querySelector(".playlog-side-cell") ||
      tr.lastElementChild ||
      tr.querySelector(".playlog-lead-cell") ||
      tr.firstElementChild
    );
  }
  return tr.querySelector(".playlog-lead-cell") || tr.firstElementChild;
}

/**
 * Arm a swipe action: keep red/green preview and show a confirm symbol to tap.
 * @param {HTMLElement} tr
 * @param {"drop" | "play"} kind
 * @param {{ symbol: string, label: string, onConfirm: () => void | Promise<void> }} opts
 */
function armPlaylogSwipe(tr, kind, { symbol, label, onConfirm }) {
  clearOtherPlaylogSwipeArmed(tr);
  tr.classList.remove(
    "playlog-row-swiping",
    "playlog-swipe-preview-drop",
    "playlog-swipe-preview-play",
  );
  tr.classList.add(
    "playlog-swipe-armed",
    `playlog-swipe-armed-${kind}`,
  );
  tr.style.setProperty("--playlog-swipe-progress", "1");
  playlogSwipeArmedRow = tr;
  const host = playlogSwipeConfirmHost(tr, kind);
  if (!host) return;
  for (const el of tr.querySelectorAll(".playlog-swipe-confirm-host")) {
    if (el !== host) el.classList.remove("playlog-swipe-confirm-host");
  }
  host.classList.add("playlog-swipe-confirm-host");
  let btn = tr.querySelector(".playlog-swipe-confirm");
  if (!btn) {
    btn = document.createElement("button");
    btn.type = "button";
  }
  if (btn.parentElement !== host) host.appendChild(btn);
  btn.className = `playlog-swipe-confirm playlog-swipe-confirm-${kind}`;
  btn.removeAttribute("aria-hidden");
  btn.tabIndex = 0;
  setSymbolButton(btn, symbol, label);
  btn.onclick = (event) => {
    event.stopPropagation();
    clearPlaylogSwipePreview(tr);
    void onConfirm();
  };
}

/**
 * Touch Playlog: left swipe previews Drop (red + ⊖), right swipe previews Play
 * (green + ▶/◀/⏸). Tap the symbol to confirm; swipe short / tap row dismisses.
 * @param {HTMLElement} tr
 * @param {{
 *   canDrop: boolean,
 *   onDrop: (() => void | Promise<void>) | null,
 *   onPlay: (() => void | Promise<void>) | null,
 *   playSymbol?: string | null,
 *   playLabel?: string | null,
 * }} opts
 */
function bindPlaylogRowSwipe(tr, { canDrop, onDrop, onPlay, playSymbol, playLabel }) {
  if (!canDrop && !onPlay) return;

  let pointerId = null;
  let startX = 0;
  let startY = 0;
  /** @type {null | "h" | "v"} */
  let axis = null;
  let dx = 0;
  let dragging = false;

  const ensurePreviewSymbol = (kind) => {
    const host = playlogSwipeConfirmHost(tr, kind);
    if (!host) return;
    for (const el of tr.querySelectorAll(".playlog-swipe-confirm-host")) {
      if (el !== host) el.classList.remove("playlog-swipe-confirm-host");
    }
    host.classList.add("playlog-swipe-confirm-host");
    let btn = tr.querySelector(".playlog-swipe-confirm");
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.tabIndex = -1;
      btn.setAttribute("aria-hidden", "true");
    }
    if (btn.parentElement !== host) host.appendChild(btn);
    btn.className = `playlog-swipe-confirm playlog-swipe-confirm-${kind} is-preview`;
    if (kind === "drop") {
      setSymbolButton(btn, BTN.drop, "Drop from sequence");
    } else {
      setSymbolButton(btn, playSymbol || BTN.play, playLabel || "Play this release");
    }
  };

  const applyDragPreview = (rawDx) => {
    let kind = null;
    let progress = 0;
    if (rawDx < 0 && canDrop) {
      kind = "drop";
      progress = Math.min(1, Math.abs(rawDx) / PLAYLOG_SWIPE_THRESHOLD_PX);
    } else if (rawDx > 0 && onPlay) {
      kind = "play";
      progress = Math.min(1, rawDx / PLAYLOG_SWIPE_THRESHOLD_PX);
    }
    tr.classList.toggle("playlog-swipe-preview-drop", kind === "drop");
    tr.classList.toggle("playlog-swipe-preview-play", kind === "play");
    if (kind) {
      tr.style.setProperty("--playlog-swipe-progress", progress.toFixed(3));
      if (progress > 0.25) ensurePreviewSymbol(kind);
    } else {
      tr.style.removeProperty("--playlog-swipe-progress");
      tr.querySelector(".playlog-swipe-confirm")?.remove();
    }
  };

  const onPointerDown = (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (event.target?.closest?.(PLAYLOG_SWIPE_IGNORE_SEL)) return;
    if (tr.classList.contains("seq-drop-pending")) return;
    // Tap (no drag) on an armed row dismisses the preview.
    if (tr.classList.contains("playlog-swipe-armed") && !dragging) {
      // Defer clear to pointerup if this stays a tap.
    }
    pointerId = event.pointerId;
    startX = event.clientX;
    startY = event.clientY;
    axis = null;
    dx = 0;
    dragging = false;
    try {
      tr.setPointerCapture(pointerId);
    } catch {
      /* ignore */
    }
  };

  const onPointerMove = (event) => {
    if (pointerId == null || event.pointerId !== pointerId) return;
    const rawDx = event.clientX - startX;
    const rawDy = event.clientY - startY;
    if (axis == null) {
      const adx = Math.abs(rawDx);
      const ady = Math.abs(rawDy);
      if (adx < 8 && ady < 8) return;
      if (adx > ady * PLAYLOG_SWIPE_AXIS_RATIO) {
        axis = "h";
        dragging = true;
        // New swipe clears prior armed chrome on this or other rows.
        clearPlaylogSwipePreview(tr);
        clearOtherPlaylogSwipeArmed(tr);
        tr.classList.add("playlog-row-swiping");
      } else {
        axis = "v";
        return;
      }
    }
    if (axis !== "h") return;
    event.preventDefault();
    dx = rawDx;
    applyDragPreview(dx);
  };

  const finish = (event) => {
    if (pointerId == null || event.pointerId !== pointerId) return;
    const committedAxis = axis;
    const committedDx = dx;
    const wasDragging = dragging;
    pointerId = null;
    axis = null;
    dx = 0;
    dragging = false;
    tr.classList.remove("playlog-row-swiping");
    tr.classList.remove("playlog-swipe-preview-drop", "playlog-swipe-preview-play");

    if (committedAxis === "h" && wasDragging) {
      if (committedDx <= -PLAYLOG_SWIPE_THRESHOLD_PX && canDrop && onDrop) {
        armPlaylogSwipe(tr, "drop", {
          symbol: BTN.drop,
          label: "Drop from sequence",
          onConfirm: onDrop,
        });
        return;
      }
      if (committedDx >= PLAYLOG_SWIPE_THRESHOLD_PX && onPlay) {
        armPlaylogSwipe(tr, "play", {
          symbol: playSymbol || BTN.play,
          label: playLabel || "Play this release",
          onConfirm: onPlay,
        });
        return;
      }
      clearPlaylogSwipePreview(tr);
      return;
    }

    // Tap on armed row (not the confirm button) dismisses.
    if (
      !wasDragging &&
      tr.classList.contains("playlog-swipe-armed") &&
      !event.target?.closest?.(".playlog-swipe-confirm")
    ) {
      clearPlaylogSwipePreview(tr);
    }
  };

  tr.addEventListener("pointerdown", onPointerDown);
  tr.addEventListener("pointermove", onPointerMove);
  tr.addEventListener("pointerup", finish);
  tr.addEventListener("pointercancel", finish);
}

/** Fill a Length-column cell with Cache status (second playlog line). */
function fillPlaylogCacheCell(cell, item) {
  cell.className = "playlog-cache-cell";
  cell.replaceChildren();
  const status = item.cache_status || "pending";
  const rejected = Boolean(item.rejected);
  const soft = Boolean(item.soft_rejected);

  if (rejected && !soft) {
    cell.classList.add("playlog-cache-rejected");
    cell.textContent = "✕";
    return;
  }
  if (rejected && soft) {
    cell.classList.add("playlog-cache-rejected");
    const size =
      item.size_bytes != null ? formatMb(item.size_bytes) : "";
    cell.textContent = size ? `✕ ${size}` : "✕";
    return;
  }

  if (status === "loading") {
    cell.classList.add("playlog-cache-loading");
    const wrap = document.createElement("div");
    wrap.className = "playlog-cache-progress";
    const total = item.total_bytes;
    const downloaded = Number(item.downloaded_bytes) || 0;
    const label = document.createElement("span");
    label.className = "playlog-cache-progress-label";
    label.textContent =
      total != null && total !== ""
        ? `← ${formatMb(total)}`
        : "← …";
    wrap.appendChild(label);
    if (total != null && total !== "" && Number(total) > 0) {
      const track = document.createElement("div");
      track.className = "playlog-cache-progress-track";
      const fill = document.createElement("div");
      fill.className = "playlog-cache-progress-fill";
      const pct = Math.max(
        0,
        Math.min(100, (downloaded / Number(total)) * 100),
      );
      fill.style.width = `${pct}%`;
      track.appendChild(fill);
      wrap.appendChild(track);
    }
    cell.appendChild(wrap);
    return;
  }

  if (status === "pending") {
    cell.classList.add("playlog-cache-pending");
    cell.textContent = "⋮ pending";
    return;
  }

  if (status === "cached") {
    const offset = Number(item.offset) || 0;
    const size =
      item.size_bytes != null ? formatMb(item.size_bytes) : "";
    if (offset < 0) {
      cell.classList.add("playlog-cache-past");
      cell.textContent = size ? `− ${size}` : "−";
    } else if (offset === 0) {
      cell.classList.add("playlog-cache-current");
      cell.textContent = size ? `✓${size}` : "✓";
    } else {
      cell.classList.add("playlog-cache-cached");
      cell.textContent = size ? `✓${size}` : "✓";
    }
    return;
  }

  // absent past
  cell.classList.add("playlog-cache-past");
  cell.textContent = "−";
}

/**
 * Patch Playlog cache/download cells from a Cache `/api/files` snapshot.
 * Used on throttled CACHE progress notices so we do not full-refetch `/api/playlog`.
 */
function patchPlaylogCacheFromFiles(data) {
  const playlogBody = document.getElementById("playlog-body");
  if (!playlogBody) return;

  const byId = new Map();
  for (const group of data.groups || []) {
    for (const file of group.mixes || []) {
      if (!file?.id) continue;
      byId.set(file.id, {
        cache_status: file.status || "pending",
        downloaded_bytes: file.downloaded_bytes,
        total_bytes: file.total_bytes,
        size_bytes: file.size_bytes,
      });
    }
  }
  for (const dl of data.downloads || []) {
    if (!dl?.mix_id) continue;
    const prev = byId.get(dl.mix_id) || {};
    byId.set(dl.mix_id, {
      ...prev,
      cache_status: prev.cache_status || "loading",
      downloaded_bytes: dl.downloaded_bytes,
      total_bytes: dl.total_bytes,
    });
  }
  if (!byId.size) return;

  for (const tr of playlogBody.querySelectorAll("tr.playlog-row[data-mix-id]")) {
    const mixId = tr.dataset.mixId;
    const info = byId.get(mixId);
    if (!info) continue;
    const cell = tr.querySelector(".playlog-cache-cell");
    if (!cell) continue;
    fillPlaylogCacheCell(cell, {
      ...info,
      offset: Number(tr.dataset.offset) || 0,
      rejected: tr.classList.contains("mix-rejected"),
      soft_rejected: tr.classList.contains("playlog-soft-rejected"),
    });
  }
}

async function playlogPlayMix(mixId) {
  const intentId = document.getElementById("player-intent")?.value;
  if (!intentId) {
    showNotice("Choose an intent", "warn");
    return;
  }
  try {
    const res = await fetch("/api/player/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent_id: intentId, mix_id: mixId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showNotice(data.detail || "Play failed", "error");
      return;
    }
    lastPlayheadCommitAt = Date.now();
    playheadPlayedNotifiedForMix = null;
    applyPlaybackMutationChrome(data, intentId);
    void refreshAfterIntentPlaybackMutation();
  } catch (err) {
    showNotice("Play request failed", "error");
    console.error(err);
  }
}

async function playlogPause() {
  try {
    const res = await fetch("/api/player/pause", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showNotice(data.detail || "Pause failed", "error");
      return;
    }
    applyPlaybackMutationChrome(data, lastPlayerIntentId);
    void refreshAfterIntentPlaybackMutation();
  } catch (err) {
    showNotice("Pause request failed", "error");
    console.error(err);
  }
}

/**
 * Scroll Playlog pane so offset −2 sits under sticky thead (in-pane).
 * Sets the fold-first home top (player fully shown there).
 */
function scrollPlaylogDefaultView() {
  const wrap = document.getElementById("playlog-table-wrap");
  const body = document.getElementById("playlog-body");
  const pane = focusPaneScrollEl("playlog");
  if (!wrap || !body || !pane) return;
  const rows = [...body.querySelectorAll(".playlog-row")];
  if (!rows.length) return;
  const target =
    rows.find((row) => row.dataset.offset === "-2") ||
    rows.find((row) => row.dataset.offset === "-1") ||
    rows.find((row) => row.dataset.offset === "0") ||
    rows[0];

  updatePlaylogStickyMetrics();

  const head = wrap.querySelector("thead");
  const headH = head ? head.getBoundingClientRect().height : 0;
  const paneRect = pane.getBoundingClientRect();
  const pin = paneRect.top + headH;
  const delta = target.getBoundingClientRect().top - pin;
  if (Math.abs(delta) >= 1) {
    pane.scrollTop += delta;
  }
  // Default −2 is collapse origin (player fully shown there).
  playlogCollapseOriginScrollTop = pane.scrollTop;
  playlogCollapseOriginReady = true;
}

/** Sticky current sits under thead; measure once per layout. */
function updatePlaylogStickyMetrics() {
  const table = document.getElementById("playlog-table");
  if (!table) return;
  const head = table.querySelector("thead");
  const headH = head ? head.getBoundingClientRect().height : 0;
  table.style.setProperty("--playlog-thead-h", `${headH}px`);
}

/**
 * Which edge the current row is pinned to (or null when in normal flow).
 * Uses the Playlog pane scroller viewport (not window).
 */
function playlogCurrentStuckEdge() {
  const wrap = document.getElementById("playlog-table-wrap");
  const pane = focusPaneScrollEl("playlog");
  const row = document.querySelector("#playlog-table .playlog-row.playlog-current");
  if (!wrap || !pane || !row) return null;

  const head = wrap.querySelector("thead");
  const headH = head ? head.getBoundingClientRect().height : 0;
  const paneRect = pane.getBoundingClientRect();
  const stickyTop = paneRect.top + headH;
  const stickyBottom = paneRect.bottom;
  const rowRect = row.getBoundingClientRect();
  const eps = 2;

  if (rowRect.top <= stickyTop + eps) {
    const prev = row.previousElementSibling;
    if (prev && prev.getBoundingClientRect().bottom <= stickyTop + eps) {
      return "top";
    }
  }
  if (rowRect.bottom >= stickyBottom - eps) {
    const next = row.nextElementSibling;
    if (next && next.getBoundingClientRect().top >= stickyBottom - eps) {
      return "bottom";
    }
  }
  return null;
}

/** True when current is pinned to the wrap top or bottom (not in normal flow). */
function playlogCurrentIsStuck() {
  return playlogCurrentStuckEdge() !== null;
}

function syncPlaylogCurrentStuck() {
  const table = document.getElementById("playlog-table");
  if (!table) return;
  const edge = playlogCurrentStuckEdge();
  table.classList.toggle("playlog-current-is-stuck", edge !== null);
  table.classList.toggle("playlog-current-stuck-top", edge === "top");
  table.classList.toggle("playlog-current-stuck-bottom", edge === "bottom");
  const row = table.querySelector(".playlog-row.playlog-current");
  if (!row) return;
  if (edge) {
    row.title = "Click empty space to return to default view";
  } else {
    row.removeAttribute("title");
  }
}

function playlogInteractiveTarget(target) {
  const el = target instanceof Element ? target : target?.parentElement;
  return Boolean(
    el &&
      el.closest(
        "button, a, input, select, textarea, label, .star-rating, .tag-chip, .tag-picker-wrap, .tag-editor",
      ),
  );
}

/** When current is stuck, click non-interactive cells → default (−2) view. */
function onPlaylogWrapClick(event) {
  const table = document.getElementById("playlog-table");
  if (!table?.classList.contains("playlog-current-is-stuck")) return;
  const cell = event.target?.closest?.(".playlog-row.playlog-current td");
  if (!cell || !table.contains(cell)) return;
  if (playlogInteractiveTarget(event.target)) return;
  scrollPlaylogDefaultView();
  rememberPlaylogScroll();
  expandPlayerCollapseFully();
  const pane = focusPaneScrollEl("playlog");
  if (pane) paneCollapseLastScrollTop = pane.scrollTop;
  requestAnimationFrame(() => {
    updatePlaylogStickyMetrics();
    syncPlaylogCurrentStuck();
  });
}

function ensurePlaylogScrollChrome() {
  const wrap = document.getElementById("playlog-table-wrap");
  if (!wrap || wrap.dataset.playlogChromeWired === "1") return;
  wrap.dataset.playlogChromeWired = "1";
  wrap.addEventListener("click", onPlaylogWrapClick);
}

/** Pane wheel/scroll drives fold-first player collapse (+ Playlog stuck metrics). */
function ensureFocusPaneScrollCollapse() {
  for (const pane of document.querySelectorAll(".focus-pane-scroll")) {
    if (pane.dataset.collapseScrollWired === "1") continue;
    pane.dataset.collapseScrollWired = "1";
    pane.addEventListener("wheel", onFocusPaneWheelFold, { passive: false });
    pane.addEventListener(
      "scroll",
      () => {
        syncPlayerCollapseFromActivePane();
        if (pane.closest('[data-focus-pane="playlog"]')) {
          syncPlaylogCurrentStuck();
        }
        syncFocusScrollHomeBtn();
      },
      { passive: true },
    );
  }
}

async function refreshPlaylog({ force = false } = {}) {
  const body = document.getElementById("playlog-body");
  if (!body) return;
  if (!force && focusInside(body)) return;
  const intentId = document.getElementById("player-intent")?.value || "";
  const playlogPane = focusPaneScrollEl("playlog");
  const savedScroll = playlogPane ? playlogPane.scrollTop : 0;
  const resetToDefault = intentId !== playlogScrollIntentId;
  const qs = intentId ? `?intent_id=${encodeURIComponent(intentId)}` : "";
  const res = await fetch(`/api/playlog${qs}`);
  const data = await res.json().catch(() => ({ items: [] }));
  const items = data.items || [];
  body.replaceChildren();
  if (!items.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "muted";
    td.textContent = "No assignment for this intent";
    tr.appendChild(td);
    body.appendChild(tr);
    playlogScrollIntentId = intentId;
    if (resetToDefault) delete focusTabScrollTop.playlog;
    return;
  }
  const playing = Boolean(data.playing);
  for (const item of items) {
    const offset = Number(item.offset) || 0;
    // One <tr> per entry so sticky works; lead (# + cover) + two-line stacks.
    const tr = document.createElement("tr");
    tr.className = "playlog-row";
    tr.dataset.mixId = item.id;
    tr.dataset.offset = String(offset);
    if (offset < 0) tr.classList.add("playlog-past");
    if (offset === 0) tr.classList.add("playlog-current");
    if (offset > 0) tr.classList.add("playlog-upcoming");
    const rejectPending = isRejectPending(item.id);
    const unrejectPending = isUnrejectPending(item.id);
    if ((item.rejected && !unrejectPending) || rejectPending) {
      tr.classList.add("mix-rejected");
    }
    if (item.soft_rejected && !unrejectPending) {
      tr.classList.add("playlog-soft-rejected");
    }
    if (rejectPending) {
      tr.classList.add("reject-pending");
      tr.setAttribute("aria-busy", "true");
    }
    if (unrejectPending) {
      tr.classList.add("unreject-pending");
      tr.setAttribute("aria-busy", "true");
    }
    const dropPending =
      Boolean(intentId) && isSequenceDropPending(intentId, item.id);
    if (dropPending) {
      tr.classList.add("seq-drop-pending");
      tr.setAttribute("aria-busy", "true");
    }

    const canPlay = Boolean(item.playable);
    const isLiveCurrent =
      Boolean(data.current_mix_id) && item.id === data.current_mix_id;
    const touchClient = isHoverNone();
    const canDrop =
      offset > 0 &&
      Boolean(intentId) &&
      !dropPending &&
      !isLiveCurrent;

    // Lead: # + cover in one cell — side-by-side when wide, stacked when narrow.
    const leadCell = document.createElement("td");
    leadCell.className = "playlog-lead-cell";
    const lead = document.createElement("div");
    lead.className = "playlog-lead";
    const offsetEl = document.createElement("div");
    offsetEl.className = "playlog-offset";
    // Hover: confirm-click Drop on `#`. Touch: keep `#` visible; swipe Drop instead.
    if (canDrop && !touchClient) {
      mountSequenceDropControl({
        cell: offsetEl,
        intentId,
        mixId: item.id,
        labelText: formatPlaylogOffset(offset),
      });
    } else {
      offsetEl.textContent = formatPlaylogOffset(offset);
    }
    lead.appendChild(offsetEl);

    const coverStack = document.createElement("div");
    coverStack.className = "playlog-cover-stack";
    if (item.has_cover) {
      const img = document.createElement("img");
      img.className = "playlog-cover";
      img.alt = item.title
        ? `Cover art for ${item.title}`
        : "Release cover art";
      img.width = 48;
      img.height = 48;
      img.loading = "lazy";
      img.src = `/api/mixes/${item.id}/cover`;
      coverStack.appendChild(img);
    } else {
      const placeholder = document.createElement("span");
      placeholder.className = "playlog-cover-placeholder";
      placeholder.setAttribute("aria-hidden", "true");
      coverStack.appendChild(placeholder);
    }
    let actionSymbol = null;
    let actionLabel = null;
    let actionHandler = null;
    if (playing && isLiveCurrent) {
      actionSymbol = "⏸";
      actionLabel = "Pause";
      actionHandler = () => playlogPause();
    } else if (offset < 0 && canPlay) {
      actionSymbol = "◀";
      actionLabel = "Play previous";
      actionHandler = () => playlogPlayMix(item.id);
    } else if (canPlay) {
      actionSymbol = "▶";
      actionLabel = offset === 0 ? "Play" : "Play this release";
      actionHandler = () => playlogPlayMix(item.id);
    }
    if (actionSymbol && actionHandler) {
      const actionBtn = document.createElement("button");
      actionBtn.type = "button";
      actionBtn.className = "playlog-cover-action";
      setSymbolButton(actionBtn, actionSymbol, actionLabel);
      actionBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        void actionHandler();
      });
      coverStack.appendChild(actionBtn);
    }
    lead.appendChild(coverStack);
    leadCell.appendChild(lead);
    tr.appendChild(leadCell);

    if (touchClient) {
      bindPlaylogRowSwipe(tr, {
        canDrop,
        onDrop: canDrop
          ? () =>
              confirmDropFromSequence({
                row: tr,
                intentId,
                mixId: item.id,
              })
          : null,
        onPlay: actionHandler,
        playSymbol: actionSymbol,
        playLabel: actionLabel,
      });
    }

    const mainCell = document.createElement("td");
    mainCell.className = "playlog-main-cell";
    const releaseLine = document.createElement("div");
    releaseLine.className = "playlog-release";
    const artist = item.artist || "Unknown";
    const title = item.title || "";
    releaseLine.appendChild(
      document.createTextNode(title ? `${artist} - ${title}` : artist),
    );
    const releaseUrl = item.url || "";
    const artistUrl = item.artist_url || "";
    const sourceHref = releaseUrl || artistUrl;
    const sourcePage = releaseUrl ? "release" : "artist";
    const sourceLink = createSourcePageLink(item.platform, sourceHref, {
      page: sourcePage,
    });
    if (sourceLink) {
      releaseLine.appendChild(document.createTextNode(" "));
      releaseLine.appendChild(sourceLink);
    }
    const annotateSlot = document.createElement("div");
    annotateSlot.className = "playlog-annotate";
    const starsRoot = document.createElement("div");
    const actionsRoot = document.createElement("div");
    actionsRoot.className = "tag-cell playlog-tag-cell";
    annotateSlot.appendChild(starsRoot);
    annotateSlot.appendChild(actionsRoot);
    mountAnnotateKit({
      surface: "playlog",
      mix: item,
      starsRoot,
      actionsRoot,
      rateInteractive: true,
      allowUnreject: true,
      refreshAfterTag: true,
      starsClass: "playlog-stars",
      tagEditorClass: "tag-editor playlog-tag-editor",
    });
    mainCell.appendChild(releaseLine);
    mainCell.appendChild(annotateSlot);
    tr.appendChild(mainCell);

    const sideCell = document.createElement("td");
    sideCell.className = "playlog-side-cell";
    const lengthLine = document.createElement("div");
    lengthLine.className = "playlog-length";
    lengthLine.textContent = formatDuration(item.duration_seconds || 0);
    const cacheLine = document.createElement("div");
    fillPlaylogCacheCell(cacheLine, item);
    sideCell.appendChild(lengthLine);
    sideCell.appendChild(cacheLine);
    tr.appendChild(sideCell);

    body.appendChild(tr);
  }
  if (data.upcoming_truncated) {
    const tr = document.createElement("tr");
    tr.className = "playlog-row playlog-truncated";
    const leadCell = document.createElement("td");
    leadCell.className = "playlog-lead-cell";
    const lead = document.createElement("div");
    lead.className = "playlog-lead";
    const offsetEl = document.createElement("div");
    offsetEl.className = "playlog-offset muted";
    offsetEl.textContent = "…";
    lead.appendChild(offsetEl);
    leadCell.appendChild(lead);
    const mainCell = document.createElement("td");
    mainCell.className = "playlog-main-cell muted";
    mainCell.textContent = "…";
    const sideCell = document.createElement("td");
    sideCell.className = "playlog-side-cell";
    tr.appendChild(leadCell);
    tr.appendChild(mainCell);
    tr.appendChild(sideCell);
    body.appendChild(tr);
  }
  playlogScrollIntentId = intentId;
  ensurePlaylogScrollChrome();
  requestAnimationFrame(() => {
    syncFocusTabsHeightVar();
    updatePlaylogStickyMetrics();
    if (activeFocusTab !== "playlog") {
      if (resetToDefault) delete focusTabScrollTop.playlog;
      return;
    }
    const pane = focusPaneScrollEl("playlog");
    if (resetToDefault) {
      scrollPlaylogDefaultView();
      expandPlayerCollapseFully();
    } else if (pane) {
      suppressPlayerCollapseFromPane = true;
      try {
        pane.scrollTop = savedScroll;
        updatePlaylogStickyMetrics();
      } finally {
        suppressPlayerCollapseFromPane = false;
      }
    }
    rememberPlaylogScroll();
    if (pane) paneCollapseLastScrollTop = pane.scrollTop;
    syncPlaylogCurrentStuck();
  });
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
  if (select.dataset.playlogBound !== "1") {
    select.dataset.playlogBound = "1";
    select.addEventListener("change", () => {
      syncPlaylogIntentPlayButton();
      void refreshPlaylog({ force: true });
    });
  }
  syncPlaylogIntentPlayButton();
}

function updateRejectControls(data) {
  if (playerAnnotateKit?.updateRejectControls) {
    playerAnnotateKit.updateRejectControls(data);
    return;
  }
  // Fallback before kit mounts (should be rare).
  const rejectBtn = document.getElementById("player-reject");
  if (!rejectBtn) return;
  rejectBtn.hidden = !!data.rejected;
}

async function maybeCommitPlayhead(playing) {
  if (!playing || playheadCommitInFlight) return;
  const now = Date.now();
  if (now - lastPlayheadCommitAt < PLAYHEAD_COMMIT_MS) return;
  playheadCommitInFlight = true;
  lastPlayheadCommitAt = now;
  const position = extrapolatedPlayerPosition();
  lastKnownPositionSeconds = position;
  try {
    const res = await fetch("/api/player/playhead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_seconds: position }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return;
    if (data.played) {
      const mixId = data.mix_id || null;
      if (mixId !== playheadPlayedNotifiedForMix) {
        playheadPlayedNotifiedForMix = mixId;
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
  // Glossary: Switch to intent; when that Intent is already playing → Pause.
  const label = playingThis ? "Pause" : "Switch to intent";
  setSymbolButton(btn, playingThis ? BTN.pause : BTN.play, label);
  btn.dataset.playing = playingThis ? "true" : "false";
}

function syncPlaylogIntentPlayButton() {
  const btn = document.getElementById("playlog-intent-play");
  if (!btn) return;
  const selected = document.getElementById("player-intent")?.value || "";
  const playingThis = Boolean(selected) && isIntentCurrentlyPlaying(selected);
  // Playlog action tip: Play now (selected Intent); Pause when that Intent is live.
  setSymbolButton(btn, playingThis ? BTN.pause : BTN.play, playingThis ? "Pause" : "Play now");
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
  for (const btn of document.querySelectorAll(
    "#intent-table .intent-cover-action.intent-play",
  )) {
    const playingThis =
      lastPlayerPlaying &&
      lastPlayerIntentId != null &&
      btn.dataset.intentId === lastPlayerIntentId;
    setIntentPlayButton(btn, playingThis);
  }
  syncPlaylogIntentPlayButton();
}

function isIntentCurrentlyPlaying(intentId) {
  return (
    lastPlayerPlaying &&
    lastPlayerIntentId != null &&
    intentId != null &&
    intentId === lastPlayerIntentId
  );
}

/** Immediate play/pause chrome from a mutation response; full remount is background. */
function applyPlaybackMutationChrome(data, intentId = null) {
  const playing = Boolean(data?.playing);
  const resolvedIntent =
    intentId || data?.intent_id || lastPlayerIntentId || null;
  if (data?.mix?.id) {
    currentMixId = data.mix.id;
  } else if (data?.current_mix_id) {
    currentMixId = data.current_mix_id;
  }
  updatePlayPauseButton(playing);
  updateIntentPlayButtons(playing, resolvedIntent);
  setPlayerLocalClock(playing);
}

async function pausePlayback() {
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
    showNotice(data.detail || "Pause failed", "error");
    return false;
  }
  if (data.played) {
    showNotice("Paused · marked played", "ok");
  }
  lastPlayheadCommitAt = Date.now();
  applyPlaybackMutationChrome(data, lastPlayerIntentId);
  void refreshAfterIntentPlaybackMutation({
    markedPlayed: Boolean(data.played),
  });
  return true;
}

async function playIntent(intentId) {
  if (!intentId) {
    showNotice("Choose an intent", "warn");
    return false;
  }
  syncPlayerIntentSelect(intentId);
  const res = await fetch("/api/player/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent_id: intentId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showNotice(data.detail || "Play failed", "error");
    return false;
  }
  lastPlayheadCommitAt = Date.now();
  playheadPlayedNotifiedForMix = null;
  applyPlaybackMutationChrome(data, intentId);
  void refreshAfterIntentPlaybackMutation();
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
    playerPositionSyncedSeconds = 0;
    playerPositionSyncedAt = 0;
    playerDurationSeconds = 0;
    if (playerTagEditor && !playerTagEditor.isBusy()) {
      playerTagEditor.setTags([]);
    }
    updateSeekBar({});
    setPlayerLocalClock(false);
    updateRejectControls({});
    updatePlayPauseButton(false);
    updateIntentPlayButtons(false, null);
    return;
  }
  const pos = Math.round(data.position_seconds || 0);
  playerDurationSeconds = Math.max(0, Math.round(data.duration_seconds || 0));
  playerPositionSyncedSeconds = pos;
  playerPositionSyncedAt = Date.now();
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
  setPlayerLocalClock(Boolean(data.playing));
  updateRejectControls(data);
  updatePlayPauseButton(Boolean(data.playing));
  updateIntentPlayButtons(Boolean(data.playing), data.intent_id);
  if (!data.playing) {
    lastPlayheadCommitAt = 0;
  }
}

/**
 * Latest-wins Cache refresh. Overlapping SSE notices share one chain: superseded
 * epochs no-op so an older GET cannot paint over newer pending/loading/progress.
 */
async function refreshFiles({ force = false } = {}) {
  const epoch = ++filesRefreshEpoch;
  if (force) filesRefreshForcePending = true;
  const done = filesRefreshTail.then(async () => {
    if (epoch !== filesRefreshEpoch) return;
    const useForce = filesRefreshForcePending;
    filesRefreshForcePending = false;
    await refreshFilesNow({ force: useForce });
  });
  filesRefreshTail = done.catch(() => {});
  return done;
}

async function refreshFilesNow({ force = false } = {}) {
  const body = document.getElementById("cache-body");
  if (!force && focusInside(body)) return;
  const res = await fetch("/api/files");
  const data = await res.json();
  updateStatusCacheChrome(
    data.cache_summary || {
      count: data.files.length,
      duration_seconds: 0,
      size_bytes: 0,
    },
  );
  body.innerHTML = "";
  const groups = Array.isArray(data.groups) ? data.groups : [];
  if (!groups.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "muted";
    td.textContent =
      "No assigned audio yet — create an intent with hours, or use Fill now on an Intent";
    tr.appendChild(td);
    body.appendChild(tr);
    patchPlaylogCacheFromFiles(data);
    return;
  }

  let paintedGroups = 0;
  for (const group of groups) {
    const visibleMixes = (group.mixes || []).filter((file) =>
      matchesNameFilter(cacheNameFilter, file.title, file.artist),
    );
    if (!visibleMixes.length) continue;
    paintedGroups += 1;
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

    for (const file of visibleMixes) {
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
          try {
            const res = await fetch("/api/current-mix", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ mix_id: isCurrent ? null : file.id }),
            });
            const bodyJson = await res.json().catch(() => ({}));
            if (!res.ok) {
              showNotice(
                bodyJson.detail || "Could not set current release",
                "error",
              );
              return;
            }
            currentMixId = bodyJson.current_mix_id || null;
            showNotice(
              currentMixId
                ? "Current release set · metered cap uses this + one ahead"
                : "Current release cleared · metered cap uses assignment head",
              "ok",
            );
            await refreshFiles();
          } catch (err) {
            showNotice("Current release request failed", "error");
            console.error(err);
          }
        });
        actionCell.appendChild(currentBtn);
      }
      tr.appendChild(actionCell);
      body.appendChild(tr);
    }
  }
  if (!paintedGroups) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "muted";
    td.textContent = cacheNameFilter.trim()
      ? "No cache rows match this filter"
      : "No assigned audio yet — create an intent with hours, or use Fill now on an Intent";
    tr.appendChild(td);
    body.appendChild(tr);
  }
  patchPlaylogCacheFromFiles(data);
}

async function saveDeviceHours(intentId, deviceId, hoursValue, expiresValue) {
  const hours = Number(hoursValue);
  if (!Number.isFinite(hours) || hours <= 0) {
    showNotice("Hours must be greater than 0", "warn");
    return false;
  }
  let expires_at = null;
  if (expiresValue !== "" && expiresValue != null) {
    const until = Number(expiresValue);
    if (!Number.isFinite(until) || until < 0) {
      showNotice("Expires in must be a non-negative number of hours", "warn");
      return false;
    }
    if (until > 0) {
      expires_at = new Date(Date.now() + until * 3600 * 1000).toISOString();
    }
  }
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
      showNotice(data.detail || "Save device hours failed", "error");
      return false;
    }
    const filling = data.fill_in_progress ? " · filling caches…" : "";
    showNotice(`Saved hours for ${deviceName(deviceId)}${filling}`, "ok");
    hoursEditorState.delete(intentId);
    await refreshIntents();
    await refreshFiles();
    return true;
  } catch (err) {
    showNotice("Save device hours request failed", "error");
    console.error(err);
    return false;
  }
}

async function deleteDeviceHours(intent, deviceId) {
  const name = deviceName(deviceId);
  const remaining = (intent.device_hours || [])
    .filter((dh) => dh.device_id !== deviceId)
    .map((dh) => ({
      device_id: dh.device_id,
      budget_seconds: dh.budget_seconds,
      expires_at: dh.expires_at,
    }));
  try {
    const res = await fetch(`/api/intents/${intent.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_hours: remaining }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      showNotice(
        typeof detail === "string"
          ? detail
          : detail?.[0]?.msg || "Remove device hours failed",
        "error",
      );
      return;
    }
    const filling = data.fill_in_progress ? " · filling caches…" : "";
    showNotice(`Removed hours for ${name}${filling}`, "ok");
    hoursEditorState.delete(intent.id);
    await refreshIntents();
    await refreshFiles();
  } catch (err) {
    showNotice("Remove device hours request failed", "error");
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

function intentCoverMixIds(seq, limit = 3) {
  const ids = [];
  for (const entry of seq?.entries || []) {
    if (!entry?.mix_id || !entry.has_cover) continue;
    ids.push(String(entry.mix_id));
    if (ids.length >= limit) break;
  }
  return ids;
}

/**
 * @param {string[]} mixIds
 * @param {{ intent?: { id: string, name: string } | null }} [options]
 */
function renderIntentCoverStack(mixIds, { intent = null } = {}) {
  const cell = document.createElement("td");
  cell.className = "intent-cover-cell intent-cover-span";
  cell.colSpan = 2;
  const stack = document.createElement("div");
  stack.className = "intent-cover-stack";
  stack.dataset.count = String(mixIds.length || 0);
  mixIds.forEach((mixId, index) => {
    const img = document.createElement("img");
    img.className = "intent-cover";
    img.alt = "";
    img.decoding = "async";
    img.src = `/api/mixes/${mixId}/cover`;
    // Sequence #1 first in the list → on top of the stack.
    img.style.zIndex = String(mixIds.length - index);
    stack.appendChild(img);
  });
  if (!mixIds.length) {
    const placeholder = document.createElement("span");
    placeholder.className = "intent-cover-placeholder";
    placeholder.setAttribute("aria-hidden", "true");
    stack.appendChild(placeholder);
  }
  if (intent) {
    const playBtn = document.createElement("button");
    playBtn.type = "button";
    playBtn.className = "intent-cover-action intent-play";
    playBtn.dataset.intentId = intent.id;
    const playingThis =
      lastPlayerPlaying &&
      lastPlayerIntentId != null &&
      lastPlayerIntentId === intent.id;
    setIntentPlayButton(playBtn, playingThis);
    playBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      void switchToIntentFromRow(intent);
    });
    stack.appendChild(playBtn);
  }
  cell.appendChild(stack);
  return cell;
}

/** Switch to intent / Pause from an Intent cover (or legacy row control). */
async function switchToIntentFromRow(intent) {
  try {
    if (isIntentCurrentlyPlaying(intent.id)) {
      const ok = await pausePlayback();
      if (ok) showNotice(`Paused “${intent.name}”`, "ok");
      return;
    }
    const ok = await playIntent(intent.id);
    if (ok) showNotice(`Playing “${intent.name}”`, "ok");
  } catch (err) {
    showNotice("Switch to intent request failed", "error");
    console.error(err);
  }
}

/**
 * @param {{ expanded?: boolean, onToggle?: () => void } | null} [toggle]
 * @returns {HTMLButtonElement | null}
 */
function renderIntentSeqToggle(toggle) {
  if (!toggle || typeof toggle.onToggle !== "function") return null;
  const expanded = Boolean(toggle.expanded);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "intent-seq-toggle";
  btn.setAttribute("aria-expanded", expanded ? "true" : "false");
  setSymbolButton(
    btn,
    expanded ? BTN.collapseSeq : BTN.expandSeq,
    expanded ? "Collapse shared sequence" : "Expand shared sequence",
  );
  btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggle.onToggle();
  });
  return btn;
}

/** Empty # + Cover cells for rows under a non-spanning cover. */
function appendIntentLeadCells(tr) {
  const num = document.createElement("td");
  num.className = "intent-num-cell";
  tr.appendChild(num);
  const cover = document.createElement("td");
  cover.className = "intent-cover-cell";
  tr.appendChild(cover);
}

/** Lead cells replaced by the sequence toggle (stack-width). */
function appendIntentToggleLeadCells(tr, toggle) {
  const cell = document.createElement("td");
  cell.className = "intent-seq-toggle-cell";
  cell.colSpan = 2;
  const btn = renderIntentSeqToggle(toggle);
  if (btn) cell.appendChild(btn);
  tr.appendChild(cell);
}

/** Toggle-only row when the intent has no assignment/editor rows. */
function appendIntentToggleRow(frag, intent, toggle) {
  const tr = document.createElement("tr");
  tr.className = "intent-toggle-row";
  tr.dataset.intentId = intent.id;
  appendIntentToggleLeadCells(tr, toggle);
  const rest = document.createElement("td");
  rest.colSpan = 2;
  rest.className = "intent-toggle-rest";
  tr.appendChild(rest);
  frag.appendChild(tr);
}

function renderIntentSeqCover(entry) {
  const cell = document.createElement("td");
  cell.className = "intent-cover-cell intent-seq-cover-cell";
  cell.appendChild(appendIntentSeqCoverEl(entry));
  return cell;
}

function toggleIntentSequence(intentId) {
  if (expandedIntentSequences.has(intentId)) {
    expandedIntentSequences.delete(intentId);
  } else {
    expandedIntentSequences.add(intentId);
  }
  void refreshIntents({ force: true });
}

function appendIntentSeqCoverEl(entry) {
  if (entry?.mix_id && entry.has_cover) {
    const img = document.createElement("img");
    img.className = "intent-seq-cover";
    img.alt = "";
    img.decoding = "async";
    img.src = `/api/mixes/${entry.mix_id}/cover`;
    return img;
  }
  const placeholder = document.createElement("span");
  placeholder.className = "intent-seq-cover-placeholder";
  placeholder.setAttribute("aria-hidden", "true");
  return placeholder;
}

function appendIntentSequenceRows(frag, intent, seq) {
  const entries = seq?.entries || [];
  if (!entries.length) {
    const tr = document.createElement("tr");
    tr.className = "intent-seq-row intent-seq-empty-row";
    tr.dataset.intentId = intent.id;
    appendIntentLeadCells(tr);
    const empty = document.createElement("td");
    empty.colSpan = 2;
    empty.className = "muted";
    empty.textContent = "Empty sequence";
    tr.appendChild(empty);
    frag.appendChild(tr);
    return;
  }

  const liveCurrentMixId =
    lastPlayerIntentId === intent.id ? currentMixId : null;

  for (const entry of entries) {
    const tr = document.createElement("tr");
    tr.className = "intent-seq-row";
    tr.dataset.intentId = intent.id;
    const dropPending =
      Boolean(entry.mix_id) && isSequenceDropPending(intent.id, entry.mix_id);
    if (dropPending) {
      tr.classList.add("seq-drop-pending");
      tr.setAttribute("aria-busy", "true");
    }

    const numCell = document.createElement("td");
    numCell.className = "intent-num-cell intent-seq-num-cell";
    const labelText = String(entry.position + 1);
    const canDrop =
      entry.mix_id &&
      !dropPending &&
      (!liveCurrentMixId || entry.mix_id !== liveCurrentMixId);
    // Hover: confirm-click Drop. Touch: show `#` only (no Intent swipe yet).
    if (canDrop && !isHoverNone()) {
      mountSequenceDropControl({
        cell: numCell,
        intentId: intent.id,
        mixId: entry.mix_id,
        labelText,
      });
    } else {
      numCell.textContent = labelText;
    }
    tr.appendChild(numCell);
    tr.appendChild(renderIntentSeqCover(entry));

    const nameCell = document.createElement("td");
    nameCell.className = "intent-seq-name-cell";
    const artist = entry.artist || "Unknown";
    const title = entry.title || entry.mix_id || "—";
    nameCell.textContent = `${artist} - ${title}`;
    tr.appendChild(nameCell);

    const actions = document.createElement("td");
    actions.className = "intent-actions-cell intent-seq-length-cell muted";
    actions.textContent =
      entry.duration_seconds != null
        ? formatDuration(entry.duration_seconds)
        : "—";
    tr.appendChild(actions);

    frag.appendChild(tr);
  }
}

/** Active platforms to show in the filters cell; empty when all are on. */
function intentFilterPlatforms(platforms) {
  const active = new Set(
    platforms && platforms.length ? platforms : DEFAULT_INTENT_PLATFORMS,
  );
  const ordered = DEFAULT_INTENT_PLATFORMS.filter((p) => active.has(p));
  if (ordered.length === DEFAULT_INTENT_PLATFORMS.length) return [];
  return ordered;
}

function appendIntentPlatformSymbols(parent, platforms) {
  for (const platform of platforms) {
    const icon = document.createElement("span");
    icon.className = "platform-symbol";
    icon.dataset.on = "true";
    icon.title = PLATFORM_LABELS[platform] || platform;
    icon.setAttribute("aria-label", PLATFORM_LABELS[platform] || platform);
    if (PLATFORM_SVG[platform]) {
      icon.innerHTML = PLATFORM_SVG[platform];
    } else {
      icon.textContent = PLATFORM_LABELS[platform] || platform;
    }
    parent.appendChild(icon);
  }
}

function appendIntentActions(cell, ...buttons) {
  cell.className = "intent-actions-cell";
  for (const btn of buttons) {
    if (btn) cell.appendChild(btn);
  }
}

function buildIntentActionButtons(intent) {
  const editBtn = document.createElement("button");
  editBtn.type = "button";
  setSymbolButton(editBtn, BTN.edit, "Edit intent");
  editBtn.addEventListener("click", () => beginEditIntent(intent));

  const regenerateBtn = document.createElement("button");
  regenerateBtn.type = "button";
  setSymbolButton(regenerateBtn, BTN.refresh, "Regenerate sequence");
  regenerateBtn.addEventListener("click", async () => {
    try {
      const res = await fetch(`/api/intents/${intent.id}/refresh-sequence`, {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showNotice(data.detail || "Regenerate sequence failed", "error");
        return;
      }
      showNotice(
        data.fill_in_progress
          ? `Regenerated “${intent.name}” · fill started`
          : `Regenerated “${intent.name}”`,
        "ok",
      );
      await refreshAffectedSurfaces(["intents", "cache"], { force: true });
    } catch (err) {
      showNotice("Regenerate sequence request failed", "error");
      console.error(err);
    }
  });

  const fillNowBtn = document.createElement("button");
  fillNowBtn.type = "button";
  setSymbolButton(fillNowBtn, BTN.fill, "Fill now");
  fillNowBtn.addEventListener("click", async () => {
    try {
      const res = await fetch(`/api/intents/${intent.id}/fill-now`, { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showNotice(data.detail || "Fill now failed", "error");
        return;
      }
      showNotice(
        data.fill_in_progress
          ? `Fill now “${intent.name}” started · ${data.files} cached so far`
          : `Fill now “${intent.name}” · ${data.files} cached`,
        "ok",
      );
      await refreshAffectedSurfaces(["cache", "intents"], { force: true });
    } catch (err) {
      showNotice("Fill now request failed", "error");
      console.error(err);
    }
  });

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  bindConfirmDelete(deleteBtn, {
    label: "Delete intent",
    onConfirm: async () => {
      try {
        const res = await fetch(`/api/intents/${intent.id}`, { method: "DELETE" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          showNotice(data.detail || "Delete intent failed", "error");
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
        showNotice(`Deleted “${intent.name}”`, "ok");
        await refreshIntents({ force: true });
      } catch (err) {
        showNotice("Delete intent request failed", "error");
        console.error(err);
      }
    },
  });

  // Switch to intent lives on the cover stack hover control.
  return [editBtn, regenerateBtn, fillNowBtn, deleteBtn];
}

/**
 * @param {{ expanded?: boolean, onToggle?: () => void } | null} [toggle]
 * @returns {boolean} true when at least one assignment/editor row was appended
 */
function appendIntentAssignmentRows(
  frag,
  intent,
  assignments,
  durationByMixId,
  { toggle = null } = {},
) {
  const assignmentByDevice = new Map();
  for (const asg of assignments) {
    assignmentByDevice.set(String(asg.device_id), asg);
  }
  const editor = hoursEditorState.get(intent.id);
  const hours = intent.device_hours || [];

  /** @type {Array<{ kind: "assignment", dh: object } | { kind: "editor" }>} */
  const specs = [];
  for (const dh of hours) {
    const editingThis =
      editor && editor.mode === "edit" && editor.deviceId === dh.device_id;
    if (!editingThis) specs.push({ kind: "assignment", dh });
  }
  if (editor) specs.push({ kind: "editor" });

  for (let i = 0; i < specs.length; i += 1) {
    const spec = specs[i];
    const isLast = i === specs.length - 1;
    const tr = document.createElement("tr");
    tr.dataset.intentId = intent.id;

    if (isLast && toggle) {
      appendIntentToggleLeadCells(tr, toggle);
    } else {
      appendIntentLeadCells(tr);
    }

    if (spec.kind === "assignment") {
      const dh = spec.dh;
      tr.className = "intent-assignment-row";

      const summary = document.createElement("td");
      summary.className = "intent-assignment-cell muted";
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
      const branch = document.createElement("span");
      branch.className = "intent-assignment-branch";
      branch.setAttribute("aria-hidden", "true");
      branch.textContent = "↦";
      const label = document.createElement("span");
      label.className = "intent-assignment-label";
      label.textContent = `${deviceName(dh.device_id)}: ${formatDuration(
        dh.budget_seconds,
      )}${outcomeText}${expiryText}`;
      summary.appendChild(branch);
      summary.appendChild(label);
      tr.appendChild(summary);

      const actions = document.createElement("td");
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
        const deleteBtn = document.createElement("button");
        deleteBtn.type = "button";
        bindConfirmDelete(deleteBtn, {
          label: "Remove hours",
          onConfirm: () => deleteDeviceHours(intent, dh.device_id),
        });
        appendIntentActions(actions, editBtn, deleteBtn);
      } else {
        appendIntentActions(actions);
      }
      tr.appendChild(actions);
    } else {
      tr.className = "intent-hours-editor-row";
      const editorCell = document.createElement("td");
      editorCell.colSpan = 2;
      editorCell.className = "intent-hours-editor-cell";
      editorCell.appendChild(buildHoursEditor(intent, editor));
      tr.appendChild(editorCell);
    }

    frag.appendChild(tr);
  }

  return specs.length > 0;
}

async function refreshIntents({ force = false } = {}) {
  const body = document.getElementById("intent-table-body");
  if (!body) return;
  if (!force && focusInside(body)) return;
  await refreshIntentArtistOptions();
  const res = await fetch("/api/intents");
  const data = await res.json();
  if (editComposer) {
    editComposer.destroy();
    editComposer = null;
  }
  if (
    editingIntentId &&
    !(data.intents || []).some((intent) => intent.id === editingIntentId)
  ) {
    editingIntentId = null;
  }

  const allIntents = data.intents || [];
  const intents = allIntents.filter(intentMatchesListFilters);
  const seqByIntentId = new Map();
  if (intents.length) {
    const seqResults = await Promise.all(
      intents.map(async (intent) => {
        try {
          const seqRes = await fetch(`/api/intents/${intent.id}/sequence`);
          if (!seqRes.ok) return [intent.id, null];
          return [intent.id, await seqRes.json()];
        } catch (err) {
          console.error(err);
          return [intent.id, null];
        }
      }),
    );
    for (const [id, seq] of seqResults) {
      seqByIntentId.set(id, seq);
    }
  }

  const frag = document.createDocumentFragment();
  let pendingEditFocus = null;

  if (!intents.length) {
    const tr = document.createElement("tr");
    tr.className = "intent-empty-row";
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "muted";
    const filtersActive =
      intentListFilterTags.length ||
      intentListFilterArtistIds.length ||
      intentListFilterPlatforms.length ||
      intentNameFilter.trim();
    td.textContent =
      !allIntents.length
        ? "No intents yet"
        : filtersActive
          ? "No intents match filters"
          : "No intents yet";
    tr.appendChild(td);
    frag.appendChild(tr);
  }

  for (const intent of intents) {
    const isEditing = editingIntentId === intent.id;
    const seq = seqByIntentId.get(intent.id) || null;
    const coverIds = intentCoverMixIds(seq);
    const seqExpanded = expandedIntentSequences.has(intent.id);
    const coverToggle =
      seq && !isEditing
        ? {
            expanded: seqExpanded,
            onToggle: () => toggleIntentSequence(intent.id),
          }
        : null;
    let assignments = [];
    const durationByMixId = new Map();
    if (seq) {
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

    if (isEditing) {
      const editRow = document.createElement("tr");
      editRow.className = "intent-edit-row";
      editRow.dataset.intentId = intent.id;
      editRow.appendChild(renderIntentCoverStack(coverIds));
      const composerCell = document.createElement("td");
      composerCell.className = "intent-composer-cell";
      const composerMount = document.createElement("div");
      composerMount.className = "intent-composer intent-composer-edit";
      composerCell.appendChild(composerMount);
      editRow.appendChild(composerCell);
      const actions = document.createElement("td");
      appendIntentActions(actions);
      editRow.appendChild(actions);
      frag.appendChild(editRow);

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
          try {
            const res = await fetch(`/api/intents/${intent.id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(values),
            });
            const data = await res.json();
            if (!res.ok) {
              const detail = data.detail;
              showNotice(
                typeof detail === "string"
                  ? detail
                  : detail?.[0]?.msg || "Update intent failed",
                "error",
              );
              return;
            }
            const filling = data.fill_in_progress ? " · filling caches…" : "";
            showNotice(`Updated “${data.intent.name}”${filling}`, "ok");
            editingIntentId = null;
            if (editComposer) {
              editComposer.destroy();
              editComposer = null;
            }
            await refreshIntents({ force: true });
            await refreshFiles();
          } catch (err) {
            showNotice("Update intent request failed", "error");
            console.error(err);
          }
        },
        onCancel() {
          cancelInlineIntentEdit();
        },
      });
      pendingEditFocus = editComposer;
    } else {
      const nameRow = document.createElement("tr");
      nameRow.className = "intent-name-row";
      nameRow.dataset.intentId = intent.id;
      const coverCell = renderIntentCoverStack(coverIds, { intent });
      coverCell.rowSpan = 2;
      nameRow.appendChild(coverCell);

      const nameCell = document.createElement("td");
      nameCell.className = "intent-name-cell";
      const nameInner = document.createElement("div");
      nameInner.className = "intent-name-inner";
      const heading = document.createElement("span");
      heading.className = "intent-name";
      heading.textContent = intent.name;
      nameInner.appendChild(heading);
      const chancesEl = document.createElement("span");
      chancesEl.className = "intent-name-chances has-tip muted";
      chancesEl.textContent = formatChanceBlocks(intent.distribution);
      chancesEl.dataset.tip = formatChancePercents(intent.distribution);
      nameInner.appendChild(chancesEl);
      nameCell.appendChild(nameInner);
      nameRow.appendChild(nameCell);

      const nameActions = document.createElement("td");
      appendIntentActions(nameActions, ...buildIntentActionButtons(intent));
      nameRow.appendChild(nameActions);
      frag.appendChild(nameRow);

      const metaRow = document.createElement("tr");
      metaRow.className = "intent-meta-row";
      metaRow.dataset.intentId = intent.id;

      const filtersCell = document.createElement("td");
      filtersCell.className = "intent-filters-cell";
      const tags = intent.tags || [];
      const artistIds = intent.artist_ids || [];
      const artistNames = artistIds.map(
        (id) => artistNameById.get(id) || "(deleted)",
      );
      const filterPlatforms = intentFilterPlatforms(intent.platforms);
      if (!tags.length && !artistNames.length && !filterPlatforms.length) {
        filtersCell.classList.add("muted");
        filtersCell.textContent = "—";
      } else {
        let needSep = false;
        if (tags.length) {
          filtersCell.appendChild(
            renderTagChipsDisplay(tags, catalogTagsCache),
          );
          needSep = true;
        }
        if (artistNames.length) {
          if (needSep) filtersCell.appendChild(intentMetaSep());
          const artistsEl = document.createElement("span");
          artistsEl.className = "intent-filter-artists muted";
          artistsEl.textContent = artistNames.join(", ");
          filtersCell.appendChild(artistsEl);
          needSep = true;
        }
        if (filterPlatforms.length) {
          if (needSep) filtersCell.appendChild(intentMetaSep());
          const platformsEl = document.createElement("span");
          platformsEl.className = "intent-filter-platforms";
          platformsEl.setAttribute("aria-label", "Sources");
          appendIntentPlatformSymbols(platformsEl, filterPlatforms);
          filtersCell.appendChild(platformsEl);
        }
      }
      metaRow.appendChild(filtersCell);

      const metaActions = document.createElement("td");
      const editor = hoursEditorState.get(intent.id);
      if (!editor) {
        const assignBtn = document.createElement("button");
        assignBtn.type = "button";
        setSymbolButton(assignBtn, BTN.add, "Add assignment");
        assignBtn.addEventListener("click", () => {
          hoursEditorState.set(intent.id, { mode: "add" });
          // Peers may have landed while a long fill held SSE; refresh before render.
          void (async () => {
            await refreshPeers();
            await refreshIntents({ force: true });
          })();
        });
        appendIntentActions(metaActions, assignBtn);
      } else {
        appendIntentActions(metaActions);
      }
      metaRow.appendChild(metaActions);
      frag.appendChild(metaRow);
    }

    const hasAssignmentRows = appendIntentAssignmentRows(
      frag,
      intent,
      assignments,
      durationByMixId,
      { toggle: coverToggle },
    );
    // No assignment/editor rows: dedicated row for the toggle (and full-width rule).
    if (!hasAssignmentRows) {
      appendIntentToggleRow(frag, intent, coverToggle);
    }
    if (seqExpanded && seq) {
      appendIntentSequenceRows(frag, intent, seq);
    }

    let blockEnd = null;
    for (const node of frag.children) {
      if (node.dataset?.intentId === intent.id) blockEnd = node;
    }
    if (blockEnd) blockEnd.classList.add("intent-block-end");
  }

  const intentPane = focusPaneScrollEl("intents");
  const savedPaneScroll = intentPane ? intentPane.scrollTop : 0;
  body.replaceChildren(frag);
  if (intentPane) intentPane.scrollTop = savedPaneScroll;
  pendingEditFocus?.focusName();
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
    showNotice("Could not copy PIN — select and copy manually", "warn");
  }
}

async function startPairSession() {
  try {
    const res = await fetch("/api/pair/session/start", { method: "POST" });
    let data = null;
    try {
      data = await res.json();
    } catch (parseErr) {
      showNotice(`Could not start pairing (HTTP ${res.status})`, "error");
      console.error(parseErr);
      return;
    }
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`;
      showNotice(detail || "Could not start pairing", "error");
      return;
    }
    setPairSessionHint("Share the PIN (or QR) with the other device");
    renderPairSession(data);
  } catch (err) {
    showNotice("Could not start pairing", "error");
    console.error(err);
  }
}

async function cancelPairSession() {
  try {
    await fetch("/api/pair/session/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    setPairSessionHint("");
    showNotice("Pairing cancelled", "ok");
    renderPairSession({ active: false });
  } catch (err) {
    showNotice("Cancel failed", "error");
    console.error(err);
  }
}

async function confirmPairSession() {
  try {
    const res = await fetch("/api/pair/session/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await res.json();
    if (!res.ok) {
      showNotice(data.detail || "Confirm failed", "error");
      return;
    }
    if (data.complete && data.peer) {
      setPairSessionHint("");
      showNotice(`Paired with ${data.peer.name}`, "ok");
      renderPairSession(data.session || { active: false });
      collapsePairForm();
      await refreshPeers();
      await refreshIntents({ force: true });
      stopPairPoll();
      return;
    }
    setPairSessionHint("Waiting for the other device to Confirm…");
    if (data.session) {
      renderPairSession(data.session);
    }
  } catch (err) {
    showNotice("Confirm failed", "error");
    console.error(err);
  }
}

async function joinPairSession({ peer_url, pin, session_id }) {
  try {
    const res = await fetch("/api/pair/session/join-remote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ peer_url, pin, session_id: session_id || null }),
    });
    const data = await res.json();
    if (!res.ok) {
      showNotice(data.detail || "Join failed", "error");
      return false;
    }
    setPairSessionHint("Compare the confirm code, then Confirm on both devices");
    renderPairSession(data);
    return true;
  } catch (err) {
    showNotice("Join failed", "error");
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
    setPairSessionHint("");
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
  const peerUrl = document.getElementById("peer-url").value.trim();
  const pin = document.getElementById("pair-code").value.trim();
  if (!peerUrl || !pin) {
    showNotice("Peer URL and PIN are required", "warn");
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
  let payload;
  try {
    payload = JSON.parse(rawText);
  } catch (err) {
    showNotice("Scanned QR is not a pairing offer", "error");
    return;
  }
  if (!payload || typeof payload !== "object" || payload.v !== 2 || !payload.pin || !payload.url) {
    showNotice("Scanned QR is not an ephemeral pairing offer", "error");
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
  if (!window.isSecureContext) {
    setPairSessionHint("Camera scan needs HTTPS or localhost; use short code instead");
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    setPairSessionHint("Camera not available; use short code instead");
    return;
  }
  if (typeof BarcodeDetector === "undefined") {
    setPairSessionHint("QR scan not supported in this browser; use short code instead");
    return;
  }
  let detector;
  try {
    detector = new BarcodeDetector({ formats: ["qr_code"] });
  } catch (err) {
    setPairSessionHint("QR scan not supported in this browser; use short code instead");
    console.error(err);
    return;
  }
  stopPairScan();
  setPairSessionHint("Starting camera…");
  try {
    pairScanStream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: "environment" } },
    });
  } catch (err) {
    setPairSessionHint("Camera permission denied; use short code instead");
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
    showNotice("Could not start camera preview", "error");
    console.error(err);
    return;
  }
  setPairSessionHint("Point at the other device's QR…");
  tickPairScan(detector);
}

document.getElementById("pair-scan-btn").addEventListener("click", () => {
  startPairScan();
});
document.getElementById("pair-scan-stop").addEventListener("click", () => {
  stopPairScan();
  setPairSessionHint("Scan stopped");
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
  },
});

document.getElementById("artists-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitBtn = document.getElementById("artists-submit");
  const refreshBtn = document.getElementById("refresh-all-artists");
  if (submitBtn?.disabled) return;
  const raw = document.getElementById("artist-urls").value;
  const urls = raw
    .split(/[\s,]+/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!urls.length) return;
  const min_duration_seconds = minDurationSecondsFromForm();
  if (submitBtn) submitBtn.disabled = true;
  if (refreshBtn) refreshBtn.disabled = true;
  try {
    const res = await fetch("/api/artists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls, min_duration_seconds }),
    });
    const data = await res.json();
    if (!res.ok) {
      showNotice(data.detail || "Add artists failed", "error");
      return;
    }
    showNotice(`Added ${data.added} releases · ${data.artists} artists`, "ok");
    document.getElementById("artist-urls").value = "";
    artistsCollapsible?.collapse();
    await refreshMixes();
    await refreshIntentArtistOptions();
  } catch (err) {
    showNotice("Add artists request failed", "error");
    console.error(err);
  } finally {
    if (submitBtn) submitBtn.disabled = false;
    if (refreshBtn) refreshBtn.disabled = false;
  }
});

document.getElementById("refresh-all-artists").addEventListener("click", async () => {
  const submitBtn = document.getElementById("artists-submit");
  const refreshBtn = document.getElementById("refresh-all-artists");
  if (refreshBtn?.disabled) return;
  if (refreshBtn) refreshBtn.disabled = true;
  if (submitBtn) submitBtn.disabled = true;
  try {
    const data = await postRefreshArtists(null);
    if (!data.ok) {
      showNotice(data.detail || "Refresh artists failed", "error");
      return;
    }
    showNotice(
      `Refreshed · ${data.added} new release(s) · ${data.artists} artists`,
      "ok",
    );
    await refreshMixes();
    await refreshIntentArtistOptions();
  } catch (err) {
    showNotice("Refresh artists request failed", "error");
    console.error(err);
  } finally {
    if (refreshBtn) refreshBtn.disabled = false;
    if (submitBtn) submitBtn.disabled = false;
  }
});

document.getElementById("intent-expand")?.addEventListener("click", () => {
  expandCreateForm();
});
document.getElementById("intent-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
});

document.getElementById("sync-btn").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/sync", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      showNotice(data.detail || "Sync failed", "error");
      return;
    }
    showNotice(
      data.fill_in_progress
        ? `Synced · ${data.peers} peers · ${data.mixes} releases · filling caches…`
        : `Synced · ${data.peers} peers · ${data.mixes} releases · ${data.files} cached`,
      "ok",
    );
    await refreshPeers();
    await refreshMixes();
    await refreshIntents();
    await refreshFiles();
  } catch (err) {
    showNotice("Sync request failed", "error");
    console.error(err);
  }
});

document.getElementById("metered-toggle").addEventListener("change", async (event) => {
  const metered = event.target.checked;
  try {
    const res = await fetch("/api/metered", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metered }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showNotice(data.detail || "Metered switch failed", "error");
      event.target.checked = !metered;
      return;
    }
    showNotice(
      data.metered
        ? "Metered · origin capped to current + one ahead"
        : "Unmetered · standing fill uses full hours",
      "ok",
    );
  } catch (err) {
    showNotice("Metered switch request failed", "error");
    event.target.checked = !metered;
    console.error(err);
  }
});

document.getElementById("player-play").addEventListener("click", async () => {
  const btn = document.getElementById("player-play");
  try {
    if (btn.dataset.playing === "true" || lastPlayerPlaying) {
      // Pause whatever intent is actually playing, independent of the dropdown.
      await pausePlayback();
      return;
    }
    await playIntent(document.getElementById("player-intent").value);
  } catch (err) {
    showNotice("Play request failed", "error");
    console.error(err);
  }
});

document.getElementById("playlog-intent-play")?.addEventListener("click", async () => {
  const intentId = document.getElementById("player-intent")?.value || "";
  try {
    if (intentId && isIntentCurrentlyPlaying(intentId)) {
      await pausePlayback();
      return;
    }
    await playIntent(intentId);
  } catch (err) {
    showNotice("Play now request failed", "error");
    console.error(err);
  }
});

document.getElementById("player-mark").addEventListener("click", async () => {
  const intentId = document.getElementById("player-intent").value;
  try {
    const body = intentId ? { intent_id: intentId } : {};
    const res = await fetch("/api/player/mark-played", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showNotice(data.detail || "Mark played failed", "error");
      return;
    }
    showNotice("Marked played", "ok");
    lastPlayheadCommitAt = Date.now();
    playheadPlayedNotifiedForMix = data.mix?.id || null;
    await refreshPlayer();
    await refreshFiles();
  } catch (err) {
    showNotice("Mark played request failed", "error");
    console.error(err);
  }
});

document.getElementById("player-skip").addEventListener("click", async () => {
  const intentId = document.getElementById("player-intent").value;
  try {
    const body = intentId ? { intent_id: intentId } : {};
    const res = await fetch("/api/player/skip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showNotice(data.detail || "Skip failed", "error");
      return;
    }
    lastPlayheadCommitAt = Date.now();
    playheadPlayedNotifiedForMix = null;
    await refreshPlayer();
    await refreshFiles();
  } catch (err) {
    showNotice("Skip request failed", "error");
    console.error(err);
  }
});

document.getElementById("player-stop").addEventListener("click", async () => {
  try {
    await fetch("/api/player/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    showNotice("Stopped", "ok");
    lastPlayheadCommitAt = Date.now();
    playheadPlayedNotifiedForMix = null;
    lastKnownPositionSeconds = 0;
    await refreshPlayer();
  } catch (err) {
    showNotice("Stop request failed", "error");
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
    syncPlayerCurrentTrackFromPosition(position);
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

async function rateCurrentPlayerMix(stars) {
  const mixId = currentMixId;
  if (!mixId) {
    showNotice("Nothing to rate", "warn");
    throw new Error("Nothing to rate");
  }
  const res = await fetch(`/api/mixes/${mixId}/rate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stars: Number(stars) }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showNotice(data.detail || "Rate failed", "error");
    throw new Error(data.detail || "Rate failed");
  }
  void refreshAfterAnnotateMutation();
}

document.getElementById("catalog-show-rejected")?.addEventListener("click", async (event) => {
  const btn = event.currentTarget;
  showRejectedCatalog = btn.getAttribute("aria-pressed") !== "true";
  syncRejectedToggle(btn, showRejectedCatalog);
  await refreshAffectedSurfaces(["mixes"], { force: true });
});

/** Notice section taxonomy mirrored from DeviceAgent UI view notices. */
const VIEW_NOTICE_SECTIONS = [
  "mixes",
  "playlog",
  "intents",
  "peers",
  "cache",
  "activity",
  "pairing_session",
  "player",
];

/**
 * Shared surface refresh. User mutations pass `{ force: true }` so open editors
 * remount; View notices omit force so focusInside editors are preserved.
 */
async function refreshAffectedSurfaces(sections, { force = false } = {}) {
  const wanted = new Set(sections);
  if (wanted.has("mixes")) {
    await refreshMixes({ force });
  }
  if (wanted.has("playlog") && !wanted.has("mixes")) {
    // refreshMixes already refreshes Playlog when mixes are included.
    await refreshPlaylog({ force });
  }
  if (wanted.has("intents")) {
    await refreshIntents({ force });
  }
  if (wanted.has("peers")) {
    await refreshPeers();
    // Device picker for Add assignment is derived from peersCache.
    if (hoursEditorState.size) {
      await refreshIntents({ force });
    }
  }
  if (wanted.has("cache")) {
    // Progress ticks are CACHE-only; Playlog bars patch from the files snapshot.
    // Download start/end also mark playlog so full remount happens via that branch.
    await refreshFiles({ force });
  }
  if (wanted.has("activity")) {
    await refreshActivity();
  }
  if (wanted.has("pairing_session")) {
    await refreshPairingSession();
  }
  if (wanted.has("player")) {
    await refreshPlayer();
    if (!wanted.has("playlog") && !wanted.has("mixes") && !wanted.has("cache")) {
      await refreshPlaylog({ force });
    }
  }
}

async function refreshAllViewSurfaces() {
  // No force: respect focusInside so tag/hours editors are not remounted mid-edit.
  await refreshAffectedSurfaces(VIEW_NOTICE_SECTIONS);
}

async function refreshViewSections(sections) {
  // Live notices must not force-rebuild while a tag input has focus.
  await refreshAffectedSurfaces(sections);
}

/** After annotate mutations: force Catalog/playlog so editors remount with new state. */
async function refreshAfterAnnotateMutation({ intents = false } = {}) {
  const sections = ["mixes", "playlog"];
  if (intents) sections.push("intents");
  await refreshAffectedSurfaces(sections, { force: true });
  await refreshPlayer();
}

/** After Switch to intent / Pause from an Intent row (and Player transport play/pause). */
async function refreshAfterIntentPlaybackMutation({ markedPlayed = false } = {}) {
  await refreshPlayer();
  await refreshPlaylog({ force: true });
  if (!markedPlayed) return;
  await refreshAffectedSurfaces(["cache", "mixes", "playlog", "intents"], {
    force: true,
  });
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
  initAppMenu();
  initFocusTabs();
  initActionTips();
  const expandBtn = document.getElementById("intent-expand");
  if (expandBtn) setSymbolButton(expandBtn, BTN.add, "Create intent");
  const playerStarsRoot = document.getElementById("player-stars");
  const playerTagRoot = document.getElementById("player-tag-editor");
  const playerRejectBtn = document.getElementById("player-reject");
  if (playerStarsRoot && playerTagRoot && playerRejectBtn) {
    playerAnnotateKit = mountAnnotateKit({
      surface: "player",
      starsRoot: playerStarsRoot,
      tagRoot: playerTagRoot,
      rejectBtn: playerRejectBtn,
      getMixId: () => currentMixId,
      async onRate(stars) {
        try {
          await rateCurrentPlayerMix(stars);
        } catch (err) {
          const notice = document.getElementById("player-notice");
          if (!notice?.textContent) {
            showNotice("Rate request failed", "error");
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
  mountIntentListFilters();
  resetIntentListFilters();
  mountCacheNameFilter();
  resetCacheNameFilter();
  await refreshHealth();
  await refreshActivity();
  await refreshPairing();
  await refreshPeers();
  await refreshMixes();
  await refreshFiles();
  await refreshIntents();
  await refreshPlayerIntents();
  await refreshPlayer();
  ensurePlayerCollapseSpacer();
  syncPlayerChrome();
  syncPlayerCollapse();
  syncFocusTabsHeightVar();
  ensurePlaylogScrollChrome();
  ensureFocusPaneScrollCollapse();
  syncFocusScrollHomeBtn();
  window.addEventListener("resize", () => {
    syncPlayerChrome();
    schedulePlayerCollapse();
    syncFocusTabsHeightVar();
    updatePlaylogStickyMetrics();
    syncPlaylogCurrentStuck();
  });
  if (typeof ResizeObserver === "function") {
    // Soft collapse already drives scale/labels on scroll; RO only reflows
    // natural cover + clip, then re-applies collapse (no hard stage snaps).
    const chromeObserver = new ResizeObserver(() => {
      syncPlayerNowStack();
      schedulePlayerCollapse();
      syncFocusTabsHeightVar();
    });
    const playerEl = document.getElementById("player");
    if (playerEl) chromeObserver.observe(playerEl);
    const playerNowRow = document.querySelector("#player .player-now-row");
    if (playerNowRow) chromeObserver.observe(playerNowRow);
    const focusTabs = document.querySelector("#focus .focus-tabs");
    if (focusTabs) chromeObserver.observe(focusTabs);
    for (const toolbar of document.querySelectorAll("#focus .focus-toolbar")) {
      chromeObserver.observe(toolbar);
    }
    const playlogWrap = document.getElementById("playlog-table-wrap");
    if (playlogWrap) {
      const playlogObserver = new ResizeObserver(() => {
        updatePlaylogStickyMetrics();
        syncPlaylogCurrentStuck();
      });
      playlogObserver.observe(playlogWrap);
    }
  }
  connectViewNotices();
})();
