"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { signIn } from "@/lib/auth-client";
import { Card } from "@/components/primitives";

// Demo admin - the "Prefill admin" button drops these into the form.
const ADMIN_EMAIL = "admin@mulp.local";
const ADMIN_PASSWORD = "mulpadmin123";

export default function LoginPage() {
  // useSearchParams must be inside a Suspense boundary for static prerendering.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const params = useSearchParams();
  const next = params.get("from") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const prefill = () => {
    setEmail(ADMIN_EMAIL);
    setPassword(ADMIN_PASSWORD);
    setError("");
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const { error } = await signIn.email({ email, password });
    if (error) {
      setError(error.message || "Sign-in failed.");
      setBusy(false);
      return;
    }
    // Hard navigation (not router.push): a client-side nav can fire before the freshly
    // set session cookie is attached to the RSC request, bouncing back to /login.
    window.location.href = next;
  };

  const input =
    "w-full rounded-md border border-border bg-bg/60 px-3 py-2 text-sm text-ink outline-none transition focus:border-brand/50 placeholder:text-ink-faint";

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-sm items-center">
      <Card className="w-full">
        <div className="space-y-1 border-b border-border px-6 py-5">
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">
            Mulp · Claims Intelligence
          </p>
          <h1 className="font-display text-2xl text-ink">Sign in</h1>
        </div>

        <form onSubmit={submit} className="space-y-4 px-6 py-6">
          <label className="block">
            <span className="mb-1.5 block text-xs text-ink-faint">Email</span>
            <input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin@mulp.local"
              className={input}
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs text-ink-faint">Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className={input}
            />
          </label>

          {error && (
            <p role="alert" aria-live="assertive" className="text-sm text-rejected">
              {error}
            </p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={busy || !email || !password}
              className="pressable flex-1 rounded-md bg-brand py-2.5 text-sm font-medium text-cream hover:bg-brand-hover disabled:opacity-60"
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
            <button
              type="button"
              onClick={prefill}
              title="Fill the admin email and password"
              className="pressable rounded-md border border-border px-3 py-2.5 text-sm text-ink-muted hover:border-border-strong hover:text-ink"
            >
              Prefill admin
            </button>
          </div>

          <p className="text-xs text-ink-faint">
            Click <span className="text-ink-muted">Prefill admin</span> to load the demo credentials,
            then Sign in.
          </p>
        </form>
      </Card>
    </div>
  );
}
