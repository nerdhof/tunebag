let localDeviceId = null;
let currentMixId = null;
let peersCache = [];
let editingHoursByDevice = null;
let editingExpiresByDevice = null;
const expandedCatalogArtists = new Set();
const expandedCacheIntents = new Set();
let rejectUndoTimer = null;
let fillWasInProgress = false;
let lastFilesRefreshAt = 0;
let filesRefreshInFlight = null;
const FILES_REFRESH_MIN_MS = 1000;

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

function resetIntentForm() {
  document.getElementById("intent-edit-id").value = "";
  document.getElementById("intent-name").value = "";
  document.getElementById("intent-tags").value = "";
  document.getElementById("chance-five").value = "30";
  document.getElementById("chance-four").value = "20";
  document.getElementById("chance-three").value = "10";
  document.getElementById("chance-two").value = "5";
  document.getElementById("chance-one").value = "5";
  document.getElementById("chance-unrated").value = "30";
  document.getElementById("intent-submit").textContent = "Create intent";
  document.getElementById("intent-cancel").hidden = true;
  editingHoursByDevice = null;
  editingExpiresByDevice = null;
  renderHoursFields();
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
  document.getElementById("intent-tags").value = intent.tags.join(", ");
  const dist = intent.distribution;
  document.getElementById("chance-five").value = String(Math.round(dist.five * 100));
  document.getElementById("chance-four").value = String(Math.round(dist.four * 100));
  document.getElementById("chance-three").value = String(Math.round(dist.three * 100));
  document.getElementById("chance-two").value = String(Math.round(dist.two * 100));
  document.getElementById("chance-one").value = String(Math.round(dist.one * 100));
  document.getElementById("chance-unrated").value = String(Math.round(dist.unrated * 100));
  document.getElementById("intent-chances").open = true;
  document.getElementById("intent-submit").textContent = "Save changes";
  document.getElementById("intent-cancel").hidden = false;
  editingHoursByDevice = {};
  editingExpiresByDevice = {};
  for (const dh of intent.device_hours || []) {
    editingHoursByDevice[dh.device_id] = String(dh.budget_seconds / 3600);
    const until = hoursUntilExpiry(dh.expires_at);
    if (until !== "") {
      editingExpiresByDevice[dh.device_id] = until;
    }
  }
  renderHoursFields();
  document.getElementById("intent-form").scrollIntoView({ behavior: "smooth", block: "start" });
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
  } catch (err) {
    el.textContent = "unreachable";
    console.error(err);
  }
}

async function refreshPairing() {
  const res = await fetch("/api/pairing");
  const payload = await res.json();
  document.getElementById("short-code").textContent = payload.short_code;
  document.getElementById("pairing-payload").textContent = JSON.stringify(payload, null, 2);
  const qr = document.getElementById("qr");
  qr.src = `/api/pairing/qr.png?t=${Date.now()}`;
}

async function refreshPeers() {
  const res = await fetch("/api/peers");
  const data = await res.json();
  peersCache = data.peers || [];
  const list = document.getElementById("peer-list");
  list.innerHTML = "";
  if (!peersCache.length) {
    const li = document.createElement("li");
    li.textContent = "No peers yet";
    li.className = "muted";
    list.appendChild(li);
  } else {
    for (const peer of peersCache) {
      const li = document.createElement("li");
      li.textContent = `${peer.name} (priority ${peer.priority})`;
      list.appendChild(li);
    }
  }
  renderHoursFields();
}

