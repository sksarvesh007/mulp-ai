"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { signOut, useSession } from "@/lib/auth-client";
import { Devlog } from "@/components/Devlog";

const linkClass =
  "pressable rounded-md px-3 py-1.5 text-ink-muted hover:bg-surface-2 hover:text-ink";

const REPO_URL = "https://github.com/sksarvesh007/mulp-ai";

export function HeaderNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { data: session } = useSession();

  // When already on the home route, a <Link href="/"> won't remount the page, so
  // state would persist. Fire an event the page listens for to reset to a fresh claim.
  const onNewClaim = () => {
    if (pathname === "/") {
      window.dispatchEvent(new CustomEvent("mulp:new-claim"));
    }
  };

  const onSignOut = async () => {
    await signOut();
    router.push("/login");
    router.refresh();
  };

  // The login page has no session and shouldn't show app nav.
  if (pathname === "/login") return null;

  return (
    <nav className="flex items-center gap-1 text-sm">
      <Devlog />
      <Link href="/" onClick={onNewClaim} className={linkClass}>
        New claim
      </Link>
      <Link href="/claims" className={linkClass}>
        Claims
      </Link>
      <Link href="/analytics" className={linkClass}>
        Analytics
      </Link>
      <a
        href={REPO_URL}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="View source on GitHub"
        title="View source on GitHub"
        className="pressable rounded-md p-2 text-ink-muted hover:bg-surface-2 hover:text-ink"
      >
        <svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true">
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.02-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
        </svg>
      </a>
      {session?.user && (
        <button onClick={onSignOut} className={`${linkClass} border border-border`}>
          Sign out
        </button>
      )}
    </nav>
  );
}
