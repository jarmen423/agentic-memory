const statusJson = document.getElementById("status-json");
const runtimeState = document.getElementById("runtime-state");
const runtimeNote = document.getElementById("runtime-note");
const repoCount = document.getElementById("repo-count");
const repoNote = document.getElementById("repo-note");
const backendUrl = document.getElementById("backend-url");
const backendAuth = document.getElementById("backend-auth");
const refreshButton = document.getElementById("refresh-button");
const repoForm = document.getElementById("repo-form");
const repoPathInput = document.getElementById("repo-path");
const repoLabelInput = document.getElementById("repo-label");
const actionFeedback = document.getElementById("action-feedback");
const markShellHealthyButton = document.getElementById("mark-shell-healthy-button");
const markRepoStepButton = document.getElementById("mark-repo-step-button");

const integrationMap = [
  { surface: "browser_extension", target: "chatgpt" },
  { surface: "acp_proxy", target: "cli" },
  { surface: "mcp_client", target: "claude_desktop" },
];

function setText(el, value) {
  el.textContent = value;
}

function setFeedback(message, isError = false) {
  setText(actionFeedback, message);
  actionFeedback.classList.toggle("error-text", isError);
}

function renderBootstrap(data) {
  setText(backendUrl, data.backend.url);
  setText(backendAuth, data.backend.auth_configured ? "Configured" : "Missing");
}

function renderProductStatus(data) {
  const runtimeStatus = data?.runtime?.server?.status ?? "unknown";
  const repoSummary = data?.summary?.repo_count ?? 0;
  const shellVersion = data?.runtime?.server?.version ?? "unknown";
  const integrations = data?.integrations ?? [];

  setText(runtimeState, runtimeStatus);
  setText(runtimeNote, `Shell sees backend version ${shellVersion}.`);
  setText(repoCount, String(repoSummary));
  setText(repoNote, `State file: ${data.state_path ?? "unknown"}`);
  statusJson.textContent = JSON.stringify(data, null, 2);

  integrationMap.forEach(({ surface, target }) => {
    const pill = document.querySelector(`[data-surface="${surface}"][data-target="${target}"]`);
    if (!pill) {
      return;
    }
    const record = integrations.find((item) => item.surface === surface && item.target === target);
    const status = record?.status ?? "pending";
    pill.dataset.status = status;
    setText(pill, status);
  });
}

async function loadBootstrap() {
  const response = await fetch("/api/bootstrap");
  if (!response.ok) {
    throw new Error(`Bootstrap failed: ${response.status}`);
  }
  renderBootstrap(await response.json());
}

async function loadStatus() {
  const response = await fetch("/api/product/status");
  if (!response.ok) {
    throw new Error(`Status request failed: ${response.status}`);
  }
  renderProductStatus(await response.json());
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function wireCopyButtons() {
  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const text = button.getAttribute("data-copy");
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
      setTimeout(() => {
        button.textContent = text;
      }, 1200);
    });
  });
}

function wireRepoForm() {
  repoForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const repoPath = repoPathInput.value.trim();
    const label = repoLabelInput.value.trim();
    if (!repoPath) {
      setFeedback("Repository path is required.", true);
      return;
    }

    try {
      await postJson("/api/product/repos", {
        repo_path: repoPath,
        label: label || null,
        metadata: { source: "desktop_shell" },
      });
      await postJson("/api/product/events", {
        event_type: "desktop_shell_repo_added",
        actor: "desktop_shell",
        status: "ok",
        details: { repo_path: repoPath },
      });
      await loadStatus();
      setFeedback(`Tracked repo: ${repoPath}`);
    } catch (error) {
      showError(error);
    }
  });
}

function wireActionButtons() {
  markShellHealthyButton.addEventListener("click", async () => {
    try {
      await postJson("/api/product/components/desktop_shell", {
        status: "healthy",
        details: { source: "desktop_shell_ui" },
      });
      await loadStatus();
      setFeedback("Marked desktop shell healthy.");
    } catch (error) {
      showError(error);
    }
  });

  markRepoStepButton.addEventListener("click", async () => {
    try {
      await postJson("/api/product/onboarding", {
        step: "repo_added",
        completed: true,
      });
      await loadStatus();
      setFeedback("Marked repo onboarding step complete.");
    } catch (error) {
      showError(error);
    }
  });

  document.querySelectorAll(".integration-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const surface = button.dataset.surface;
      const target = button.dataset.target;
      const status = button.dataset.status || "configured";
      try {
        await postJson("/api/product/integrations", {
          surface,
          target,
          status,
          config: { source: "desktop_shell" },
        });
        await loadStatus();
        setFeedback(`Updated integration: ${surface} -> ${target}`);
      } catch (error) {
        showError(error);
      }
    });
  });

  document.querySelectorAll(".component-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const component = button.dataset.component;
      const status = button.dataset.status || "healthy";
      try {
        await postJson(`/api/product/components/${component}`, {
          status,
          details: { source: "desktop_shell" },
        });
        await loadStatus();
        setFeedback(`Updated component: ${component}`);
      } catch (error) {
        showError(error);
      }
    });
  });

  document.querySelectorAll(".onboarding-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const step = button.dataset.step;
      try {
        await postJson("/api/product/onboarding", {
          step,
          completed: true,
        });
        await loadStatus();
        setFeedback(`Marked onboarding step complete: ${step}`);
      } catch (error) {
        showError(error);
      }
    });
  });
}

async function init() {
  wireCopyButtons();
  wireRepoForm();
  wireActionButtons();
  refreshButton.addEventListener("click", () => loadStatus().catch(showError));

  try {
    await loadBootstrap();
    await loadStatus();
    setFeedback("Shell connected.");
  } catch (error) {
    showError(error);
  }
}

function showError(error) {
  const message = error instanceof Error ? error.message : String(error);
  setText(runtimeState, "unavailable");
  setText(runtimeNote, message);
  setText(repoCount, "0");
  setText(repoNote, "Check the local backend URL and API key.");
  statusJson.textContent = message;
  setFeedback(message, true);
}

init();