function renderHoursFields() {
  const root = document.getElementById("intent-hours");
  const previous = {};
  const previousExpires = {};
  for (const input of root.querySelectorAll("input[data-device-id]")) {
    previous[input.dataset.deviceId] = input.value;
  }
  for (const input of root.querySelectorAll("input[data-expires-for]")) {
    previousExpires[input.dataset.expiresFor] = input.value;
  }
  root.innerHTML = "";

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
  if (editingHoursByDevice) {
    const known = new Set(devices.map((d) => d.id));
    for (const [deviceId, hours] of Object.entries(editingHoursByDevice)) {
      if (!known.has(deviceId)) {
        devices.push({
          id: deviceId,
          name: deviceId.slice(0, 8),
          defaultHours: hours,
        });
      }
    }
  }
  if (!devices.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "Waiting for this device’s id…";
    root.appendChild(p);
    return;
  }

  for (const device of devices) {
    const row = document.createElement("div");
    row.className = "hours-row";

    const label = document.createElement("label");
    label.textContent = `${device.name} (hours)`;
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0.5";
    input.step = "0.5";
    input.required = true;
    input.dataset.deviceId = device.id;
    input.value =
      previous[device.id] ??
      editingHoursByDevice?.[device.id] ??
      device.defaultHours;
    label.appendChild(input);
    row.appendChild(label);

    const expiresLabel = document.createElement("label");
    expiresLabel.textContent = "Expires in (hours, optional)";
    const expiresInput = document.createElement("input");
    expiresInput.type = "number";
    expiresInput.min = "0";
    expiresInput.step = "0.5";
    expiresInput.placeholder = "never";
    expiresInput.dataset.expiresFor = device.id;
    expiresInput.value =
      previousExpires[device.id] ?? editingExpiresByDevice?.[device.id] ?? "";
    expiresLabel.appendChild(expiresInput);
    row.appendChild(expiresLabel);

    root.appendChild(row);
  }
}

function formatDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
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
}

function cacheGroupKey(group) {
  return group.id == null ? "other" : String(group.id);
}

function formatCacheOverview(overview) {
  const parts = ["cached", "loading", "pending"].map((status) => {
    const bucket = overview?.[status] || { count: 0, duration_seconds: 0 };
    return `${status}: ${bucket.count} (${formatHms(bucket.duration_seconds)})`;
  });
  return parts.join(", ");
}

function formatMb(bytes) {
  const n = Number(bytes) || 0;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
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

function groupMixesByArtist(mixes) {
  const groups = new Map();
  for (const mix of mixes) {
    const artistId = mix.artist_id || "unknown";
    const artistName = mix.artist || "Unknown";
    let group = groups.get(artistId);
    if (!group) {
      group = { artistId, artistName, mixes: [] };
      groups.set(artistId, group);
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

async function refreshMixes() {
  const res = await fetch("/api/mixes");
  const data = await res.json();
  const body = document.getElementById("catalog-body");
  body.innerHTML = "";
  if (!data.mixes.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "muted";
    td.textContent = "No mixes yet";
    tr.appendChild(td);
    body.appendChild(tr);
    await refreshTagSuggestions();
    return;
  }

  for (const group of groupMixesByArtist(data.mixes)) {
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
    const toggle = document.createElement("span");
    toggle.className = "artist-toggle";
    toggle.setAttribute("aria-hidden", "true");
    toggle.textContent = expanded ? "▼" : "▶";
    artistCell.appendChild(toggle);
    artistCell.appendChild(
      document.createTextNode(
        `${group.artistName} (${group.mixes.length})`,
      ),
    );
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

    for (const mix of group.mixes) {
      const tr = document.createElement("tr");
      tr.className = "mix-row";
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
      rating.textContent = mix.stars != null ? `${mix.stars}★` : "—";
      tr.appendChild(rating);

      const tagsCell = document.createElement("td");
      const tagRow = document.createElement("div");
      tagRow.className = "tag-cell";
      const tagInput = document.createElement("input");
      tagInput.type = "text";
      tagInput.setAttribute("list", "tag-suggestions");
      tagInput.placeholder = "tags";
      tagInput.value = (mix.tags || []).join(", ");
      tagInput.addEventListener("click", (event) => event.stopPropagation());
      tagRow.appendChild(tagInput);
      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.textContent = "Save";
      saveBtn.addEventListener("click", async (event) => {
        event.stopPropagation();
        const tags = tagInput.value
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean);
        const saveRes = await fetch(`/api/mixes/${mix.id}/tags`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tags }),
        });
        if (saveRes.ok) {
          const saved = await saveRes.json();
          tagInput.value = (saved.mix?.tags || tags).join(", ");
          await refreshTagSuggestions();
        }
      });
      tagRow.appendChild(saveBtn);
      tagsCell.appendChild(tagRow);
      tr.appendChild(tagsCell);
      body.appendChild(tr);
    }
  }
  await refreshTagSuggestions();
}

