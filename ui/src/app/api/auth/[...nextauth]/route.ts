import NextAuth from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import DiscordProvider from "next-auth/providers/discord";

console.log("NODE_ENV in NextAuth route:", process.env.NODE_ENV);

const handler = NextAuth({
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
    DiscordProvider({
      clientId: process.env.DISCORD_CLIENT_ID!,
      clientSecret: process.env.DISCORD_CLIENT_SECRET!,
    }),
  ],
  session: {
    strategy: "jwt",
  },
  callbacks: {
    async signIn({ user, account, profile }) {
      console.log("NextAuth signIn callback:", { user, account, profile });
      // Ensure you return true to continue the sign-in process
      // You can add custom logic here, e.g., to block certain users
      return true;
    },
    async jwt({ token, user, account, profile }) {
      console.log("NextAuth JWT callback:", { token, user, account, profile });
      if (account && user) {
        // Persist the OAuth access_token and or the user id to the token right after signin
        token.accessToken = account.access_token;
        token.id = user.id; // Or profile.id depending on provider
      }
      return token;
    },
    async session({ session, token, user }) {
      console.log("NextAuth session callback:", { session, token, user });
      // Send properties to the client, like an access_token and user id from a provider.
      // The type for session.user needs to be augmented if you add custom properties
      // session.accessToken = token.accessToken;
      // session.user.id = token.id;
      return session;
    },
  },
  // Enable debug messages in the console if you are having problems
  // Force debug mode for now to get more logs
  debug: true, 
});

export { handler as GET, handler as POST };
