import { auth } from "@/auth";
import { NextResponse } from "next/server";

// Customer-facing routes are intentionally public — the QR table token is
// the only access control for ordering. No auth gate for these prefixes.
const GUEST_PREFIXES = ["/t/", "/menu", "/cart", "/order/"];

const PROTECTED_PREFIXES: string[] = [];

export default auth((req) => {
  const { pathname } = req.nextUrl;

  if (GUEST_PREFIXES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const isProtected = PROTECTED_PREFIXES.some((p) => pathname.startsWith(p));
  if (isProtected && !req.auth) {
    const loginUrl = new URL("/login", req.url);
    loginUrl.searchParams.set("callbackUrl", req.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
