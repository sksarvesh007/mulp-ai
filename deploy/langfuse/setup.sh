#!/usr/bin/env bash
# One-shot setup for self-hosted Langfuse on a fresh Ubuntu VM (e.g. Oracle Always-Free).
# Idempotent: re-running keeps the existing .env (and your data) and just brings the stack up.
#
#   chmod +x setup.sh && ./setup.sh
#
# Optional overrides (env vars):
#   LF_PUBLIC_URL   public URL users open (default: http://<detected-public-ip>:3000)
#   LF_ADMIN_EMAIL  admin login email     (default: admin@plum.local)
#   LF_ADMIN_PASSWORD  admin password     (default: a strong generated one, printed below)
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }

# ── 1. Docker ────────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker…"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi
DC="docker compose"; docker compose version >/dev/null 2>&1 || DC="docker-compose"
SUDO=""; docker ps >/dev/null 2>&1 || SUDO="sudo"   # group change needs re-login; fall back to sudo

# ── 2. .env (generate once; never overwrite existing → secrets + data stay stable) ──
if [ ! -f .env ]; then
  say "Generating .env with fresh secrets…"
  hex()  { openssl rand -hex "$1"; }                 # URL-safe (used in connection strings)
  b64()  { openssl rand -base64 "$1" | tr -d '\n'; } # for NEXTAUTH_SECRET / SALT
  PUBIP="$(curl -fsS --max-time 5 https://api.ipify.org || curl -fsS --max-time 5 https://ifconfig.me || echo CHANGE_ME)"
  PUBLIC_URL="${LF_PUBLIC_URL:-http://${PUBIP}:3000}"
  ADMIN_EMAIL="${LF_ADMIN_EMAIL:-admin@plum.local}"
  ADMIN_PASSWORD="${LF_ADMIN_PASSWORD:-$(b64 12)}"
  cat > .env <<EOF
NEXTAUTH_URL=${PUBLIC_URL}

LANGFUSE_INIT_USER_EMAIL=${ADMIN_EMAIL}
LANGFUSE_INIT_USER_PASSWORD=${ADMIN_PASSWORD}
LANGFUSE_INIT_USER_NAME=Admin
LANGFUSE_INIT_ORG_ID=plum
LANGFUSE_INIT_ORG_NAME=Plum
LANGFUSE_INIT_PROJECT_ID=claims
LANGFUSE_INIT_PROJECT_NAME=Claims
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-$(hex 16)
LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-$(hex 16)

NEXTAUTH_SECRET=$(b64 32)
SALT=$(b64 32)
ENCRYPTION_KEY=$(hex 32)
POSTGRES_PASSWORD=$(hex 24)
CLICKHOUSE_PASSWORD=$(hex 24)
REDIS_PASSWORD=$(hex 24)
MINIO_ROOT_PASSWORD=$(hex 24)
EOF
  chmod 600 .env
else
  say "Reusing existing .env (delete it to regenerate secrets — this also orphans existing data)."
fi

# ── 3. Open port 3000 on the host firewall (skipped in Codespaces, which proxies ports) ──
if [ -z "${CODESPACE_NAME:-}" ] && command -v iptables >/dev/null 2>&1 && ! sudo iptables -C INPUT -p tcp --dport 3000 -j ACCEPT 2>/dev/null; then
  say "Opening TCP 3000 in the host firewall…"
  sudo iptables -I INPUT 1 -p tcp --dport 3000 -j ACCEPT || true
  (command -v netfilter-persistent >/dev/null 2>&1 && sudo netfilter-persistent save) || true
fi

# ── 4. Start the stack ─────────────────────────────────────────────────────────
say "Starting Langfuse (first boot runs DB migrations — give it ~1–2 min)…"
$SUDO $DC pull
$SUDO $DC up -d

# ── 5. Print what to share + what to put on the backend ─────────────────────────
set -a; . ./.env; set +a
cat <<EOF

────────────────────────────────────────────────────────────────────────────
✅ Langfuse is starting. Open it in ~1–2 minutes:

   URL:       ${NEXTAUTH_URL}
   Email:     ${LANGFUSE_INIT_USER_EMAIL}
   Password:  ${LANGFUSE_INIT_USER_PASSWORD}

Share the URL + email + password to let someone view the trace dashboard.

Put these on the Render backend (Environment), then redeploy it:
   ENABLE_OBSERVABILITY = true
   LANGFUSE_HOST        = ${NEXTAUTH_URL}
   LANGFUSE_PUBLIC_KEY  = ${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}
   LANGFUSE_SECRET_KEY  = ${LANGFUSE_INIT_PROJECT_SECRET_KEY}

Logs:   $DC logs -f langfuse-web
Stop:   $DC down        (add -v to also wipe data)
────────────────────────────────────────────────────────────────────────────
EOF