async function refreshTagSuggestions() {
  const res = await fetch("/api/tags");
  const data = await res.json();
  const datalist = document.getElementById("tag-suggestions");
  if (!datalist) return;
  datalist.innerHTML = "";
  for (const tag of data.tags || []) {
    const option = document.createElement("option");
    option.value = tag;
    datalist.appendChild(option);
  }
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

async function refreshPlayer() {
  const res = await fetch("/api/player");
  const data = await res.json();
  const now = document.getElementById("player-now");
  if (!now) return;
  if (!data.current_mix_id) {
    now.textContent = "Nothing playing";
    updateSeekBar({});
    setPlayerPolling(false);
    updateRejectControls({});
    return;
  }
  const state = data.playing ? "Playing" : "Paused/stopped";
  const pos = Math.round(data.position_seconds || 0);
  now.textContent = `${state}: ${data.title} @ ${pos}s / ${formatDuration(data.duration_seconds || 0)}`;
  if (!playerSeekDragging) {
    document.getElementById("player-position").value = String(pos);
  }
  document.getElementById("player-stars").value =
    data.stars != null ? String(data.stars) : "";
  document.getElementById("player-tags").value = (data.tags || []).join(", ");
  updateSeekBar(data);
  setPlayerPolling(Boolean(data.playing));
  updateRejectControls(data);
}

async function showLaterFeatures(features) {
  const panel = document.getElementById("later-panel");
  const list = document.getElementById("later-list");
  if (!panel || !list) return;
  list.innerHTML = "";
  for (const feature of features || []) {
    const li = document.createElement("li");
    li.textContent = feature;
    list.appendChild(li);
  }
  panel.hidden = false;
  // Close the active player controls; the demo ends on the later list.
  for (const id of [
    "player-play",
    "player-stop",
    "player-mark",
    "player-seek",
    "player-seekbar",
    "player-rate",
    "player-reject",
    "player-undo-reject",
    "player-tag",
    "player-intent",
    "player-position",
    "player-stars",
    "player-tags",
  ]) {
    const el = document.getElementById(id);
    if (el) el.disabled = true;
  }
  setPlayerPolling(false);
  const now = document.getElementById("player-now");
  if (now) now.textContent = "Player closed";
}

async function refreshFiles() {
  const res = await fetch("/api/files");
  const data = await res.json();
  const countEl = document.getElementById("cache-count");
  if (countEl) {
    countEl.textContent = String(data.files.length);
  }
  const body = document.getElementById("cache-body");
  body.innerHTML = "";
  const groups = Array.isArray(data.groups) ? data.groups : [];
  if (!groups.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
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
    intentCell.colSpan = 5;
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

      const title = document.createElement("td");
      title.textContent = file.title || "";
      tr.appendChild(title);

      const length = document.createElement("td");
      length.textContent = formatDuration(file.duration_seconds || 0);
      tr.appendChild(length);

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
        currentBtn.textContent = isCurrent ? "Clear current" : "Set current";
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
              status.textContent = bodyJson.detail || "Could not set current mix";
              return;
            }
            currentMixId = bodyJson.current_mix_id || null;
            status.textContent = currentMixId
              ? `Current mix set · metered cap uses this + one ahead`
              : "Current mix cleared · metered cap uses assignment head";
            await refreshFiles();
          } catch (err) {
            status.textContent = "Current mix request failed";
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

async function refreshIntents() {
  const res = await fetch("/api/intents");
  const data = await res.json();
  const list = document.getElementById("intent-list");
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
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", () => beginEditIntent(intent));
    headingRow.appendChild(editBtn);
    const fillNowBtn = document.createElement("button");
    fillNowBtn.type = "button";
    fillNowBtn.textContent = "Fill now";
    fillNowBtn.title = "Top up this intent to full hours once (metered override)";
    fillNowBtn.addEventListener("click", async () => {
      const status = document.getElementById("intent-status");
      status.textContent = `Fill now “${intent.name}”…`;
      try {
        const res = await fetch(`/api/intents/${intent.id}/fill-now`, { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          status.textContent = data.detail || "Fill now failed";
          return;
        }
        status.textContent = data.fill_in_progress
          ? `Fill now “${intent.name}” started · ${data.files} cached so far`
          : `Fill now “${intent.name}” · ${data.files} cached`;
        await refreshFiles();
      } catch (err) {
        status.textContent = "Fill now request failed";
        console.error(err);
      }
    });
    headingRow.appendChild(fillNowBtn);
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", async () => {
      if (!window.confirm(`Delete intent “${intent.name}”?`)) {
        return;
      }
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
        status.textContent = `Deleted “${intent.name}”`;
        await refreshIntents();
      } catch (err) {
        status.textContent = "Delete intent request failed";
        console.error(err);
      }
    });
    headingRow.appendChild(deleteBtn);
    li.appendChild(headingRow);

    const meta = document.createElement("p");
    meta.className = "muted";
    const tags = intent.tags.length ? intent.tags.join(", ") : "untagged only";
    const dist = intent.distribution;
    const hours = (intent.device_hours || [])
      .map((dh) => {
        const budget = formatDuration(dh.budget_seconds);
        if (!dh.expires_at) return budget;
        const until = hoursUntilExpiry(dh.expires_at);
        return until === "" || until === "0"
          ? `${budget} (expired)`
          : `${budget} (expires ${until}h)`;
      })
      .join(" / ");
    meta.textContent =
      `Tags: ${tags} · chances ${Math.round(dist.five * 100)}/` +
      `${Math.round(dist.four * 100)}/${Math.round(dist.three * 100)}/` +
      `${Math.round(dist.two * 100)}/${Math.round(dist.one * 100)}/` +
      `${Math.round(dist.unrated * 100)}` +
      ` · hours ${hours}`;
    li.appendChild(meta);

    const seqRes = await fetch(`/api/intents/${intent.id}/sequence`);
    if (seqRes.ok) {
      const seq = await seqRes.json();
      const seqTitle = document.createElement("p");
      seqTitle.textContent = `Shared sequence (${seq.entries.length})`;
      li.appendChild(seqTitle);
      const seqList = document.createElement("ol");
      seqList.className = "seq-list";
      for (const entry of seq.entries) {
        const item = document.createElement("li");
        const dur =
          entry.duration_seconds != null ? ` · ${formatDuration(entry.duration_seconds)}` : "";
        item.textContent = `${entry.title || entry.mix_id} (${entry.bucket})${dur}`;
        seqList.appendChild(item);
      }
      li.appendChild(seqList);

      if (seq.assignments?.length) {
        const asgTitle = document.createElement("p");
        asgTitle.textContent = "Assignments";
        li.appendChild(asgTitle);
        const asgList = document.createElement("ul");
        asgList.className = "asg-list";
        for (const asg of seq.assignments) {
          const item = document.createElement("li");
          const name = asg.device_name || asg.device_id;
          item.textContent =
            `${name}: ${asg.mix_ids.length} mixes · ` +
            `${formatDuration(asg.budget_seconds)} budget`;
          asgList.appendChild(item);
        }
        li.appendChild(asgList);
      }
    }

    list.appendChild(li);
  }
  await refreshPlayerIntents();
}

