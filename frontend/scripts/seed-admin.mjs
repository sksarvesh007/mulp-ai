// Seeds the demo admin into auth.db at build time (after the schema migration), so the
// deployed image always has a working login. Uses a sign-up-enabled instance because the
// runtime auth disables open sign-up; same DB file + same schema, so the row is shared.
import Database from "better-sqlite3";
import { betterAuth } from "better-auth";

const auth = betterAuth({
  database: new Database(process.env.AUTH_DB_PATH ?? "auth.db"),
  basePath: "/auth",
  emailAndPassword: { enabled: true },
  secret: process.env.BETTER_AUTH_SECRET ?? "build-time-seed-secret",
});

try {
  await auth.api.signUpEmail({
    body: { email: "admin@mulp.local", password: "mulpadmin123", name: "Admin" },
  });
  console.log("seed-admin: created admin@mulp.local");
} catch (e) {
  // already exists (idempotent re-runs) → fine; anything else, surface it
  const msg = String(e);
  if (/exist/i.test(msg)) console.log("seed-admin: admin already present");
  else throw e;
}
