# Healthcare experiments web dashboard

Read-only UI + API over the Postgres projection described in
[`../DASHBOARD_BUILD_AGENT_PROMPT.md`](../DASHBOARD_BUILD_AGENT_PROMPT.md).

## Layout

- [`server/`](server/) — FastAPI + `psycopg` pool; serves `/api/*` and (after build) static assets from `server/static/` (that folder is gitignored — always run the UI build before deploying).
- [`ui/`](ui/) — Vite + React; `npm run build` writes into `server/static/`.

## Local development

**Terminal A — API** (from `server/`):

```bash
cd experiments/healthcare/dashboard/web/server
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://healthcare:healthcare@127.0.0.1:5432/healthcare_experiments"
export PORT=8787
python -m healthcare_dashboard
```

**Terminal B — UI** (from `ui/`):

```bash
cd experiments/healthcare/dashboard/web/ui
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8787`.

## Production on Hetzner (loopback + Cloudflare Tunnel)

1. **Postgres** stays on `127.0.0.1:5432` (Docker bind from the main healthcare docs). Do not expose it publicly.
2. **Build the UI** on any machine with Node, or on the VM:

   ```bash
   cd experiments/healthcare/dashboard/web/ui
   npm ci
   npm run build
   ```

   Confirm `server/static/index.html` exists.

3. **Run the API** bound to loopback only:

   ```bash
   cd experiments/healthcare/dashboard/web/server
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   export DATABASE_URL="postgresql://healthcare:healthcare@127.0.0.1:5432/healthcare_experiments"
   export HOST=127.0.0.1
   export PORT=8787
   python -m healthcare_dashboard
   ```

4. **Cloudflare Tunnel** — point the public hostname at `http://127.0.0.1:8787` (or whichever `PORT` you set). Prefer **Cloudflare Access** on that hostname so the dashboard is not world-readable.

### Optional: systemd unit

`/etc/systemd/system/healthcare-dashboard.service`:

```ini
[Unit]
Description=Healthcare experiments dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/agentic-memory/experiments/healthcare/dashboard/web/server
EnvironmentFile=/etc/healthcare-dashboard.env
ExecStart=/root/agentic-memory/experiments/healthcare/dashboard/web/server/.venv/bin/python -m healthcare_dashboard
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`/etc/healthcare-dashboard.env` (example):

```env
DATABASE_URL=postgresql://healthcare:healthcare@127.0.0.1:5432/healthcare_experiments
HOST=127.0.0.1
PORT=8787
```

Then: `systemctl daemon-reload && systemctl enable --now healthcare-dashboard`.

## API quick check

- `GET /api/health` — process up.
- `GET /api/health/db` — `SELECT 1` against Postgres.
- `GET /api/runs`, `/api/arms/summary`, `/api/answers`, `/api/poor-tasks`, etc.

## Data refresh

After new result JSON is normalized and loaded into Postgres, reload the UI; no app restart is required.
