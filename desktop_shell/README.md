# Agentic Memory Desktop Shell

Minimal local web shell for the control plane.

## What It Does

- Shows a live status view from the existing `am-server` product API.
- Surfaces placeholder cards for browser extension, ACP proxy, and MCP client integrations.
- Gives you a simple dev path without Electron or Tauri.

## Run It

Start the product API backend first:

```powershell
python -m am_server.server
```

Then start the shell:

```powershell
python -m desktop_shell --backend-url http://127.0.0.1:8765
```

If you need to point at a different backend or port:

```powershell
python -m desktop_shell --backend-url http://127.0.0.1:8765 --host 127.0.0.1 --port 3030
```

## Environment Variables

- `DESKTOP_SHELL_BACKEND_URL`
- `DESKTOP_SHELL_API_KEY`
- `DESKTOP_SHELL_HOST`
- `DESKTOP_SHELL_PORT`
