function normalizeOrigin(value) {
  if (!value) {
    throw new Error("BACKEND_ORIGIN is required.");
  }
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

function sanitizeHeaders(request, env) {
  const headers = new Headers(request.headers);
  headers.set("x-forwarded-host", new URL(request.url).host);
  headers.set("x-forwarded-proto", "https");

  if (env.PUBLIC_BASE_URL) {
    headers.set("x-agentic-memory-public-base-url", env.PUBLIC_BASE_URL);
  }

  return headers;
}

export default {
  async fetch(request, env) {
    const origin = normalizeOrigin(env.BACKEND_ORIGIN);
    const incomingUrl = new URL(request.url);
    const upstreamUrl = new URL(`${origin}${incomingUrl.pathname}${incomingUrl.search}`);

    const upstreamRequest = new Request(upstreamUrl, {
      method: request.method,
      headers: sanitizeHeaders(request, env),
      body: request.body,
      redirect: "manual",
    });

    const response = await fetch(upstreamRequest);
    const responseHeaders = new Headers(response.headers);

    if (env.PUBLIC_BASE_URL) {
      responseHeaders.set("x-agentic-memory-public-base-url", env.PUBLIC_BASE_URL);
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  },
};
