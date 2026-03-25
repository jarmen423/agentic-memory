const default_config = {
  endpoint: "http://localhost:8000",
  api_key: "",
  project_id: "browser",
  paused: false,
  platforms: {
    chatgpt: true,
    claude: true,
    gemini: true,
    perplexity: true,
  },
};

let saved_message_timer = null;

document.addEventListener("DOMContentLoaded", initialize_onboarding);

function initialize_onboarding() {
  const elements = {
    endpoint: document.getElementById("endpoint"),
    api_key: document.getElementById("api-key"),
    project_id: document.getElementById("project-id"),
    test_btn: document.getElementById("test-btn"),
    test_status: document.getElementById("test-status"),
    save_btn: document.getElementById("save-btn"),
    saved_msg: document.getElementById("saved-msg"),
    cb_chatgpt: document.getElementById("cb-chatgpt"),
    cb_claude: document.getElementById("cb-claude"),
    cb_gemini: document.getElementById("cb-gemini"),
    cb_perplexity: document.getElementById("cb-perplexity"),
  };

  chrome.storage.sync.get(["endpoint", "api_key", "project_id", "paused", "platforms"], (stored_config) => {
    const config = merge_with_defaults(stored_config);
    apply_config_to_form(elements, config);
  });

  elements.test_btn.addEventListener("click", async () => {
    await test_connection(elements);
  });

  elements.save_btn.addEventListener("click", () => {
    const config = build_form_config(elements);
    chrome.storage.sync.set(config, () => {
      show_saved_message(elements);
    });
  });
}

function merge_with_defaults(stored_config) {
  return {
    endpoint: stored_config?.endpoint || default_config.endpoint,
    api_key: stored_config?.api_key || default_config.api_key,
    project_id: stored_config?.project_id || default_config.project_id,
    paused: Boolean(stored_config?.paused),
    platforms: {
      chatgpt: stored_config?.platforms?.chatgpt ?? default_config.platforms.chatgpt,
      claude: stored_config?.platforms?.claude ?? default_config.platforms.claude,
      gemini: stored_config?.platforms?.gemini ?? default_config.platforms.gemini,
      perplexity: stored_config?.platforms?.perplexity ?? default_config.platforms.perplexity,
    },
  };
}

function apply_config_to_form(elements, config) {
  elements.endpoint.value = config.endpoint;
  elements.api_key.value = config.api_key;
  elements.project_id.value = config.project_id;
  elements.cb_chatgpt.checked = config.platforms.chatgpt;
  elements.cb_claude.checked = config.platforms.claude;
  elements.cb_gemini.checked = config.platforms.gemini;
  elements.cb_perplexity.checked = config.platforms.perplexity;
}

async function test_connection(elements) {
  const endpoint = normalize_endpoint(elements.endpoint.value.trim() || "http://localhost:8000");

  elements.test_btn.disabled = true;
  set_test_status(elements, "Testing...", "status-neutral");

  try {
    const response = await fetch(`${endpoint}/health`, {
      signal: AbortSignal.timeout(5000),
    });

    if (response.ok) {
      set_test_status(elements, "Connected", "status-success");
      return;
    }
  } catch (_error) {}

  set_test_status(elements, "Cannot reach server", "status-error");
  elements.test_btn.disabled = false;
}

function set_test_status(elements, message, class_name) {
  elements.test_status.hidden = false;
  elements.test_status.textContent = message;
  elements.test_status.className = `status-chip ${class_name}`;

  if (message === "Connected" || message === "Cannot reach server") {
    elements.test_btn.disabled = false;
  }
}

function build_form_config(elements) {
  return {
    endpoint: normalize_endpoint(elements.endpoint.value.trim() || "http://localhost:8000"),
    api_key: elements.api_key.value.trim(),
    project_id: elements.project_id.value.trim() || "browser",
    paused: false,
    platforms: {
      chatgpt: elements.cb_chatgpt.checked,
      claude: elements.cb_claude.checked,
      gemini: elements.cb_gemini.checked,
      perplexity: elements.cb_perplexity.checked,
    },
  };
}

function show_saved_message(elements) {
  elements.saved_msg.hidden = false;

  if (saved_message_timer !== null) {
    clearTimeout(saved_message_timer);
  }

  saved_message_timer = window.setTimeout(() => {
    elements.saved_msg.hidden = true;
  }, 2000);
}

function normalize_endpoint(endpoint) {
  return endpoint.replace(/\/+$/, "");
}
