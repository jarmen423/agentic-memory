const supported_platforms = [
  {
    key: "chatgpt",
    label: "chatgpt.com",
    matches: ["chatgpt.com", "chat.openai.com"],
  },
  {
    key: "claude",
    label: "claude.ai",
    matches: ["claude.ai"],
  },
  {
    key: "perplexity",
    label: "perplexity.ai",
    matches: ["perplexity.ai"],
  },
  {
    key: "gemini",
    label: "gemini.google.com",
    matches: ["gemini.google.com"],
  },
];

document.addEventListener("DOMContentLoaded", initialize_popup);

function initialize_popup() {
  const elements = {
    platform_value: document.getElementById("platform-value"),
    status_badge: document.getElementById("status-badge"),
    session_value: document.getElementById("session-value"),
    turn_count: document.getElementById("turn-count"),
    pause_btn: document.getElementById("pause-btn"),
    settings_link: document.getElementById("settings-link"),
  };

  const popup_state = {
    active_tab_id: null,
    platform_info: null,
    config: {
      api_key: "",
      paused: false,
      platforms: {},
    },
  };

  elements.pause_btn.hidden = true;
  elements.settings_link.addEventListener("click", (event) => {
    event.preventDefault();
    const onboarding_url = chrome.runtime.getURL("onboarding/onboarding.html");
    chrome.tabs.create({ url: onboarding_url });
  });

  elements.pause_btn.addEventListener("click", () => {
    popup_state.config.paused = !popup_state.config.paused;
    chrome.storage.sync.set({ paused: popup_state.config.paused }, () => {
      update_popup_view(elements, popup_state);
    });
    update_popup_view(elements, popup_state);
  });

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const active_tab = tabs?.[0] || null;
    popup_state.active_tab_id = active_tab?.id ?? null;
    popup_state.platform_info = detect_platform(active_tab?.url);

    update_platform_label(elements, popup_state.platform_info);
    update_popup_view(elements, popup_state);

    chrome.storage.sync.get(["endpoint", "api_key", "paused", "platforms"], (cfg) => {
      popup_state.config = {
        endpoint: cfg?.endpoint || "",
        api_key: cfg?.api_key || "",
        paused: Boolean(cfg?.paused),
        platforms: cfg?.platforms || {},
      };

      update_popup_view(elements, popup_state);
      request_tab_status(elements, popup_state.active_tab_id);
    });
  });
}

function detect_platform(tab_url) {
  if (!tab_url) {
    return null;
  }

  let hostname = "";

  try {
    hostname = new URL(tab_url).hostname.toLowerCase();
  } catch (_error) {
    return null;
  }

  for (const platform of supported_platforms) {
    if (platform.matches.some((candidate) => hostname === candidate || hostname.endsWith(`.${candidate}`))) {
      return {
        key: platform.key,
        label: platform.label,
      };
    }
  }

  return null;
}

function update_platform_label(elements, platform_info) {
  elements.platform_value.textContent = platform_info?.label || "Not on a supported page";
}

function update_popup_view(elements, popup_state) {
  const status = determine_status(popup_state.config, popup_state.platform_info);

  elements.status_badge.textContent = status.label;
  elements.status_badge.className = `status-badge ${status.class_name}`;
  elements.pause_btn.textContent = popup_state.config.paused ? "Resume" : "Pause";
  elements.pause_btn.hidden = !popup_state.platform_info;
}

function determine_status(config, platform_info) {
  if (!config.api_key) {
    return {
      label: "Not configured",
      class_name: "status-neutral",
    };
  }

  if (config.paused || (platform_info && config.platforms?.[platform_info.key] === false)) {
    return {
      label: "Paused",
      class_name: "status-paused",
    };
  }

  if (platform_info) {
    return {
      label: "Capturing",
      class_name: "status-capturing",
    };
  }

  return {
    label: "Not on a supported page",
    class_name: "status-neutral",
  };
}

function request_tab_status(elements, active_tab_id) {
  if (!active_tab_id) {
    return;
  }

  chrome.tabs.sendMessage(active_tab_id, { type: "GET_STATUS" }, (response) => {
    if (chrome.runtime.lastError || !response) {
      return;
    }

    if (response.session_id) {
      elements.session_value.textContent = format_session_id(response.session_id);
    }

    const turns_this_session = extract_turn_count(response);
    if (turns_this_session !== null) {
      elements.turn_count.textContent = String(turns_this_session);
    }
  });
}

function extract_turn_count(response) {
  const turn_candidates = [
    response.turn_count,
    response.turns_this_session,
    response.turns,
  ];

  for (const candidate of turn_candidates) {
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return candidate;
    }
  }

  return null;
}

function format_session_id(session_id) {
  if (typeof session_id !== "string" || session_id.length === 0) {
    return "--";
  }

  if (session_id.length <= 8) {
    return session_id;
  }

  return `${session_id.slice(0, 8)}…`;
}
