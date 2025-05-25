import { NextResponse } from 'next/server'

export async function middleware() {
  // Authentication/authorization checks are disabled for demo/design preview.
  // All pages are visible to anonymous users.
  return NextResponse.next();
}

export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
