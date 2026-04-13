"""Public HTML pages for product overview, legal text, and support contacts.

These routes exist so marketplace and directory submissions can point at stable
HTTPS URLs (privacy, terms, support, DPA) without exposing authenticated APIs.
Content is static markup rendered through a shared layout helper.

**Router contract**

- Tag ``publication`` for OpenAPI grouping (individual routes may set
  ``include_in_schema=False``).
- No API-key dependency: intended for unauthenticated crawlers and reviewers.

**Response shapes**

- Most handlers return ``HTMLResponse`` with inline CSS and navigation.
- The publication root issues an HTTP redirect to the main overview path.

**Dependencies**

- ``fastapi.APIRouter``, ``HTMLResponse``, ``RedirectResponse`` only; no app
  services or databases.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["publication"])

PUBLICATION_ROOT = "/publication"
PUBLICATION_WEBSITE_PATH = f"{PUBLICATION_ROOT}/agentic-memory"
PUBLICATION_PRIVACY_PATH = f"{PUBLICATION_ROOT}/privacy"
PUBLICATION_TERMS_PATH = f"{PUBLICATION_ROOT}/terms"
PUBLICATION_SUPPORT_PATH = f"{PUBLICATION_ROOT}/support"
PUBLICATION_DPA_PATH = f"{PUBLICATION_ROOT}/dpa"

REPOSITORY_URL = "https://github.com/jarmen423/agentic-memory"
ISSUES_URL = f"{REPOSITORY_URL}/issues"


def _page_html(*, title: str, description: str, body: str) -> HTMLResponse:
    """Build a full HTML document with shared chrome (nav, footer, styles).

    Args:
        title: Document ``<title>`` and main ``<h1>`` heading text.
        description: Short meta description and header lede paragraph.
        body: Inner HTML for the ``<article>`` (caller supplies headings and copy).

    Returns:
        ``HTMLResponse`` with UTF-8 HTML and publication-themed styling.
    """

    nav = (
        f'<a href="{PUBLICATION_WEBSITE_PATH}">Overview</a>'
        f'<a href="{PUBLICATION_PRIVACY_PATH}">Privacy</a>'
        f'<a href="{PUBLICATION_TERMS_PATH}">Terms</a>'
        f'<a href="{PUBLICATION_SUPPORT_PATH}">Support</a>'
        f'<a href="{PUBLICATION_DPA_PATH}">DPA</a>'
    )
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <meta name="description" content="{description}" />
    <style>
      :root {{
        color-scheme: light;
        --bg: #f3f0e8;
        --paper: #fffdf8;
        --ink: #1f2a1f;
        --muted: #5a655b;
        --accent: #21543d;
        --rule: #d9d2c2;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: Georgia, "Times New Roman", serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, #efe6d1 0, transparent 36rem),
          linear-gradient(180deg, #f8f4ea 0%, var(--bg) 100%);
      }}
      .page {{
        max-width: 900px;
        margin: 0 auto;
        padding: 40px 24px 72px;
      }}
      header {{
        border-bottom: 1px solid var(--rule);
        margin-bottom: 28px;
        padding-bottom: 20px;
      }}
      .eyebrow {{
        margin: 0 0 8px;
        font-size: 0.8rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      h1 {{
        margin: 0 0 10px;
        font-size: clamp(2rem, 4vw, 3.25rem);
        line-height: 1.04;
      }}
      .lede {{
        margin: 0;
        max-width: 48rem;
        font-size: 1.05rem;
        line-height: 1.6;
        color: var(--muted);
      }}
      nav {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 18px;
      }}
      nav a {{
        color: var(--accent);
        text-decoration: none;
        border-bottom: 1px solid transparent;
      }}
      nav a:hover {{
        border-color: var(--accent);
      }}
      article {{
        background: color-mix(in srgb, var(--paper) 92%, white);
        border: 1px solid var(--rule);
        border-radius: 18px;
        padding: 24px;
        box-shadow: 0 16px 40px rgba(36, 42, 36, 0.06);
      }}
      h2, h3 {{
        margin-top: 1.6em;
      }}
      h2:first-child, h3:first-child {{
        margin-top: 0;
      }}
      p, li {{
        font-size: 1rem;
        line-height: 1.65;
      }}
      ul {{
        padding-left: 1.2rem;
      }}
      .grid {{
        display: grid;
        gap: 18px;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        margin: 22px 0;
      }}
      .card {{
        border: 1px solid var(--rule);
        border-radius: 14px;
        padding: 16px;
        background: rgba(255, 255, 255, 0.62);
      }}
      .card h3 {{
        margin: 0 0 8px;
        font-size: 1rem;
      }}
      a {{
        color: var(--accent);
      }}
      .muted {{
        color: var(--muted);
      }}
      footer {{
        margin-top: 22px;
        color: var(--muted);
        font-size: 0.95rem;
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <header>
        <p class="eyebrow">Agentic Memory Publication</p>
        <h1>{title}</h1>
        <p class="lede">{description}</p>
        <nav>{nav}</nav>
      </header>
      <article>{body}</article>
      <footer>
        <p>Canonical repository: <a href="{REPOSITORY_URL}">{REPOSITORY_URL}</a></p>
      </footer>
    </main>
  </body>
</html>
"""
    return HTMLResponse(html)