document.getElementById("pair-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("pair-status");
  status.textContent = "Pairing…";
  const payloadText = document.getElementById("pair-payload").value.trim();
  const body = {};
  if (payloadText) {
    try {
      body.payload = JSON.parse(payloadText);
    } catch (err) {
      status.textContent = "Payload is not valid JSON";
      return;
    }
  } else {
    body.peer_url = document.getElementById("peer-url").value.trim();
    body.short_code = document.getElementById("pair-code").value.trim();
  }
  try {
    const res = await fetch("/api/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.detail || "Pair failed";
      return;
    }
    status.textContent = `Paired with ${data.peer.name}`;
    await refreshPeers();
  } catch (err) {
    status.textContent = "Pair request failed";
    console.error(err);
  }
});

document.getElementById("artists-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("artists-status");
  const raw = document.getElementById("artist-urls").value;
  const urls = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const minutes = Number(document.getElementById("min-duration-minutes").value);
  const min_duration_seconds = Number.isFinite(minutes)
    ? Math.max(0, Math.round(minutes * 60))
    : 1200;
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
    status.textContent = `Added ${data.added} mixes · ${data.artists} artists`;
    await refreshMixes();
  } catch (err) {
    status.textContent = "Add artists request failed";
    console.error(err);
  }
});

document.getElementById("intent-cancel").addEventListener("click", () => {
  document.getElementById("intent-status").textContent = "";
  resetIntentForm();
});

