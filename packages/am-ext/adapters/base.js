class BaseAdapter {
  constructor(platform, selectors) {
    this.platform = platform;
    this.selectors = selectors;
    this._debounce_timer = null;
    this._last_turn_count = 0;
    this._session_id = null;
    this._turn_index = 0;
    this._observer = null;
  }

  start() {
    this._session_id = this._extractSessionId();
    const container = this._queryFirst(this.selectors.messages_container);
    if (!container) {
      return;
    }

    this._observer = new MutationObserver(() => this._onMutation());
    this._observer.observe(container, { childList: true, subtree: true });
    this._captureNewTurns();
  }

  stop() {
    if (this._observer) {
      this._observer.disconnect();
      this._observer = null;
    }
    if (this._debounce_timer) {
      clearTimeout(this._debounce_timer);
      this._debounce_timer = null;
    }
  }

  _onMutation() {
    clearTimeout(this._debounce_timer);
    this._debounce_timer = setTimeout(() => this._captureNewTurns(), 800);
  }

  _captureNewTurns() {
    const turns = this._extractAllTurns();
    const new_turns = turns.slice(this._last_turn_count);
    new_turns.forEach((turn) => this._sendTurn(turn));
    this._last_turn_count = turns.length;
  }

  _sendTurn(turn) {
    chrome.runtime.sendMessage({
      type: "NEW_TURN",
      payload: {
        role: turn.role,
        content: turn.content,
        session_id: this._session_id,
        platform: this.platform,
        turn_index: this._turn_index++,
      },
    }).catch(() => {});
  }

  _extractSessionId() {
    const match = window.location.pathname.match(
      new RegExp(this.selectors.session_id_regex)
    );
    return match ? match[1] : `fallback-${Date.now()}`;
  }

  _queryFirst(selector_list) {
    if (!selector_list) {
      return null;
    }

    return selector_list
      .split(",")
      .map((selector) => document.querySelector(selector.trim()))
      .find((element) => element != null) || null;
  }

  _extractAllTurns() {
    const all = [...document.querySelectorAll(
      `${this.selectors.user_message}, ${this.selectors.assistant_message}`
    )].sort((a, b) => {
      if (a === b) {
        return 0;
      }
      return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    });

    return all
      .map((element) => {
        const content_element = this.selectors.message_content
          ? element.querySelector(this.selectors.message_content)
          : null;
        const content = (content_element || element).innerText.trim();
        return {
          role: element.matches(this.selectors.user_message) ? "user" : "assistant",
          content,
        };
      })
      .filter((turn) => turn.content);
  }
}

globalThis.BaseAdapter = BaseAdapter;