@router.get(PUBLICATION_ROOT, include_in_schema=False)
def publication_root() -> RedirectResponse:
    """Redirect ``/publication`` to the canonical product overview URL.

    Returns:
        HTTP 307 Temporary Redirect to ``PUBLICATION_WEBSITE_PATH``.
    """
    return RedirectResponse(PUBLICATION_WEBSITE_PATH, status_code=307)


@router.get(PUBLICATION_WEBSITE_PATH, response_class=HTMLResponse, include_in_schema=False)
def publication_website() -> HTMLResponse:
    """Serve the primary public product overview and connector contract summary.

    Returns:
        ``HTMLResponse`` describing MCP surfaces (OpenAI, Anthropic, Codex paths)
        and high-level public tool policy bullets.
    """

    body = f"""
<h2>What Agentic Memory does</h2>
<p>
  Agentic Memory is a hosted MCP service that gives AI agents persistent,
  searchable memory across code, research, and conversations. The public
  connector surface exposes bounded retrieval tools plus explicit memory-write
  tools while keeping indexing and admin operations out of the published
  contract.
</p>
<div class="grid">
  <section class="card">
    <h3>OpenAI</h3>
    <p>Canonical reviewer endpoint: <code>/mcp-openai</code></p>
  </section>
  <section class="card">
    <h3>Anthropic</h3>
    <p>Canonical reviewer endpoint: <code>/mcp-claude</code></p>
  </section>
  <section class="card">
    <h3>Codex Preflight</h3>
    <p>Local plugin bundle targets the hosted MCP surface at <code>/mcp-codex</code>.</p>
  </section>
</div>
<h2>Public contract summary</h2>
<ul>
  <li>Public read tools cover code search, dependency lookup, execution tracing, unified memory search, web-memory search, and conversation retrieval.</li>
  <li>Public write tools are limited to private Agentic Memory backend state.</li>
  <li>The public connector surface does not publish to the public internet.</li>
  <li>The chosen authenticated publication model is OAuth 2.0 authorization code flow once public auth is enabled.</li>
  <li>Claude Code support should only be claimed after the direct OAuth/network path is validated.</li>
</ul>
<h2>Operational links</h2>
<ul>
  <li><a href="{PUBLICATION_PRIVACY_PATH}">Privacy Policy</a></li>
  <li><a href="{PUBLICATION_TERMS_PATH}">Terms of Service</a></li>
  <li><a href="{PUBLICATION_SUPPORT_PATH}">Support</a></li>
  <li><a href="{PUBLICATION_DPA_PATH}">Data Processing Addendum</a></li>
  <li><a href="{ISSUES_URL}">Issue Tracker</a></li>
</ul>
<p class="muted">
  This page is intended to be the stable product/company URL for publication
  submissions until a broader marketing site replaces it.
</p>
"""
    return _page_html(
        title="Agentic Memory",
        description=(
            "Hosted MCP memory for code, research, and conversations, with a "
            "bounded public connector contract for ChatGPT, Codex, and Claude."
        ),
        body=body,
    )


@router.get(PUBLICATION_PRIVACY_PATH, response_class=HTMLResponse, include_in_schema=False)
def publication_privacy() -> HTMLResponse:
    """Serve the public privacy notice for hosted connector surfaces.

    Returns:
        ``HTMLResponse`` covering data categories, use, minimization, subprocessors,
        retention, and contact via the support page.
    """

    body = """
<h2>Scope</h2>
<p>
  This privacy notice covers the hosted Agentic Memory public connector
  surfaces exposed through the Agentic Memory MCP service.
</p>
<h2>Data categories</h2>
<ul>
  <li>Code snippets, file paths, and repository metadata intentionally sent through tool calls.</li>
  <li>Conversation-memory content intentionally stored through explicit memory-write operations.</li>
  <li>Research-memory content intentionally stored through explicit research-ingest operations.</li>
  <li>Operational telemetry needed to run the service, prevent abuse, and diagnose failures.</li>
</ul>
<h2>How data is used</h2>
<ul>
  <li>To execute retrieval and memory-write tool calls requested by the user.</li>
  <li>To operate, monitor, secure, and improve the hosted Agentic Memory service.</li>
  <li>To investigate abuse, reliability issues, or support requests.</li>
</ul>
<h2>Data minimization</h2>
<ul>
  <li>The public connector contract excludes admin and indexing tools.</li>
  <li>Public tools should return only the data needed for the user task.</li>
  <li>The service should not collect payment card data, PHI, government identifiers, or raw credentials as part of normal operation.</li>
  <li>The public tool surface does not intentionally expose internal request ids, trace ids, or debug payloads to end users unless operationally required.</li>
</ul>
<h2>Third-party processing</h2>
<p>
  Agentic Memory may rely on infrastructure, storage, and model providers needed
  to operate the hosted service. Those providers process data only as needed to
  deliver the service and its underlying platform capabilities.
</p>
<h2>Retention and deletion</h2>
<p>
  Stored memory may persist until deleted, replaced, or removed through service
  operations. Privacy, deletion, and support requests should be initiated
  through the support channel linked on the Support page.
</p>
<h2>Contact</h2>
<p>
  For privacy or support questions, start with the <a href="/publication/support">Support page</a>.
</p>
"""
    return _page_html(
        title="Privacy Policy",
        description="Privacy notice for the hosted Agentic Memory public connector surfaces.",
        body=body,
    )