document.getElementById("intent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("intent-status");
  const editId = document.getElementById("intent-edit-id").value.trim();
  const name = document.getElementById("intent-name").value.trim();
  const tags = document
    .getElementById("intent-tags")
    .value.split(/[,]+/)
    .map((tag) => tag.trim())
    .filter(Boolean);
  const five = Number(document.getElementById("chance-five").value);
  const four = Number(document.getElementById("chance-four").value);
  const three = Number(document.getElementById("chance-three").value);
  const two = Number(document.getElementById("chance-two").value);
  const one = Number(document.getElementById("chance-one").value);
  const unrated = Number(document.getElementById("chance-unrated").value);
  const total = five + four + three + two + one + unrated;
  if (Math.abs(total - 100) > 0.01) {
    status.textContent = `Star chances must sum to 100% (got ${total})`;
    return;
  }

  // Refresh device id before collect — open tab after serve restart can be stale.
  await refreshHealth();
  await refreshPeers();
  renderHoursFields();

  const device_hours = [];
  for (const input of document.querySelectorAll("#intent-hours input[data-device-id]")) {
    const hours = Number(input.value);
    if (!Number.isFinite(hours) || hours <= 0) {
      status.textContent = "Each device needs hours greater than 0";
      return;
    }
    const deviceId = input.dataset.deviceId;
    const expiresInput = document.querySelector(
      `#intent-hours input[data-expires-for="${deviceId}"]`,
    );
    let expires_at = null;
    if (expiresInput && expiresInput.value !== "") {
      const until = Number(expiresInput.value);
      if (!Number.isFinite(until) || until < 0) {
        status.textContent = "Expires in must be a non-negative number of hours";
        return;
      }
      if (until > 0) {
        expires_at = new Date(Date.now() + until * 3600 * 1000).toISOString();
      }
    }
    device_hours.push({
      device_id: deviceId,
      budget_seconds: Math.round(hours * 3600),
      expires_at,
    });
  }
  if (!device_hours.length) {
    status.textContent = "No devices available for hours";
    return;
  }

  const body = {
    name,
    tags,
    distribution: {
      five: five / 100,
      four: four / 100,
      three: three / 100,
      two: two / 100,
      one: one / 100,
      unrated: unrated / 100,
    },
    device_hours,
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
    const fileCount = data.files ?? 0;
    const filling = data.fill_in_progress ? " · filling caches…" : ` · ${fileCount} cached`;
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
      ? `Synced · ${data.peers} peers · ${data.mixes} mixes · filling caches…`
      : `Synced · ${data.peers} peers · ${data.mixes} mixes · ${data.files} cached`;
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

document.getElementById("player-tags").addEventListener("input", async (event) => {
  const value = event.target.value;
  const last = value.split(",").pop()?.trim() || "";
  const res = await fetch(`/api/tags?q=${encodeURIComponent(last)}`);
  const data = await res.json().catch(() => ({ tags: [] }));
  const datalist = document.getElementById("tag-suggestions");
  if (!datalist) return;
  datalist.innerHTML = "";
  for (const tag of data.tags || []) {
    const option = document.createElement("option");
    option.value = tag;
    datalist.appendChild(option);
  }
});

document.getElementById("player-play").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  const intentId = document.getElementById("player-intent").value;
  if (!intentId) {
    status.textContent = "Choose an intent";
    return;
  }
  status.textContent = "Starting playback…";
  try {
    const res = await fetch("/api/player/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent_id: intentId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Play failed";
      return;
    }
    status.textContent = `Playing “${data.mix.title}”`;
    document.getElementById("later-panel").hidden = true;
    await refreshPlayer();
    await refreshFiles();
  } catch (err) {
    status.textContent = "Play request failed";
    console.error(err);
  }
});

