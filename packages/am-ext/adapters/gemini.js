class GeminiAdapter extends BaseAdapter {
  _extractAllTurns() {
    const all = [...document.querySelectorAll("user-query, model-response")]
      .sort((a, b) => {
        if (a === b) {
          return 0;
        }
        return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
      });

    return all
      .map((element) => {
        const is_user = element.tagName.toLowerCase() === "user-query";
        const content_element = is_user
          ? element.querySelector("div.query-content")
          : element.querySelector("message-content");

        return {
          role: is_user ? "user" : "assistant",
          content: (content_element || element).innerText.trim(),
        };
      })
      .filter((turn) => turn.content);
  }
}

globalThis.GeminiAdapter = GeminiAdapter;
