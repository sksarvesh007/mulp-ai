import { type NextRequest, NextResponse } from "next/server";

// Gate the app behind a session - an optimistic cookie check (Edge-safe, no DB); the
// real session is validated server-side by better-auth on each request.
//
// We check the cookie name directly (instead of better-auth's getSessionCookie) because
// behind a TLS-terminating proxy (Render/Cloudflare) the internal request looks like plain
// HTTP, so getSessionCookie misses the `__Secure-`-prefixed cookie that the browser sends.
const SESSION_COOKIES = ["__Secure-better-auth.session_token", "better-auth.session_token"];

export function middleware(request: NextRequest): NextResponse {
  const hasSession = SESSION_COOKIES.some((name) => request.cookies.get(name));
  if (!hasSession) {
    const url = new URL("/login", request.url);
    url.searchParams.set("from", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Protect everything except the login page, the auth endpoints, the backend API proxy,
  // and static assets - including the public ``/samples`` gallery (manifest + document
  // images) the upload tab fetches, which must load without a session (otherwise the auth
  // redirect returns HTML in place of the PNGs and the previews break).
  matcher: ["/((?!login|auth|api|_next/static|_next/image|favicon.ico|samples).*)"],
};
