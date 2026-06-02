import Database from "better-sqlite3";
import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";

// Auth lives under /auth (NOT /api/auth) so it never collides with the `/api/*` rewrite
// that proxies to the FastAPI backend. SQLite keeps it self-contained and swappable.
export const auth = betterAuth({
  database: new Database(process.env.AUTH_DB_PATH ?? "auth.db"),
  basePath: "/auth",
  secret: process.env.BETTER_AUTH_SECRET ?? "dev-insecure-secret-please-set-BETTER_AUTH_SECRET",
  // Sign-in only - the admin is pre-seeded; open sign-up is disabled (it's shared publicly).
  emailAndPassword: { enabled: true, disableSignUp: true },
  // Allow localhost and the temporary demo tunnels to complete the auth flow.
  trustedOrigins: [
    "http://localhost:3001",
    "https://*.onrender.com",
    "https://*.ngrok-free.app",
    "https://*.ngrok.app",
    "https://*.ngrok.io",
    "https://*.trycloudflare.com",
  ],
  plugins: [nextCookies()],
});
