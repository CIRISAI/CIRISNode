import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import AuthProvider from "../components/AuthProvider";
// import { getServerSession } from "next-auth"; // No longer needed here as middleware handles auth
// import { redirect } from "next/navigation"; // No longer needed here
// import { headers } from "next/headers"; // No longer needed here

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "EthicsEngine Admin",
  description: "CIRISBench admin dashboard — evaluation management, model benchmarking, and system monitoring.",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Session check and redirect logic is now handled by middleware.ts
  // const session = await getServerSession();
  // const requestHeaders = await headers(); 
  // const nextUrl = requestHeaders.get("next-url"); 
  // console.log(`RootLayout: Raw next-url header: ${nextUrl}`);
  
  // let pathname = nextUrl || "/";
  // if (pathname !== "/" && pathname.endsWith("/")) {
  //   pathname = pathname.slice(0, -1);
  // }
  // if (!pathname.startsWith("/")) {
  //   pathname = "/" + pathname;
  // }

  // console.log(`RootLayout: Checking session. Normalized Pathname: ${pathname}, Session found: ${!!session}`);
  
  // const isLoginPage = pathname === "/login" || pathname.startsWith("/login/");

  // if (!session && !isLoginPage) {
  //   console.log(`RootLayout: No session and not on login page. Redirecting to /login from ${pathname}`);
  //   redirect("/login");
  // }
  // // console.log("RootLayout rendering, pathname (manual check):", typeof window !== 'undefined' ? window.location.pathname : 'N/A on server');
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
