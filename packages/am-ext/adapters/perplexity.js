class PerplexityAdapter extends BaseAdapter {
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
      .map((element) => ({
        role: element.matches(this.selectors.user_message) ? "user" : "assistant",
        content: (element.querySelector(this.selectors.message_content) || element).innerText.trim(),
      }))
      .filter((turn) => turn.content);
  }
}

globalThis.PerplexityAdapter = PerplexityAdapter;
