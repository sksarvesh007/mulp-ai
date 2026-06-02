#!/usr/bin/env bash
# Expose the Codespace's Langfuse through a REAL public URL.
#
# Why: GitHub's forwarded *.app.github.dev URL requires GitHub's auth handshake even when
# "public", so a browser can view it but the backend CANNOT POST traces to it (they get
# walled → no traces). A free Cloudflare quick-tunnel gives a genuine public HTTPS endpoint
# (no account, no card) that accepts both viewing AND ingestion.
#
# Run AFTER ./codespace-up.sh:   chmod +x codespace-tunnel.sh && ./codespace-tunnel.sh
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { echo "Run ./codespace-up.sh first (no .env found)." >&2; exit 1; }
say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }

# 1. cloudflared
if ! command -v cloudflared >/dev/null 2>&1; then
  say "Installing cloudflared…"
  ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
  curl -fsSL -o /tmp/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}"
  sudo install /tmp/cloudflared /usr/local/bin/cloudflared && rm -f /tmp/cloudflared
fi

# 2. start a quick tunnel to the local Langfuse and capture its public URL
say "Starting Cloudflare tunnel to http://localhost:3000 …"
pkill -f "cloudflared tunnel" 2>/dev/null || true
: > /tmp/cf.log
nohup cloudflared tunnel --no-autoupdate --url http://localhost:3000 >/tmp/cf.log 2>&1 &
URL=""
for _ in $(seq 1 30); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf.log | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 2
done
[ -z "$URL" ] && { echo "Tunnel URL not found — see /tmp/cf.log:" >&2; tail -n 20 /tmp/cf.log >&2; exit 1; }

# 3. make the tunnel URL Langfuse's canonical URL (so login works there) + restart web
say "Pointing Langfuse at ${URL} and restarting…"
sed -i "s#^NEXTAUTH_URL=.*#NEXTAUTH_URL=${URL}#" .env
DC="docker compose"; docker compose version >/dev/null 2>&1 || DC="docker-compose"
$DC up -d langfuse-web

# 4. print what to share + what to set on the backend
set -a; . ./.env; set +a
cat <<EOF

────────────────────────────────────────────────────────────────────────────
✅ Public tunnel ready — works for BOTH dashboard viewing AND backend ingestion:

   URL:       ${URL}
   Email:     ${LANGFUSE_INIT_USER_EMAIL}
   Password:  ${LANGFUSE_INIT_USER_PASSWORD}

Set on the Render backend (Environment) → redeploy:
   ENABLE_OBSERVABILITY = true
   LANGFUSE_HOST        = ${URL}
   LANGFUSE_PUBLIC_KEY  = ${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}
   LANGFUSE_SECRET_KEY  = ${LANGFUSE_INIT_PROJECT_SECRET_KEY}

Keep this Codespace + the tunnel running. Tunnel log: tail -f /tmp/cf.log
NOTE: a quick-tunnel URL changes each run — re-run this script after a restart
and update LANGFUSE_HOST on the backend to the new URL.
────────────────────────────────────────────────────────────────────────────
EOF
