let localDeviceId = null;
let currentMixId = null;
let peersCache = [];
let editingHoursByDevice = null;

function resetIntentForm() {
  document.getElementById("intent-edit-id").value = "";
  document.getElementById("intent-name").value = "";
  document.getElementById("intent-tags").value = "";
  document.getElementById("chance-five").value = "40";
  document.getElementById("chance-four").value = "30";
  document.getElementById("chance-three").value = "20";
  document.getElementById("chance-rest").value = "10";
  document.getElementById("intent-submit").textContent = "Create intent";
  document.getElementById("intent-cancel").hidden = true;
  editingHoursByDevice = null;
  renderHoursFields();
}

function beginEditIntent(intent) {
  document.getElementById("intent-edit-id").value = intent.id;
  document.getElementById("intent-name").value = intent.name;
  document.getElementById("intent-tags").value = intent.tags.join(", ");
  const dist = intent.distribution;
  document.getElementById("chance-five").value = String(Math.round(dist.five * 100));
  document.getElementById("chance-four").value = String(Math.round(dist.four * 100));
  document.getElementById("chance-three").value = String(Math.round(dist.three * 100));
  document.getElementById("chance-rest").value = String(Math.round(dist.rest * 100));
  document.getElementById("intent-chances").open = true;
  document.getElementById("intent-submit").textContent = "Save changes";
  document.getElementById("intent-cancel").hidden = false;
  editingHoursByDevice = {};
  for (const dh of intent.device_hours || []) {
    editingHoursByDevice[dh.device_id] = String(dh.budget_seconds / 3600);
  }
  renderHoursFields();
  document.getElementById("intent-form").scrollIntoView({ behavior: "smooth", block: "start" });
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
  for (const input of root.querySelectorAll("input[data-device-id]")) {
    previous[input.dataset.deviceId] = input.value;
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
    root.appendChild(label);
  }
}

function formatDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

async function refreshMixes() {
  const res = await fetch("/api/mixes");
  const data = await res.json();
  const list = document.getElementById("mix-list");
  list.innerHTML = "";
  if (!data.mixes.length) {
    const li = document.createElement("li");
    li.textContent = "No mixes yet";
    li.className = "muted";
    list.appendChild(li);
    return;
  }
  for (const mix of data.mixes) {
    const li = document.createElement("li");
    const meta = document.createElement("div");
    const stars = mix.stars != null ? ` · ${mix.stars}★` : "";
    const played = mix.played ? " · played" : "";
    meta.textContent = `${mix.title} · ${formatDuration(mix.duration_seconds)}${stars}${played}`;
    li.appendChild(meta);
    const row = document.createElement("div");
    row.className = "controls";
    const tagInput = document.createElement("input");
    tagInput.type = "text";
    tagInput.setAttribute("list", "tag-suggestions");
    tagInput.placeholder = "tags";
    tagInput.value = (mix.tags || []).join(", ");
    tagInput.style.flex = "1";
    row.appendChild(tagInput);
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = "Save tags";
    saveBtn.addEventListener("click", async () => {
      const tags = tagInput.value
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean);
      const res = await fetch(`/api/mixes/${mix.id}/tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags }),
      });
      if (res.ok) {
        await refreshMixes();
        await refreshTagSuggestions();
      }
    });
    row.appendChild(saveBtn);
    li.appendChild(row);
    list.appendChild(li);
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

async function refreshPlayer() {
  const res = await fetch("/api/player");
  const data = await res.json();
  const now = document.getElementById("player-now");
  if (!now) return;
  if (!data.current_mix_id) {
    now.textContent = "Nothing playing";
    return;
  }
  const state = data.playing ? "Playing" : "Paused/stopped";
  const pos = Math.round(data.position_seconds || 0);
  now.textContent = `${state}: ${data.title} @ ${pos}s / ${formatDuration(data.duration_seconds || 0)}`;
  document.getElementById("player-position").value = String(pos);
  document.getElementById("player-stars").value =
    data.stars != null ? String(data.stars) : "";
  document.getElementById("player-tags").value = (data.tags || []).join(", ");
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
    "player-rate",
    "player-tag",
    "player-intent",
    "player-position",
    "player-stars",
    "player-tags",
  ]) {
    const el = document.getElementById(id);
    if (el) el.disabled = true;
  }
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
  const list = document.getElementById("file-list");
  list.innerHTML = "";
  if (!data.files.length) {
    const li = document.createElement("li");
    li.textContent = "No cached audio yet — create an intent with hours, or press Fill caches";
    li.className = "muted";
    list.appendChild(li);
    return;
  }
  for (const file of data.files) {
    const li = document.createElement("li");
    const row = document.createElement("div");
    row.className = "controls";
    const label = document.createElement("span");
    label.style.flex = "1";
    const isCurrent = currentMixId === file.id;
    label.textContent =
      `${file.title} · ${formatDuration(file.duration_seconds)}` +
      (isCurrent ? " · current" : "");
    row.appendChild(label);
    const currentBtn = document.createElement("button");
    currentBtn.type = "button";
    currentBtn.textContent = isCurrent ? "Clear current" : "Set current";
    currentBtn.addEventListener("click", async () => {
      const status = document.getElementById("fill-status");
      try {
        const res = await fetch("/api/current-mix", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mix_id: isCurrent ? null : file.id }),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
          status.textContent = body.detail || "Could not set current mix";
          return;
        }
        currentMixId = body.current_mix_id || null;
        status.textContent = currentMixId
          ? `Current mix set · metered cap uses this + one ahead`
          : "Current mix cleared · metered cap uses assignment head";
        await refreshFiles();
      } catch (err) {
        status.textContent = "Current mix request failed";
        console.error(err);
      }
    });
    row.appendChild(currentBtn);
    li.appendChild(row);
    list.appendChild(li);
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
        status.textContent = `Fill now “${intent.name}” · ${data.files} cached`;
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
      .map((dh) => `${formatDuration(dh.budget_seconds)}`)
      .join(" / ");
    meta.textContent =
      `Tags: ${tags} · chances ${Math.round(dist.five * 100)}/` +
      `${Math.round(dist.four * 100)}/${Math.round(dist.three * 100)}/` +
      `${Math.round(dist.rest * 100)}` +
      (hours ? ` · hours ${hours}` : "");
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
  const rest = Number(document.getElementById("chance-rest").value);
  const total = five + four + three + rest;
  if (Math.abs(total - 100) > 0.01) {
    status.textContent = `Star chances must sum to 100% (got ${total})`;
    return;
  }

  const device_hours = [];
  for (const input of document.querySelectorAll("#intent-hours input[data-device-id]")) {
    const hours = Number(input.value);
    if (!Number.isFinite(hours) || hours <= 0) {
      status.textContent = "Each device needs hours greater than 0";
      return;
    }
    device_hours.push({
      device_id: input.dataset.deviceId,
      budget_seconds: Math.round(hours * 3600),
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
      rest: rest / 100,
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
    status.textContent = editId
      ? `Updated “${data.intent.name}” · ${fileCount} cached`
      : `Created “${data.intent.name}” · ${fileCount} cached`;
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
    status.textContent =
      `Synced · ${data.peers} peers · ${data.mixes} mixes · ${data.files} cached`;
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
  status.textContent = "Filling caches… (downloads can take a while)";
  try {
    const res = await fetch("/api/fill", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.detail || "Fill failed";
      return;
    }
    status.textContent = `Filled · ${data.files} cached`;
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
  await refreshPairing();
  await refreshPeers();
  await refreshMixes();
  await refreshFiles();
  await refreshIntents();
  await refreshPlayerIntents();
  await refreshPlayer();
})();
