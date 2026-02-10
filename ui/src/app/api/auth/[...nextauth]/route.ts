import NextAuth from "next-auth";
import GoogleProvider from "next-auth/providers/google";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://node.ciris.ai";

const handler = NextAuth({
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
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
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.role = (token.role as string) || "anonymous";
      }
      return session;
    },
  },
  debug: process.env.NODE_ENV === "development",
});

export { handler as GET, handler as POST };
