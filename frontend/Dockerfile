# syntax=docker/dockerfile:1
FROM node:22-slim AS deps
WORKDIR /app
# build tools so better-sqlite3 (native) compiles if no prebuilt binary matches
RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# /api is proxied to BACKEND_ORIGIN at runtime (see next.config.ts) - bake the relative base.
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL=/api
RUN npm run build
# Bake the auth schema + the demo admin into auth.db so the deployed login works out of the box.
RUN npx --yes @better-auth/cli@latest migrate -y && node scripts/seed-admin.mjs

FROM node:22-slim AS runner
WORKDIR /app
# HOSTNAME=0.0.0.0 so the standalone server accepts external connections (Render/containers);
# PORT is injected by the platform. AUTH_DB_PATH points at the baked, pre-seeded DB.
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 NEXT_PUBLIC_API_URL=/api AUTH_DB_PATH=/app/auth.db
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/auth.db ./auth.db
EXPOSE 3000
CMD ["node", "server.js"]
