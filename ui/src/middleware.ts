import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { getToken } from 'next-auth/jwt'

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  console.log(`Middleware: Processing request for ${pathname}`);

  // Allow requests for NextAuth.js API routes, static files, and image optimization to pass through
  // This check should be very early.
  if (
    pathname.startsWith('/api/auth/') ||
    pathname.startsWith('/_next/') || // Broader rule for all _next assets
    pathname.endsWith('.ico') || 
    pathname.endsWith('.png') || 
    pathname.endsWith('.jpg') ||
    pathname.endsWith('.svg')
  ) {
    console.log(`Middleware: Allowing asset or NextAuth API route: ${pathname}`);
    return NextResponse.next();
  }

  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) {
    console.error("Middleware: NEXTAUTH_SECRET is not set!");
    // Potentially redirect to an error page or allow access if in dev and unconfigured
    return NextResponse.next(); 
  }

  const token = await getToken({ req, secret, raw: true });

  console.log(`Middleware: Pathname: ${pathname}, Token found: ${!!token}`);

  // If user is not authenticated and not on the login page, redirect to login
  if (!token && pathname !== '/login') {
    const loginUrl = new URL('/login', req.url);
    console.log(`Middleware: No token and not on /login. Redirecting to ${loginUrl.toString()}`);
    return NextResponse.redirect(loginUrl);
  }

  // If user is authenticated and tries to access login page, redirect to home
  if (token && pathname === '/login') {
    const homeUrl = new URL('/', req.url);
    console.log(`Middleware: Token found and on /login. Redirecting to ${homeUrl.toString()}`);
    return NextResponse.redirect(homeUrl);
  }

  return NextResponse.next();
}

// See "Matching Paths" below to learn more
export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes) - this is too broad, handled above
     * - _next/static (static files) - handled above
     * - _next/image (image optimization files) - handled above
     * - favicon.ico (favicon file) - handled above
     * So, we match everything else that is a page.
     */
    '/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