@router.get(PUBLICATION_TERMS_PATH, response_class=HTMLResponse, include_in_schema=False)
def publication_terms() -> HTMLResponse:
    """Serve baseline terms of service for the hosted connector product.

    Returns:
        ``HTMLResponse`` with scope, acceptable use, availability, enforcement, and
        support pointers (explicitly marked as pre-legal-review copy).
    """

    body = """
<h2>Service scope</h2>
<p>
  Agentic Memory provides hosted MCP endpoints and related tooling for memory
  retrieval and explicit memory writes across code, research, and conversations.
</p>
<h2>Acceptable use</h2>
<ul>
  <li>Use the service only for lawful purposes and in ways that comply with platform policies.</li>
  <li>Do not attempt to abuse, overload, reverse engineer, or circumvent service protections.</li>
  <li>Do not use the service to submit secrets or highly regulated data unless you have separately verified that the service is appropriate for that use.</li>
</ul>
<h2>Availability</h2>
<p>
  The service may change over time. Features may be updated, limited, or
  removed for security, legal, operational, or product reasons.
</p>
<h2>Suspension and removal</h2>
<p>
  Agentic Memory may suspend, limit, or remove access where needed to address
  abuse, legal risk, security concerns, or service instability.
</p>
<h2>Support and notices</h2>
<p>
  For product support, privacy questions, or publication-related issues, use
  the <a href="/publication/support">Support page</a>.
</p>
<p class="muted">
  These terms are intended to provide baseline public publication language for
  the hosted connector surfaces. They should receive legal review before being
  used as the final long-term public terms for enterprise commitments.
</p>
"""
    return _page_html(
        title="Terms of Service",
        description="Baseline public terms for the hosted Agentic Memory connector surfaces.",
        body=body,
    )


@router.get(PUBLICATION_SUPPORT_PATH, response_class=HTMLResponse, include_in_schema=False)
def publication_support() -> HTMLResponse:
    """Serve the public support and issue-tracker entrypoint.

    Returns:
        ``HTMLResponse`` listing GitHub issues/repository links and guidance for
        safe public bug reports.
    """

    body = f"""
<h2>Support channels</h2>
<p>
  Public support for Agentic Memory currently runs through the repository issue
  tracker.
</p>
<ul>
  <li>Issue tracker: <a href="{ISSUES_URL}">{ISSUES_URL}</a></li>
  <li>Repository: <a href="{REPOSITORY_URL}">{REPOSITORY_URL}</a></li>
</ul>
<h2>Use this page for</h2>
<ul>
  <li>Connector setup and connectivity issues</li>
  <li>Review/demo account issues</li>
  <li>Bug reports and public documentation corrections</li>
  <li>Privacy and data-handling questions</li>
</ul>
<h2>Before opening a public issue</h2>
<ul>
  <li>Do not include secrets, API keys, passwords, or private repository contents.</li>
  <li>For sensitive requests, describe the issue at a high level and ask for a private follow-up channel.</li>
  <li>Reference the platform, connector surface, and approximate time of failure when reporting operational issues.</li>
</ul>
"""
    return _page_html(
        title="Support",
        description="Support and contact entrypoint for the hosted Agentic Memory connector surfaces.",
        body=body,
    )


@router.get(PUBLICATION_DPA_PATH, response_class=HTMLResponse, include_in_schema=False)
def publication_dpa() -> HTMLResponse:
    """Serve a stable DPA reference page for procurement and vendor reviews.

    Returns:
        ``HTMLResponse`` describing processing posture and how to request a
        formal data processing addendum via support.
    """

    body = """
<h2>Purpose</h2>
<p>
  This page exists so publication and procurement workflows have a stable URL
  for Agentic Memory's data-processing terms and DPA handling path.
</p>
<h2>Processing posture</h2>
<ul>
  <li>Agentic Memory processes data needed to provide hosted MCP retrieval and explicit memory-write functionality.</li>
  <li>Customers remain responsible for the lawfulness of the data they submit to the service.</li>
  <li>Agentic Memory uses infrastructure and service providers only as needed to operate the hosted product.</li>
</ul>
<h2>DPA requests</h2>
<p>
  If your procurement or compliance process requires a data processing
  addendum, start through the <a href="/publication/support">Support page</a>
  and reference your organization, use case, and required compliance terms.
</p>
<p class="muted">
  This publication URL is intended to satisfy directory and vendor-review
  workflows that request a stable DPA reference. If you require a negotiated or
  enterprise-specific addendum, contact support before production use.
</p>
"""
    return _page_html(
        title="Data Processing Addendum",
        description="Public DPA reference and request path for the hosted Agentic Memory service.",
        body=body,
    )
