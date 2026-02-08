import NextAuth from "next-auth";
import GoogleProvider from "next-auth/providers/google";

// Allowed email domain for admin access
const ALLOWED_DOMAIN = process.env.ALLOWED_EMAIL_DOMAIN || "ciris.ai";

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
      // Restrict sign-in to @ciris.ai emails only
      const email = user.email?.toLowerCase();
      if (!email || !email.endsWith(`@${ALLOWED_DOMAIN}`)) {
        console.warn(`Sign-in denied: ${email ?? "no email"} (requires @${ALLOWED_DOMAIN})`);
        return false;
      }
      return true;
    },
    async jwt({ token, user, account }) {
      if (account && user) {
        token.accessToken = account.access_token;
        token.id = user.id;
      }
      return token;
    },
    async session({ session }) {
      return session;
    },
  },
  debug: process.env.NODE_ENV === "development",
});

export { handler as GET, handler as POST };
