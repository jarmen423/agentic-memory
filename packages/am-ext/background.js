chrome.alarms.create("keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => {});

chrome.runtime.onMessage.addListener((msg, _sender, _send_response) => {
  if (msg?.type !== "NEW_TURN") {
    return false;
  }

  handle_turn(msg.payload);
  return false;
});

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.tabs.create({
      url: chrome.runtime.getURL("onboarding/onboarding.html"),
    }).catch(() => {});
  }
});

async function handle_turn(payload) {
  try {
    if (!payload?.platform) {
      return;
    }

    const cfg = await chrome.storage.sync.get([
      "endpoint",
      "api_key",
      "paused",
      "platforms",
      "project_id",
    ]);

    if (cfg.paused) {
      return;
    }

    if (!cfg.platforms?.[payload.platform]) {
      return;
    }

    if (!cfg.api_key) {
      return;
    }

    const endpoint = cfg.endpoint || "http://localhost:8000";
    const body = {
      role: payload.role,
      content: payload.content,
      session_id: payload.session_id,
      project_id: cfg.project_id || "browser",
      turn_index: payload.turn_index,
      source_agent: payload.platform,
      ingestion_mode: "passive",
      source_key: `browser_ext_${payload.platform}`,
    };

    fetch(`${endpoint}/ingest/conversation`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${cfg.api_key}`,
      },
      body: JSON.stringify(body),
    }).catch(() => {});
  } catch (_error) {}
}
