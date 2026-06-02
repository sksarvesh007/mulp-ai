import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  output: "standalone",
  // Externalize ONLY the DB-adapter deps: better-sqlite3 is native, and the kysely adapter
  // ships dialects (node:sqlite, etc.) the bundler can't parse. NOTE: do not externalize
  // `better-auth` itself - that breaks `better-auth/react`'s hooks during SSR (null React).
  serverExternalPackages: ["better-sqlite3", "@better-auth/kysely-adapter", "kysely"],
  // Allow a temporary public tunnel host to reach the dev server (HMR/assets).
  allowedDevOrigins: ["*.trycloudflare.com", "*.ngrok-free.app", "*.ngrok.app", "*.ngrok.io"],
  // NOTE: `/api/*` is proxied to the backend by app/api/[...path]/route.ts (a RUNTIME proxy),
  // not a build-time rewrite - so BACKEND_ORIGIN can be resolved after deploy without a rebuild.
};

export default nextConfig;
