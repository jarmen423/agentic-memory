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
const openClawForm = document.getElementById("openclaw-form");
const openClawWorkspaceInput = document.getElementById("openclaw-workspace-id");
const openClawDeviceInput = document.getElementById("openclaw-device-id");
const openClawAgentInput = document.getElementById("openclaw-agent-id");
const openClawMemoryPill = document.getElementById("openclaw-memory-pill");
const openClawContextPill = document.getElementById("openclaw-context-pill");
const openClawNote = document.getElementById("openclaw-note");
const openClawContextButton = document.getElementById("openclaw-context-button");
const openClawVerifyButton = document.getElementById("openclaw-verify-button");

const integrationMap = [
  { surface: "browser_extension", target: "chatgpt" },
  { surface: "acp_proxy", target: "cli" },
  { surface: "mcp_client", target: "claude_desktop" },
  { surface: "openclaw_memory", target: "workspace" },
  { surface: "openclaw_context_engine", target: "workspace" },
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
  renderOpenClawStatus(integrations);

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

function renderOpenClawStatus(integrations) {
  const memoryRecord = integrations.find(
    (item) => item.surface === "openclaw_memory" && item.target === "workspace",
  );
  const contextRecord = integrations.find(
    (item) => item.surface === "openclaw_context_engine" && item.target === "workspace",
  );

  setText(
    openClawMemoryPill,
    memoryRecord ? `Memory ${memoryRecord.status}` : "Memory pending",
  );
  setText(
    openClawContextPill,
    contextRecord ? `Context ${contextRecord.status}` : "Context pending",
  );
  openClawMemoryPill.dataset.status = memoryRecord?.status ?? "pending";
  openClawContextPill.dataset.status = contextRecord?.status ?? "pending";

  const workspaceId =
    memoryRecord?.config?.workspace_id ||
    contextRecord?.config?.workspace_id ||
    openClawWorkspaceInput.value ||
    "unassigned";
  const deviceId =
    memoryRecord?.config?.device_id ||
    contextRecord?.config?.device_id ||
    openClawDeviceInput.value ||
    "unknown";
  const agentId =
    memoryRecord?.config?.agent_id ||
    contextRecord?.config?.agent_id ||
    openClawAgentInput.value ||
    "unknown";

  setText(
    openClawNote,
    `Workspace ${workspaceId} is shared across devices. Device ${deviceId} and agent ${agentId} are tracked for memory and context testing.`,
  );
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

function loadOpenClawDraft() {
  openClawWorkspaceInput.value = localStorage.getItem("desktop_shell.openclaw.workspace_id") || "";
  openClawDeviceInput.value = localStorage.getItem("desktop_shell.openclaw.device_id") || "";
  openClawAgentInput.value = localStorage.getItem("desktop_shell.openclaw.agent_id") || "";
}

function saveOpenClawDraft() {
  localStorage.setItem("desktop_shell.openclaw.workspace_id", openClawWorkspaceInput.value.trim());
  localStorage.setItem("desktop_shell.openclaw.device_id", openClawDeviceInput.value.trim());
  localStorage.setItem("desktop_shell.openclaw.agent_id", openClawAgentInput.value.trim());
}

function buildOpenClawConfig() {
  return {
    workspace_id: openClawWorkspaceInput.value.trim() || null,
    device_id: openClawDeviceInput.value.trim() || null,
    agent_id: openClawAgentInput.value.trim() || null,
    source: "desktop_shell",
  };
}

/**
 * Build the identity payload the backend expects for OpenClaw routes.
 *
 * The shell reuses the same workspace/device/agent shape that the real
 * OpenClaw plugin package will send later, which lets this UI act as a
 * realistic setup and verification surface instead of a separate mock path.
 */
function buildOpenClawSessionPayload(contextEngine = "legacy") {
  const config = buildOpenClawConfig();
  return {
    workspace_id: config.workspace_id,
    device_id: config.device_id,
    agent_id: config.agent_id,
    session_id: `${config.workspace_id || "workspace"}:${config.device_id || "device"}:${config.agent_id || "agent"}:desktop-shell`,
    context_engine: contextEngine,
    metadata: {
      source: "desktop_shell",
    },
  };
}

async function setOpenClawIntegration(surface, status) {
  const config = buildOpenClawConfig();
  await postJson("/api/product/integrations", {
    surface,
    target: "workspace",
    status,
    config,
  });
}

function wireOpenClawForm() {
  loadOpenClawDraft();
  openClawForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      saveOpenClawDraft();
      await postJson("/api/openclaw/session/register", buildOpenClawSessionPayload("legacy"));
      await setOpenClawIntegration("openclaw_memory", "configured");
      await loadStatus();
      setFeedback("OpenClaw memory enabled.");
    } catch (error) {
      showError(error);
    }
  });

  openClawContextButton.addEventListener("click", async () => {
    try {
      saveOpenClawDraft();
      await postJson("/api/openclaw/session/register", buildOpenClawSessionPayload("agentic-memory"));
      await setOpenClawIntegration("openclaw_context_engine", "configured");
      await loadStatus();
      setFeedback("OpenClaw context engine enabled.");
    } catch (error) {
      showError(error);
    }
  });

  openClawVerifyButton.addEventListener("click", async () => {
    try {
      saveOpenClawDraft();
      const config = buildOpenClawConfig();
      const result = await postJson("/api/openclaw/context/resolve", {
        workspace_id: config.workspace_id,
        device_id: config.device_id,
        agent_id: config.agent_id,
        session_id: `${config.workspace_id || "workspace"}:${config.device_id || "device"}:${config.agent_id || "agent"}:desktop-shell-verify`,
        query: "Verify shared OpenClaw memory connectivity from the desktop shell.",
        limit: 3,
        metadata: {
          source: "desktop_shell",
          probe: true,
        },
      });
      await postJson("/api/product/events", {
        event_type: "openclaw_cross_device_test",
        actor: "desktop_shell",
        status: "ok",
        details: {
          ...config,
          block_count: result.context_blocks?.length || 0,
        },
      });
      await loadStatus();
      setFeedback("OpenClaw cross-device test completed.");
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
  wireOpenClawForm();
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