document.getElementById("player-stop").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  try {
    await fetch("/api/player/stop", { method: "POST" });
    status.textContent = "Stopped (mix left in place if under 75%)";
    await refreshPlayer();
  } catch (err) {
    status.textContent = "Stop request failed";
    console.error(err);
  }
});

const playerSeekbar = document.getElementById("player-seekbar");
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
  playerSeekbar.addEventListener("input", () => {
    playerSeekDragging = true;
    const currentEl = document.getElementById("player-time-current");
    if (currentEl) {
      currentEl.textContent = formatClock(Number(playerSeekbar.value || 0));
    }
    document.getElementById("player-position").value = String(
      Math.round(Number(playerSeekbar.value || 0)),
    );
  });
  playerSeekbar.addEventListener("change", async () => {
    playerSeekDragging = false;
    const status = document.getElementById("player-status");
    const position = Math.round(Number(playerSeekbar.value || 0));
    try {
      const res = await fetch("/api/player/seek", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ position_seconds: position }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        status.textContent = data.detail || "Seek failed";
        await refreshPlayer();
        return;
      }
      status.textContent = data.played
        ? `Seeked to ${formatClock(position)} · marked played`
        : `Seeked to ${formatClock(position)}`;
      if (data.played) {
        await showLaterFeatures(data.later || []);
      }
      await refreshPlayer();
      await refreshMixes();
      await refreshFiles();
      await refreshIntents();
    } catch (err) {
      status.textContent = "Seek request failed";
      console.error(err);
      await refreshPlayer();
    }
  });
}

document.getElementById("player-seek").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  const position = Number(document.getElementById("player-position").value || 0);
  try {
    const res = await fetch("/api/player/playhead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position_seconds: position }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Playhead update failed";
      return;
    }
    status.textContent = data.played
      ? `Playhead ${position}s · marked played`
      : `Playhead ${position}s`;
    if (data.played) {
      await showLaterFeatures(data.later || []);
    }
    await refreshPlayer();
    await refreshMixes();
    await refreshFiles();
    await refreshIntents();
  } catch (err) {
    status.textContent = "Playhead request failed";
    console.error(err);
  }
});

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
    await showLaterFeatures(data.later);
    await refreshPlayer();
    await refreshMixes();
    await refreshFiles();
    await refreshIntents();
  } catch (err) {
    status.textContent = "Mark played request failed";
    console.error(err);
  }
});

document.getElementById("player-rate").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  const player = await (await fetch("/api/player")).json();
  if (!player.current_mix_id) {
    status.textContent = "Nothing to rate";
    return;
  }
  const stars = document.getElementById("player-stars").value;
  if (!stars) {
    status.textContent = "Choose 1–5 stars";
    return;
  }
  try {
    const res = await fetch(`/api/mixes/${player.current_mix_id}/rate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stars: Number(stars) }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Rate failed";
      return;
    }
    status.textContent = `Rated ${stars}★`;
    await refreshMixes();
    await refreshPlayer();
  } catch (err) {
    status.textContent = "Rate request failed";
    console.error(err);
  }
});

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

document.getElementById("player-tag").addEventListener("click", async () => {
  const status = document.getElementById("player-status");
  const player = await (await fetch("/api/player")).json();
  if (!player.current_mix_id) {
    status.textContent = "Nothing to tag";
    return;
  }
  const tags = document
    .getElementById("player-tags")
    .value.split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
  try {
    const res = await fetch(`/api/mixes/${player.current_mix_id}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Tag failed";
      return;
    }
    status.textContent = tags.length ? `Tags: ${tags.join(", ")}` : "Tags cleared";
    await refreshMixes();
    await refreshTagSuggestions();
    await refreshPlayer();
  } catch (err) {
    status.textContent = "Tag request failed";
    console.error(err);
  }
});

(async () => {
  await refreshHealth();
  await refreshActivity();
  await refreshPairing();
  await refreshPeers();
  await refreshMixes();
  await refreshFiles();
  await refreshIntents();
  await refreshPlayerIntents();
  await refreshPlayer();
  setInterval(refreshActivity, 1000);
})();
