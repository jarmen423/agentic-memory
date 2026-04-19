function normalizeOrigin(value) {
  if (!value) {
    throw new Error("BACKEND_ORIGIN is required.");
  }
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

function rewriteRedirectLocation(location, backendOrigin, publicBaseUrl) {
  if (!location || !publicBaseUrl) {
    return location;
  }

  if (location.startsWith(`${backendOrigin}/`) || location === backendOrigin) {
    return `${publicBaseUrl}${location.slice(backendOrigin.length)}`;
  }

  return location;
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

function openAIAppsChallengeResponse(env) {
  const token = String(env.OPENAI_APPS_CHALLENGE_TOKEN || "").trim();
  if (!token) {
    return new Response("Challenge token not configured.", { status: 404 });
  }

  return new Response(token, {
    status: 200,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

export default {
  async fetch(request, env) {
    const origin = normalizeOrigin(env.BACKEND_ORIGIN);
    const publicBaseUrl = env.PUBLIC_BASE_URL ? normalizeOrigin(env.PUBLIC_BASE_URL) : "";
    const incomingUrl = new URL(request.url);

    if (
      incomingUrl.pathname === "/.well-known/openai-apps-challenge" &&
      request.method === "GET"
    ) {
      return openAIAppsChallengeResponse(env);
    }

    const upstreamUrl = new URL(`${origin}${incomingUrl.pathname}${incomingUrl.search}`);

    const upstreamRequest = new Request(upstreamUrl, {
      method: request.method,
      headers: sanitizeHeaders(request, env),
      body: request.body,
      redirect: "manual",
    });

    const response = await fetch(upstreamRequest);
    const responseHeaders = new Headers(response.headers);
    const rewrittenLocation = rewriteRedirectLocation(
      responseHeaders.get("location"),
      origin,
      publicBaseUrl,
    );

    if (rewrittenLocation) {
      responseHeaders.set("location", rewrittenLocation);
    }

    if (publicBaseUrl) {
      responseHeaders.set("x-agentic-memory-public-base-url", publicBaseUrl);
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  },
};
