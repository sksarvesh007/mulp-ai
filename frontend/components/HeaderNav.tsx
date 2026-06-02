"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { signOut, useSession } from "@/lib/auth-client";
import { Devlog } from "@/components/Devlog";

const linkClass =
  "pressable rounded-md px-3 py-1.5 text-ink-muted hover:bg-surface-2 hover:text-ink";

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
      {session?.user && (
        <>
          <span className="ml-1 hidden text-xs text-ink-faint sm:inline">{session.user.email}</span>
          <button onClick={onSignOut} className={`${linkClass} border border-border`}>
            Sign out
          </button>
        </>
      )}
    </nav>
  );
}
