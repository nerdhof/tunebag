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
/** @type {ReturnType<typeof mountTagEditor> | null} */
let intentTagEditor = null;

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
  btn.textContent = symbol;
  btn.removeAttribute("title");
  btn.setAttribute("aria-label", label);
  btn.dataset.tip = label;
}

/** @type {string[]} */
let catalogTagsCache = [];

function normalizeTag(tag) {
  return String(tag || "")
    .trim()
    .toLowerCase();
}

/** FNV-1a → stable soft HSL border/fill for a tag (same tag ⇒ same color). */
function tagChipColors(tag) {
  let hash = 2166136261;
  for (let i = 0; i < tag.length; i += 1) {
    hash ^= tag.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  hash >>>= 0;
  const hue = hash % 360;
  const sat = 48 + ((hash >>> 9) % 22); // 48–69%
  const border = `hsl(${hue} ${sat}% 42%)`;
  const fill = `hsl(${hue} ${sat}% 52% / 0.18)`;
  return [border, fill];
}

/**
 * Chip tag editor: thin colored chips, confirm-to-remove, + picker.
 * @param {HTMLElement} root
 * @param {{
 *   tags?: string[],
 *   onAdd: (tag: string) => Promise<void> | void,
 *   onRemove: (tag: string) => Promise<void> | void,
 *   getCatalogTags?: () => string[],
 * }} options
 */
function mountTagEditor(root, options) {
  const getCatalogTags = options.getCatalogTags || (() => catalogTagsCache);
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
      item.className = "tag-suggest";
      if (index === highlightIndex) item.classList.add("is-active");
      if (row.create) item.classList.add("is-create");
      const [border, fill] = tagChipColors(row.tag);
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
    const frag = document.createDocumentFragment();
    for (const tag of tags) {
      const [border, fill] = tagChipColors(tag);
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
      if (confirming === tag) {
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
          armConfirm(tag);
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
let intentCollapsible = null;
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
  // Tag chip × / + keep aria-label for a11y but only tip when armed (data-tip set).
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

function updateChanceSummary() {
  const summary = document.querySelector("#intent-chances > summary");
  if (!summary) return;
  const chances = readChances();
  summary.textContent = `Rating chances: ${formatChanceBlocksFromPct(chances)}`;
  summary.removeAttribute("title");
  summary.classList.add("has-tip");
  summary.dataset.tip = formatChancePercentsFromPct(chances);
}

function snapChancePct(n) {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n / 10) * 10));
}

function readChances() {
  const chances = {};
  for (const id of CHANCE_IDS) {
    chances[id] = Number(document.getElementById(id).value);
  }
  return chances;
}

function writeChances(chances) {
  for (const id of CHANCE_IDS) {
    document.getElementById(id).value = String(chances[id]);
  }
  updateChanceSummary();
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

function rebalanceChances(changedId) {
  const chances = readChances();
  let total = sumChances(chances);
  if (total === 100) {
    updateChanceSummary();
    return;
  }

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
      // five was capped; put leftover on next ratings high→low
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
  writeChances(chances);
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

function initChanceSelects() {
  for (const id of CHANCE_IDS) {
    const select = document.getElementById(id);
    fillChanceSelect(select, CHANCE_DEFAULTS[id]);
    select.addEventListener("change", () => rebalanceChances(id));
  }
  updateChanceSummary();
}

function setChancesFromDist(dist) {
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
  writeChances(chances);
}

const DEFAULT_INTENT_PLATFORMS = ["soundcloud", "hearthisat", "bandcamp", "youtube"];
const PLATFORM_LABELS = {
  soundcloud: "SoundCloud",
  hearthisat: "hearthis.at",
  bandcamp: "Bandcamp",
  youtube: "YouTube",
};

function clearIntentArtistSelection() {
  const select = document.getElementById("intent-artists");
  if (!select) return;
  for (const option of select.options) {
    option.selected = false;
  }
}

function selectedIntentArtistIds() {
  const select = document.getElementById("intent-artists");
  if (!select) return [];
  return Array.from(select.selectedOptions).map((option) => option.value);
}

function setIntentArtistSelection(artistIds) {
  const select = document.getElementById("intent-artists");
  if (!select) return;
  const wanted = new Set(artistIds || []);
  for (const option of select.options) {
    option.selected = wanted.has(option.value);
  }
}

function intentPlatformButtons() {
  return Array.from(document.querySelectorAll("#intent-platforms .source-toggle"));
}

function selectedIntentPlatforms() {
  return intentPlatformButtons()
    .filter((btn) => btn.getAttribute("aria-pressed") === "true")
    .map((btn) => btn.dataset.platform)
    .filter(Boolean);
}

function setIntentPlatformSelection(platforms) {
  const wanted = new Set(
    platforms && platforms.length ? platforms : DEFAULT_INTENT_PLATFORMS,
  );
  for (const btn of intentPlatformButtons()) {
    const on = wanted.has(btn.dataset.platform);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }
}

function resetIntentPlatformSelection() {
  setIntentPlatformSelection(DEFAULT_INTENT_PLATFORMS);
}

function bindIntentPlatformToggles() {
  const root = document.getElementById("intent-platforms");
  if (!root || root.dataset.bound === "1") return;
  root.dataset.bound = "1";
  root.addEventListener("click", (event) => {
    const btn = event.target.closest(".source-toggle");
    if (!btn || !root.contains(btn)) return;
    const pressed = btn.getAttribute("aria-pressed") === "true";
    if (pressed) {
      const activeCount = selectedIntentPlatforms().length;
      if (activeCount <= 1) return;
      btn.setAttribute("aria-pressed", "false");
      return;
    }
    btn.setAttribute("aria-pressed", "true");
  });
}

async function refreshIntentArtistOptions() {
  const select = document.getElementById("intent-artists");
  if (!select) return;
  const previouslySelected = new Set(selectedIntentArtistIds());
  try {
    const res = await fetch("/api/artists");
    const data = await res.json();
    const artists = data.artists || [];
    artistNameById = new Map(artists.map((artist) => [artist.id, artist.name]));
    select.innerHTML = "";
    for (const artist of artists) {
      const option = document.createElement("option");
      option.value = artist.id;
      option.textContent = artist.name;
      option.selected = previouslySelected.has(artist.id);
      select.appendChild(option);
    }
  } catch (err) {
    console.error(err);
  }
}

function clearIntentFormFields() {
  document.getElementById("intent-edit-id").value = "";
  document.getElementById("intent-name").value = "";
  intentTagEditor?.setTags([]);
  clearIntentArtistSelection();
  resetIntentPlatformSelection();
  writeChances({ ...CHANCE_DEFAULTS });
  document.getElementById("intent-chances").open = false;
}

function resetIntentForm() {
  clearIntentFormFields();
  intentCollapsible?.collapse();
}

function hoursUntilExpiry(iso) {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms)) return "";
  if (ms <= 0) return "0";
  return String(Math.round((ms / 3600000) * 10) / 10);
}

function beginEditIntent(intent) {
  document.getElementById("intent-edit-id").value = intent.id;
  document.getElementById("intent-name").value = intent.name;
  intentTagEditor?.setTags(intent.tags || []);
  setIntentArtistSelection(intent.artist_ids || []);
  setIntentPlatformSelection(intent.platforms || DEFAULT_INTENT_PLATFORMS);
  setChancesFromDist(intent.distribution);
  document.getElementById("intent-chances").open = true;
  intentCollapsible?.expand({ submitLabel: "Save changes" });
  document.getElementById("intent-form").scrollIntoView({ behavior: "smooth", block: "start" });
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

function formatHms(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

let playerSeekDragging = false;
let playerPollTimer = null;
let playerSeekTracks = [];
let playerSeekArtist = "";
/** Stable key for current marks layout; skip DOM rebuild while unchanged. */
let playerSeekMarksKey = "";
/** Track index currently highlighted (−1 = none). Survives poll refreshes. */
let playerSeekHotIndex = -1;

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

async function seekToPlayerPosition(positionSeconds) {
  const status = document.getElementById("player-status");
  const seekbar = document.getElementById("player-seekbar");
  const position = Math.max(0, Math.round(Number(positionSeconds) || 0));
  lastKnownPositionSeconds = position;
  lastPlayheadCommitAt = Date.now();
  if (seekbar) {
    seekbar.value = String(position);
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

function seekLabelHeadroomRem(tracks, artist) {
  let maxChars = 0;
  for (const track of tracks) {
    const text = displayTrackTitle(track.title, artist) || "";
    if (text.length > maxChars) maxChars = text.length;
  }
  // 0.7rem labels at −60°: vertical rise ≈ chars * charWidth * sin(60°) + gap.
  return Math.min(14, Math.max(3.5, maxChars * 0.28 + 0.7));
}

function setSeekLabelHeadroom(seekRow, tracks, artist) {
  if (!seekRow) return;
  if (!tracks || tracks.length < 2) {
    seekRow.classList.remove("has-track-labels");
    seekRow.style.removeProperty("--seek-label-headroom");
    return;
  }
  seekRow.classList.add("has-track-labels");
  seekRow.style.setProperty(
    "--seek-label-headroom",
    `${seekLabelHeadroomRem(tracks, artist)}rem`,
  );
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

function formatCacheOverview(overview) {
  const parts = ["cached", "loading", "pending"].map((status) => {
    const bucket = overview?.[status] || {
      count: 0,
      duration_seconds: 0,
      size_bytes: 0,
    };
    const detail =
      Number(bucket.size_bytes) > 0
        ? `${formatHms(bucket.duration_seconds)}, ${formatBytes(bucket.size_bytes)}`
        : formatHms(bucket.duration_seconds);
    return `${status}: ${bucket.count} (${detail})`;
  });
  return parts.join(", ");
}

function formatBytes(bytes) {
  const n = Math.max(0, Number(bytes) || 0);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  if (unit === 0) {
    return `${Math.round(value)} ${units[unit]}`;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
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
        mixes: [],
      };
      groups.set(artistId, group);
    } else if (!group.artistUrl && mix.artist_url) {
      group.artistUrl = mix.artist_url;
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
      td.colSpan = 5;
      td.className = "muted";
      td.textContent = "No releases yet";
      tr.appendChild(td);
      body.appendChild(tr);
      await refreshTagSuggestions();
      await refreshPlayHistory(data.mixes);
      return;
    }

    for (const group of groupMixesByArtist(data.mixes)) {
      const visibleMixes = showRejectedCatalog
        ? group.mixes
        : group.mixes.filter((mix) => !mix.rejected);
      const expanded = expandedCatalogArtists.has(group.artistId);
      const header = document.createElement("tr");
      header.className = "artist-row";
      header.dataset.artistId = group.artistId;
      header.dataset.expanded = expanded ? "true" : "false";
      header.setAttribute("aria-expanded", expanded ? "true" : "false");
      header.tabIndex = 0;
      header.setAttribute("role", "button");

      const artistCell = document.createElement("td");
      artistCell.colSpan = 5;
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
        const link = document.createElement("a");
        link.className = "artist-link";
        link.href = group.artistUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.removeAttribute("title");
        link.setAttribute("aria-label", "Open artist page");
        link.dataset.tip = "Open artist page";
        link.textContent = "↗";
        link.addEventListener("click", (event) => {
          event.stopPropagation();
        });
        artistLabel.appendChild(document.createTextNode(" "));
        artistLabel.appendChild(link);
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

        const blankArtist = document.createElement("td");
        blankArtist.textContent = "";
        tr.appendChild(blankArtist);

        const title = document.createElement("td");
        title.textContent = mix.title || "";
        tr.appendChild(title);

        const length = document.createElement("td");
        length.textContent = formatDuration(mix.duration_seconds || 0);
        tr.appendChild(length);

        const rating = document.createElement("td");
        const starsRoot = document.createElement("div");
        starsRoot.className = "stars-display";
        mountStarRating(starsRoot, { stars: mix.stars, interactive: false });
        rating.appendChild(starsRoot);
        tr.appendChild(rating);

        const tagsCell = document.createElement("td");
        const tagRow = document.createElement("div");
        tagRow.className = "tag-cell";

        const rejectBtn = document.createElement("button");
        rejectBtn.type = "button";
        rejectBtn.className = "catalog-reject";
        const undoBtn = document.createElement("button");
        undoBtn.type = "button";
        undoBtn.className = "catalog-undo-reject";
        const unRejectBtn = document.createElement("button");
        unRejectBtn.type = "button";
        unRejectBtn.className = "catalog-un-reject";
        setSymbolButton(rejectBtn, BTN.reject, "Reject release");
        setSymbolButton(undoBtn, BTN.cancel, "Undo reject");
        setSymbolButton(unRejectBtn, BTN.unreject, "Un-reject release");

        const pendingUntil = mix.reject_pending_until;
        if (pendingUntil) {
          rejectBtn.hidden = true;
          unRejectBtn.hidden = true;
          undoBtn.hidden = false;
          scheduleCatalogRejectRefresh(mix.id, pendingUntil);
        } else if (mix.rejected) {
          rejectBtn.hidden = true;
          undoBtn.hidden = true;
          unRejectBtn.hidden = false;
          clearCatalogRejectTimer(mix.id);
        } else {
          rejectBtn.hidden = false;
          undoBtn.hidden = true;
          unRejectBtn.hidden = true;
          clearCatalogRejectTimer(mix.id);
        }

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
        tagRow.appendChild(rejectBtn);
        tagRow.appendChild(undoBtn);
        tagRow.appendChild(unRejectBtn);

        const tagEditorRoot = document.createElement("div");
        tagEditorRoot.className = "tag-editor catalog-tag-editor";
        tagEditorRoot.addEventListener("click", (event) => event.stopPropagation());
        mountTagEditor(tagEditorRoot, {
          tags: mix.tags || [],
          ...mixTagHandlers(mix.id),
        });
        tagRow.appendChild(tagEditorRoot);
        tagsCell.appendChild(tagRow);
        tr.appendChild(tagsCell);
        body.appendChild(tr);
      }
    }
    await refreshTagSuggestions();
  }
  await refreshPlayHistory(data.mixes);
}

function formatLastHeard(ts) {
  if (!ts) return "";
  const match = String(ts).match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
  if (match) return `${match[1]} ${match[2]}`;
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
    starsRoot.className = "history-stars";
    starsRoot.setAttribute("aria-label", "Rate release");
    mountStarRating(starsRoot, {
      stars: mix.stars,
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
    ratingCell.appendChild(starsRoot);
    tr.appendChild(ratingCell);

    const tagsCell = document.createElement("td");
    const tagRow = document.createElement("div");
    tagRow.className = "tag-cell history-tag-cell";

    const rejectBtn = document.createElement("button");
    rejectBtn.type = "button";
    rejectBtn.className = "history-reject";
    const undoBtn = document.createElement("button");
    undoBtn.type = "button";
    undoBtn.className = "history-undo-reject";
    const unRejectBtn = document.createElement("button");
    unRejectBtn.type = "button";
    unRejectBtn.className = "history-un-reject";
    setSymbolButton(rejectBtn, BTN.reject, "Reject release");
    setSymbolButton(undoBtn, BTN.cancel, "Undo reject");
    setSymbolButton(unRejectBtn, BTN.unreject, "Un-reject release");

    const pendingUntil = mix.reject_pending_until;
    if (pendingUntil) {
      rejectBtn.hidden = true;
      unRejectBtn.hidden = true;
      undoBtn.hidden = false;
      scheduleCatalogRejectRefresh(mix.id, pendingUntil);
    } else if (mix.rejected) {
      rejectBtn.hidden = true;
      undoBtn.hidden = true;
      unRejectBtn.hidden = false;
      clearCatalogRejectTimer(mix.id);
    } else {
      rejectBtn.hidden = false;
      undoBtn.hidden = true;
      unRejectBtn.hidden = true;
      clearCatalogRejectTimer(mix.id);
    }

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
    tagRow.appendChild(rejectBtn);
    tagRow.appendChild(undoBtn);
    tagRow.appendChild(unRejectBtn);

    const tagEditorRoot = document.createElement("div");
    tagEditorRoot.className = "tag-editor history-tag-editor";
    tagEditorRoot.addEventListener("click", (event) => event.stopPropagation());
    mountTagEditor(tagEditorRoot, {
      tags: mix.tags || [],
      ...mixTagHandlers(mix.id),
      async onAdd(tag) {
        await mixTagHandlers(mix.id).onAdd(tag);
        await refreshMixes({ force: true });
        await refreshPlayer();
      },
      async onRemove(tag) {
        await mixTagHandlers(mix.id).onRemove(tag);
        await refreshMixes({ force: true });
        await refreshPlayer();
      },
    });
    tagRow.appendChild(tagEditorRoot);
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
        if (status) status.textContent = `Playing “${data.mix.title}”`;
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
  const undoBtn = document.getElementById("player-undo-reject");
  const rejectBtn = document.getElementById("player-reject");
  const status = document.getElementById("player-reject-status");
  if (!undoBtn || !rejectBtn || !status) return;
  const until = data.reject_pending_until;
  clearRejectUndoTimer();
  if (until && data.current_mix_id) {
    undoBtn.hidden = false;
    rejectBtn.hidden = true;
    status.hidden = false;
    status.textContent = "Reject pending — undo available for a few seconds";
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
    if (data.rejected) {
      status.hidden = false;
      status.textContent = "Rejected";
    } else {
      status.hidden = true;
      status.textContent = "";
    }
  }
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
  if (status) status.textContent = `Playing “${data.mix.title}”`;
  lastPlayheadCommitAt = Date.now();
  playheadPlayedNotifiedForMix = null;
  await refreshPlayer();
  await refreshFiles();
  return true;
}

async function refreshPlayer() {
  const res = await fetch("/api/player");
  const data = await res.json();
  const now = document.getElementById("player-now");
  if (!now) return;
  currentMixId = data.current_mix_id || null;
  if (!data.current_mix_id) {
    now.textContent = "Nothing playing";
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
  const title = data.title || "Untitled";
  const artist = data.artist || "Unknown";
  const label = `${artist} - ${title}`;
  now.textContent =
    data.size_bytes != null && Number(data.size_bytes) > 0
      ? `${label} (${formatBytes(data.size_bytes)})`
      : label;
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
    td.colSpan = 7;
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
    intentCell.colSpan = 7;
    const toggle = document.createElement("span");
    toggle.className = "cache-intent-toggle";
    toggle.setAttribute("aria-hidden", "true");
    toggle.textContent = expanded ? "▼" : "▶";
    intentCell.appendChild(toggle);
    const heading = document.createElement("span");
    heading.className = "cache-intent-name";
    heading.textContent = group.name || "Intent";
    intentCell.appendChild(heading);
    const overview = document.createElement("span");
    overview.className = "cache-intent-overview muted";
    overview.textContent = formatCacheOverview(group.overview);
    intentCell.appendChild(overview);
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

      const blankIntent = document.createElement("td");
      blankIntent.textContent = "";
      tr.appendChild(blankIntent);

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
    const deviceLabel = document.createElement("label");
    deviceLabel.className = "inline-field";
    deviceLabel.textContent = "Device";
    deviceSelect = document.createElement("select");
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
    deviceLabel.appendChild(deviceSelect);
    wrap.appendChild(deviceLabel);
  } else {
    const deviceLabel = document.createElement("label");
    deviceLabel.className = "inline-field";
    deviceLabel.textContent = "Device";
    const fixed = document.createElement("input");
    fixed.type = "text";
    fixed.value = deviceName(fixedDeviceId);
    fixed.readOnly = true;
    deviceLabel.appendChild(fixed);
    wrap.appendChild(deviceLabel);
  }

  const hoursLabel = document.createElement("label");
  hoursLabel.className = "inline-field";
  hoursLabel.textContent = "Hours";
  const hoursInput = document.createElement("input");
  hoursInput.type = "number";
  hoursInput.min = "0.5";
  hoursInput.step = "0.5";
  hoursInput.value = defaultHours;
  hoursLabel.appendChild(hoursInput);
  wrap.appendChild(hoursLabel);

  const expiresLabel = document.createElement("label");
  expiresLabel.className = "inline-field";
  expiresLabel.textContent = "Expires in (hours)";
  const expiresInput = document.createElement("input");
  expiresInput.type = "number";
  expiresInput.min = "0";
  expiresInput.step = "0.5";
  expiresInput.placeholder = "never";
  expiresInput.value = defaultExpires;
  expiresLabel.appendChild(expiresInput);
  wrap.appendChild(expiresLabel);

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

function renderDeviceHoursPanel(intent, assignments = []) {
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
      const mixText = asg ? ` · ${asg.mix_ids.length} releases` : "";
      label.textContent = `${deviceName(dh.device_id)}: ${formatDuration(
        dh.budget_seconds,
      )}${mixText}${expiryText}`;
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
  list.innerHTML = "";
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
          if (document.getElementById("intent-edit-id").value === intent.id) {
            resetIntentForm();
          }
          hoursEditorState.delete(intent.id);
          status.textContent = `Deleted “${intent.name}”`;
          await refreshIntents();
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
    tagsEl.textContent = `Tags: ${intent.tags.length ? intent.tags.join(", ") : "-"}`;
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
    const templateRoot = document.getElementById("intent-platforms");
    for (const platform of platforms) {
      const template = templateRoot?.querySelector(
        `.source-toggle[data-platform="${CSS.escape(platform)}"]`,
      );
      const icon = document.createElement("span");
      icon.className = "source-toggle";
      icon.setAttribute("aria-pressed", "true");
      icon.title = PLATFORM_LABELS[platform] || platform;
      if (template) {
        icon.innerHTML = template.innerHTML;
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

    let assignments = [];
    let seq = null;
    const seqRes = await fetch(`/api/intents/${intent.id}/sequence`);
    if (seqRes.ok) {
      seq = await seqRes.json();
      assignments = seq.assignments || [];
    }

    li.appendChild(renderDeviceHoursPanel(intent, assignments));

    const footer = document.createElement("div");
    footer.className = "intent-footer";

    if (seq) {
      const seqKey = `${intent.id}:sequence`;
      const seqExpanded = expandedIntentPanes.has(seqKey);
      const seqPane = document.createElement("div");
      seqPane.className = "intent-pane intent-pane-sequence";
      const seqToggle = document.createElement("button");
      seqToggle.type = "button";
      seqToggle.className = "intent-pane-toggle";
      seqToggle.setAttribute("aria-expanded", seqExpanded ? "true" : "false");
      seqToggle.textContent = `${seqExpanded ? "▾" : "▸"} Shared sequence (${seq.entries.length})`;
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
        seqToggle.textContent = `${open ? "▾" : "▸"} Shared sequence (${seq.entries.length})`;
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

bindIntentPlatformToggles();

intentCollapsible = bindCollapsibleAdd(document.getElementById("intent-form"), {
  button: "#intent-submit",
  expandLabel: "Create intent",
  submitLabel: "Create intent",
  cancelButton: "#intent-cancel",
  focusSelector: "#intent-name",
  onCancel: () => {
    document.getElementById("intent-status").textContent = "";
    clearIntentFormFields();
  },
});

document.getElementById("intent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("intent-status");
  const editId = document.getElementById("intent-edit-id").value.trim();
  const name = document.getElementById("intent-name").value.trim();
  const tags = intentTagEditor?.getTags() || [];
  const chances = readChances();
  const total = sumChances(chances);
  if (total !== 100) {
    status.textContent = `Rating chances must sum to 100% (got ${total})`;
    return;
  }

  const platforms = selectedIntentPlatforms();
  if (!platforms.length) {
    status.textContent = "Keep at least one source active";
    return;
  }

  const body = {
    name,
    tags,
    artist_ids: selectedIntentArtistIds(),
    platforms,
    distribution: {
      five: chances["chance-five"] / 100,
      four: chances["chance-four"] / 100,
      three: chances["chance-three"] / 100,
      two: chances["chance-two"] / 100,
      one: chances["chance-one"] / 100,
      unrated: chances["chance-unrated"] / 100,
    },
  };

  status.textContent = editId ? "Saving intent…" : "Creating intent…";
  try {
    const res = await fetch(editId ? `/api/intents/${editId}` : "/api/intents", {
      method: editId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      const detail = data.detail;
      status.textContent =
        typeof detail === "string"
          ? detail
          : detail?.[0]?.msg || (editId ? "Update intent failed" : "Create intent failed");
      return;
    }
    const filling = data.fill_in_progress ? " · filling caches…" : "";
    status.textContent = editId
      ? `Updated “${data.intent.name}”${filling}`
      : `Created “${data.intent.name}”${filling}`;
    resetIntentForm();
    await refreshIntents();
    await refreshFiles();
  } catch (err) {
    status.textContent = editId ? "Update intent request failed" : "Create intent request failed";
    console.error(err);
  }
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
    status.textContent = `Playing “${data.mix.title}”`;
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
  status.textContent = `Rated ${stars}★`;
  await refreshMixes();
  await refreshPlayer();
}

document.getElementById("player-reject").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  const player = await (await fetch("/api/player")).json();
  if (!player.current_mix_id) {
    status.textContent = "Nothing to reject";
    return;
  }
  try {
    const res = await fetch(`/api/mixes/${player.current_mix_id}/reject`, {
      method: "POST",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Reject failed";
      return;
    }
    status.textContent = "Reject started — undo available briefly";
    await refreshPlayer();
    await refreshMixes();
  } catch (err) {
    status.textContent = "Reject request failed";
    console.error(err);
  }
});

document.getElementById("player-undo-reject").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  const player = await (await fetch("/api/player")).json();
  if (!player.current_mix_id) {
    status.textContent = "Nothing to undo";
    return;
  }
  try {
    const res = await fetch(`/api/mixes/${player.current_mix_id}/undo-reject`, {
      method: "POST",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Undo reject failed";
      return;
    }
    status.textContent = data.undone ? "Reject undone" : "Nothing to undo";
    await refreshPlayer();
    await refreshMixes();
  } catch (err) {
    status.textContent = "Undo reject request failed";
    console.error(err);
  }
});

document.getElementById("catalog-show-rejected")?.addEventListener("change", async (event) => {
  showRejectedCatalog = Boolean(event.target.checked);
  await refreshMixes({ force: true });
});

document.getElementById("play-history-show-rejected")?.addEventListener("change", async (event) => {
  showRejectedHistory = Boolean(event.target.checked);
  await refreshMixes({ force: true });
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
  initSectionInfo();
  initSectionNav();
  initActionTips();
  initChanceSelects();
  const playerStarsRoot = document.getElementById("player-stars");
  if (playerStarsRoot) {
    playerStarRating = mountStarRating(playerStarsRoot, {
      stars: null,
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
  }
  const playerTagRoot = document.getElementById("player-tag-editor");
  if (playerTagRoot) {
    playerTagEditor = mountTagEditor(playerTagRoot, {
      tags: [],
      async onAdd(tag) {
        if (!currentMixId) throw new Error("Nothing to tag");
        await mixTagHandlers(currentMixId).onAdd(tag);
      },
      async onRemove(tag) {
        if (!currentMixId) throw new Error("Nothing to tag");
        await mixTagHandlers(currentMixId).onRemove(tag);
      },
    });
  }
  const intentTagRoot = document.getElementById("intent-tag-editor");
  if (intentTagRoot) {
    intentTagEditor = mountTagEditor(intentTagRoot, {
      tags: [],
      async onAdd() {},
      async onRemove() {},
    });
  }
  const rejectedFilter = document.getElementById("catalog-show-rejected");
  if (rejectedFilter) {
    rejectedFilter.checked = false;
    showRejectedCatalog = false;
  }
  const historyRejectedFilter = document.getElementById("play-history-show-rejected");
  if (historyRejectedFilter) {
    historyRejectedFilter.checked = false;
    showRejectedHistory = false;
  }
  await refreshHealth();
  await refreshActivity();
  await refreshPairing();
  await refreshPeers();
  await refreshMixes();
  await refreshFiles();
  await refreshIntents();
  await refreshPlayerIntents();
  await refreshPlayer();
  connectViewNotices();
  setInterval(refreshActivity, 1000);
})();
