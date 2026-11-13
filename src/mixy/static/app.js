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
    const tags = mix.tags?.length ? ` · ${mix.tags.join(", ")}` : "";
    li.textContent = `${mix.title} · ${formatDuration(mix.duration_seconds)}${tags}`;
    list.appendChild(li);
  }
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

(async () => {
  await refreshHealth();
  await refreshPairing();
  await refreshPeers();
  await refreshMixes();
  await refreshFiles();
  await refreshIntents();
})();
