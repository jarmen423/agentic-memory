# Agentic Memory Desktop Shell

Thin FastAPI host for the built `am-dashboard` workspace.

## What It Does

- Serves the static dashboard bundle from `D:\code\agentic-memory\desktop_shell\static`.
- Proxies authenticated `/api/*` calls into the backend product and OpenClaw routes.
- Keeps backend URL and API key handling in Python so the React app stays a static client bundle.
- Provides the local shell host for the Phase 13 OpenClaw dashboard wave without introducing Electron or Tauri.

## Run It

Start the product API backend first:

```powershell
python -m am_server.server
```

Build the dashboard bundle:

```powershell
npm run build --workspace am-dashboard
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

## Source Layout

- React source: `D:\code\agentic-memory\packages\am-dashboard`
- Built assets served by FastAPI: `D:\code\agentic-memory\desktop_shell\static`
- Shell host/proxy: `D:\code\agentic-memory\desktop_shell\app.py`
