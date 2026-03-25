import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";

// Pure logic mirrored from adapters/base.js.
function extract_session_id(pathname, regex_str) {
  const match = pathname.match(new RegExp(regex_str));
  return match ? match[1] : `fallback-${Date.now()}`;
}

function make_debounce(callback, delay_ms) {
  let timer = null;

  return function debounced() {
    clearTimeout(timer);
    timer = setTimeout(callback, delay_ms);
  };
}

function query_first(selector_list, doc) {
  if (!selector_list) {
    return null;
  }

  return selector_list
    .split(",")
    .map((selector) => doc.querySelector(selector.trim()))
    .find((element) => element != null) || null;
}

function make_doc(matches = {}) {
  const seen_selectors = [];

  return {
    seen_selectors,
    querySelector(selector) {
      seen_selectors.push(selector);
      return matches[selector] ?? null;
    },
  };
}

describe("extract_session_id", () => {
  test("extracts chatgpt session ids", () => {
    assert.equal(
      extract_session_id("/c/abc123-def456", "/c/([a-z0-9-]+)"),
      "abc123-def456"
    );
  });

  test("extracts claude session ids", () => {
    assert.equal(
      extract_session_id("/chat/xyz789", "/chat/([a-z0-9-]+)"),
      "xyz789"
    );
  });

  test("extracts gemini session ids", () => {
    assert.equal(
      extract_session_id("/app/abc123", "/app/([a-z0-9]+)"),
      "abc123"
    );
  });

  test("extracts perplexity session ids", () => {
    assert.equal(
      extract_session_id("/search/qwe123", "/search/([a-z0-9-]+)"),
      "qwe123"
    );
  });

  test("falls back when the url does not match", () => {
    assert.match(
      extract_session_id("/unknown/path", "/c/([a-z0-9-]+)"),
      /^fallback-\d+$/
    );
  });
});

describe("make_debounce", () => {
  test("fires once after 800ms when called rapidly", async () => {
    let call_count = 0;
    const debounced = make_debounce(() => {
      call_count += 1;
    }, 800);

    debounced();
    debounced();
    debounced();

    assert.equal(call_count, 0);
    await delay(850);
    assert.equal(call_count, 1);
  });

  test("fires after 800ms for a single call and not before", async () => {
    let call_count = 0;
    const debounced = make_debounce(() => {
      call_count += 1;
    }, 800);

    debounced();

    await delay(700);
    assert.equal(call_count, 0);

    await delay(150);
    assert.equal(call_count, 1);
  });
});

describe("query_first", () => {
  test("returns the first matching selector from a comma-separated list", () => {
    const present = { tagName: "SPAN" };
    const doc = make_doc({
      "span.present": present,
    });

    assert.equal(query_first("div.missing, span.present", doc), present);
    assert.deepEqual(doc.seen_selectors, ["div.missing", "span.present"]);
  });

  test("returns null when no selectors match", () => {
    const doc = make_doc();

    assert.equal(query_first("div.missing, span.also-missing", doc), null);
    assert.deepEqual(doc.seen_selectors, ["div.missing", "span.also-missing"]);
  });

  test("trims whitespace from each selector before querying", () => {
    const trimmed = { tagName: "SPAN" };
    const doc = make_doc({
      "span.trimmed": trimmed,
    });

    assert.equal(query_first(" div.spaced , span.trimmed ", doc), trimmed);
    assert.deepEqual(doc.seen_selectors, ["div.spaced", "span.trimmed"]);
  });
});
