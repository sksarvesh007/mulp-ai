# Self-hosted Langfuse — shareable trace dashboard

Runs the full Langfuse v3 stack (web · worker · Postgres · ClickHouse · Redis · MinIO),
giving a **public URL + login** you can hand to anyone to view every trace. Data persists
in Docker volumes.

Why not Hugging Face: Langfuse needs ~6 persistent services; HF Spaces is a single
ephemeral container, so it can't host it. Pick one of the two no-card paths below.

---

## Option A — GitHub Codespaces (recommended · free · no card)

A Codespace gives you Docker + a public HTTPS URL with **no credit card** (free accounts get
~120 core-hours/month). The URL isn't tied to your laptop.

1. On the GitHub repo: **Code ▸ Codespaces ▸ Create codespace on main** (a 2-core machine is
   enough; 4-core is snappier if offered).
2. In the Codespace terminal:
   ```bash
   cd deploy/langfuse
   chmod +x setup.sh codespace-up.sh && ./codespace-up.sh
   ```
   This generates secrets + project keys, sets `NEXTAUTH_URL` to the Codespace's forwarded
   URL, brings the stack up (first boot ~1–2 min for DB migrations), and flips **port 3000 to
   Public**. It prints the **URL + login** and the **backend env values**.
3. **For backend ingestion, also run** `chmod +x codespace-tunnel.sh && ./codespace-tunnel.sh`.
   GitHub's `*.app.github.dev` URL requires GitHub's auth handshake even when "public" — a
   browser can view it, but the **backend can't POST traces** to it (they get walled). This
   starts a free Cloudflare quick-tunnel (`*.trycloudflare.com`, no account/card) that is a
   real public endpoint for both viewing AND ingestion, and prints the URL + login + backend
   env. Share THAT URL and use it as `LANGFUSE_HOST`.

> The dashboard is reachable while the Codespace is running. Codespaces auto-stop after ~30 min
> idle; **Code ▸ Codespaces ▸ … ▸ Restart** brings it back with the same data and URL. Keep it
> running during a review/demo window.

## Option B — any VM (Oracle Always-Free, a VPS, etc.) — needs a card on most clouds

On a fresh Ubuntu VM, open TCP **3000** to the internet (cloud security-list/firewall), then:
```bash
git clone https://github.com/sksarvesh007/mulp-ai.git
cd mulp-ai/deploy/langfuse
chmod +x setup.sh && ./setup.sh
```
`setup.sh` installs Docker, generates secrets, detects the public IP for `NEXTAUTH_URL`, opens
the host firewall, and prints the URL/login + backend env. (On Oracle you must ALSO add an
ingress rule for TCP 3000 in the VCN security list.)

---

## Point the app's backend at it

On the Render **backend** service → Environment, set these (the script prints the exact
values), then redeploy:

| Key | Value |
|-----|-------|
| `ENABLE_OBSERVABILITY` | `true` |
| `LANGFUSE_HOST` | the printed URL (`https://…app.github.dev` or `http://<ip>:3000`) |
| `LANGFUSE_PUBLIC_KEY` | the `pk-lf-…` from the script output |
| `LANGFUSE_SECRET_KEY` | the `sk-lf-…` from the script output |

Run a claim → traces appear in the dashboard within a few seconds. The backend's keys
authenticate ingestion, so a public port is safe — viewing still requires the Langfuse login.

---

## Operating it

```bash
docker compose logs -f langfuse-web   # watch logs (run from deploy/langfuse)
docker compose ps                     # status
docker compose pull && docker compose up -d   # upgrade Langfuse
docker compose down                   # stop (data kept); add -v to also wipe data
```

Only port 3000 is exposed; Postgres/ClickHouse/Redis/MinIO stay on the internal Docker
network. Secrets are random per-install and live only in `.env` (chmod 600, git-ignored).
For a custom domain + HTTPS on a VM, put [Caddy](https://caddyserver.com) in front and re-run
with `LF_PUBLIC_URL=https://your-domain ./setup.sh`.
