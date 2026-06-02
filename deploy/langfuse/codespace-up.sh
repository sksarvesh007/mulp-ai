#!/usr/bin/env bash
# Bring up self-hosted Langfuse inside a GitHub Codespace and make it shareable.
#
#   chmod +x codespace-up.sh && ./codespace-up.sh
#
# A Codespace already has Docker + the gh CLI (pre-authenticated). This computes the
# Codespace's forwarded URL for port 3000, stands up the stack with that as NEXTAUTH_URL,
# and flips the port to PUBLIC so anyone with the link can open the login page.
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "${CODESPACE_NAME:-}" ]; then
  echo "Not in a GitHub Codespace. Use ./setup.sh on a VM instead." >&2
  exit 1
fi

DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
export LF_PUBLIC_URL="https://${CODESPACE_NAME}-3000.${DOMAIN}"

# Reuse the shared installer (it skips the VM firewall step inside a Codespace).
./setup.sh

# Make port 3000 reachable WITHOUT a GitHub login, so the URL is shareable.
printf '\n\033[1;36m==>\033[0m Making port 3000 public…\n'
if gh codespace ports visibility 3000:public -c "$CODESPACE_NAME" 2>/dev/null; then
  echo "Port 3000 is now PUBLIC."
else
  echo "Couldn't set it via gh. Do it once in the PORTS tab: right-click port 3000 →"
  echo "Port Visibility → Public."
fi
