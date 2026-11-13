async function refreshHealth() {
  const el = document.getElementById("health");
  const nameEl = document.getElementById("device-name");
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    el.textContent = data.ok ? `ok (v${data.version})` : "degraded";
    nameEl.textContent = data.device || "unknown";
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
  const list = document.getElementById("peer-list");
  list.innerHTML = "";
  if (!data.peers.length) {
    const li = document.createElement("li");
    li.textContent = "No peers yet";
    li.className = "muted";
    list.appendChild(li);
    return;
  }
  for (const peer of data.peers) {
    const li = document.createElement("li");
    li.textContent = `${peer.name} (priority ${peer.priority})`;
    list.appendChild(li);
  }
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
    li.textContent = mix.title;
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
    status.textContent = `Synced · ${data.peers} peers · ${data.mixes} mixes`;
    await refreshPeers();
    await refreshMixes();
  } catch (err) {
    status.textContent = "Sync request failed";
    console.error(err);
  }
});

refreshHealth();
refreshPairing();
refreshPeers();
refreshMixes();
