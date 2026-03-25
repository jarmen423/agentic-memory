(() => {
  const BUNDLED_SELECTORS = {
    version: 1,
    platforms: {
      chatgpt: {
        url_pattern: "chat.openai.com|chatgpt.com",
        session_id_regex: "/c/([a-z0-9-]+)",
        messages_container: "[data-testid='conversation-turns']",
        user_message: "[data-message-author-role='user']",
        assistant_message: "[data-message-author-role='assistant']",
        message_content: ".markdown, .whitespace-pre-wrap",
      },
      claude: {
        url_pattern: "claude.ai",
        session_id_regex: "/chat/([a-z0-9-]+)",
        messages_container: "[data-testid='conversation'], body",
        user_message: "[data-testid='user-message']",
        assistant_message: ".font-claude-response, .font-claude-message, [data-testid='assistant-message']",
        message_content: null,
      },
      gemini: {
        url_pattern: "gemini.google.com",
        session_id_regex: "/app/([a-z0-9]+)",
        messages_container: "chat-window, .conversation-container",
        user_message: "user-query",
        assistant_message: "model-response",
        message_content: "div.query-content, message-content",
      },
      perplexity: {
        _note: "LOW confidence selectors - verify via hotpatch",
        url_pattern: "perplexity.ai",
        session_id_regex: "/search/([a-z0-9-]+)",
        messages_container: "[class*='ConversationMessage'], .prose",
        user_message: "[class*='UserMessage']",
        assistant_message: "[class*='AnswerSection'], [class*='AssistantMessage']",
        message_content: null,
      },
    },
  };

  const ADAPTERS = {
    chatgpt: globalThis.ChatGPTAdapter,
    claude: globalThis.ClaudeAdapter,
    gemini: globalThis.GeminiAdapter,
    perplexity: globalThis.PerplexityAdapter,
  };

  function detect_platform(hostname) {
    if (hostname.includes("chat.openai.com") || hostname.includes("chatgpt.com")) {
      return "chatgpt";
    }
    if (hostname.includes("claude.ai")) {
      return "claude";
    }
    if (hostname.includes("gemini.google.com")) {
      return "gemini";
    }
    if (hostname.includes("perplexity.ai")) {
      return "perplexity";
    }
    return null;
  }

  const detectPlatform = detect_platform;

  async function load_selectors(platform, endpoint) {
    let selectors = BUNDLED_SELECTORS.platforms[platform];

    try {
      const response = await fetch(`${endpoint}/ext/selectors.json`);
      if (response.ok) {
        const remote = await response.json();
        if (remote.platforms?.[platform]) {
          selectors = remote.platforms[platform];
        }
      }
    } catch {}

    return selectors;
  }

  (async () => {
    const platform = detectPlatform(window.location.hostname);
    if (!platform) {
      return;
    }

    const config = await chrome.storage.sync.get(["endpoint", "platforms", "paused"]);
    if (config.paused) {
      return;
    }
    if (config.platforms && config.platforms[platform] === false) {
      return;
    }

    const endpoint = (config.endpoint || "http://localhost:8000").replace(/\/$/, "");
    const selectors = await load_selectors(platform, endpoint);
    const AdapterClass = ADAPTERS[platform];
    if (!AdapterClass) {
      return;
    }

    const adapter = new AdapterClass(platform, selectors);
    adapter.start();

    let last_url = window.location.href;
    const spa_observer = new MutationObserver(() => {
      if (window.location.href !== last_url) {
        last_url = window.location.href;
        adapter.stop?.();
        setTimeout(() => {
          adapter._session_id = adapter._extractSessionId();
          adapter._last_turn_count = 0;
          adapter._turn_index = 0;
          adapter.start();
        }, 200);
      }
    });

    if (document.body) {
      spa_observer.observe(document.body, { subtree: true, childList: true });
    }
  })();
})();
