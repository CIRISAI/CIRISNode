import NextAuth from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import { SignJWT } from "jose";
import { getEnv } from "../../../../lib/env";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://node.ciris.ai";

/** Lazily resolve the CIRISNode JWT signing key (secrets may not be in process.env on CF Workers) */
function getCirisNodeKey() {
  const secret = getEnv("JWT_SECRET") || "testsecret";
  return new TextEncoder().encode(secret);
}

const handler = NextAuth({
  providers: [
    GoogleProvider({
      clientId: getEnv("GOOGLE_CLIENT_ID") || process.env.GOOGLE_CLIENT_ID!,
      clientSecret: getEnv("GOOGLE_CLIENT_SECRET") || process.env.GOOGLE_CLIENT_SECRET!,
    }),
  ],
  session: {
    strategy: "jwt",
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  callbacks: {
    async signIn({ user }) {
      const email = user.email?.toLowerCase();
      if (!email) return false;

      // Call CIRISNode check-access endpoint instead of domain check
      try {
        const res = await fetch(
          `${API_URL}/api/v1/auth/check-access?email=${encodeURIComponent(email)}`
        );
        if (!res.ok) {
          console.warn(`check-access failed: ${res.status}`);
          return false;
        }
        const data = await res.json();
        if (!data.allowed) {
          console.warn(`Sign-in denied: ${email} (not authorized)`);
          return false;
        }
        return true;
      } catch (err) {
        console.error("check-access error:", err);
        // Fallback: allow @ciris.ai emails
        return email.endsWith("@ciris.ai");
      }
    },
    async jwt({ token, user, account }) {
      if (account && user) {
        token.accessToken = account.access_token;
        token.id = user.id;

        // Fetch role from check-access
        const email = user.email?.toLowerCase();
        if (email) {
          try {
            const res = await fetch(
              `${API_URL}/api/v1/auth/check-access?email=${encodeURIComponent(email)}`
            );
            if (res.ok) {
              const data = await res.json();
              token.role = data.role;
            }
          } catch {
            // Default to admin for @ciris.ai, anonymous otherwise
            token.role = email.endsWith("@ciris.ai") ? "admin" : "anonymous";
          }

          // Mint a CIRISNode-compatible JWT for API calls
          token.apiToken = await new SignJWT({
            sub: email,
            role: token.role || "anonymous",
          })
            .setProtectedHeader({ alg: "HS256" })
            .setIssuedAt()
            .setExpirationTime("24h")
            .sign(getCirisNodeKey());
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.role = (token.role as string) || "anonymous";
        session.user.apiToken = token.apiToken as string;
      }
      return session;
    },
  },
  debug: process.env.NODE_ENV === "development",
});

export { handler as GET, handler as POST };
