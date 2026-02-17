import type { Metadata } from "next";
import "./globals.css";
import { MobileNav } from "./mobile-nav";

export const metadata: Metadata = {
  title: "Content Analyzer",
  description: "Creator-centric content analysis across platforms",
};

function NavLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      className="px-3 py-2 rounded-md text-sm font-medium hover:bg-[var(--muted)] transition-colors"
    >
      {children}
    </a>
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />
      </head>
      <body className="min-h-screen">
        <nav className="border-b border-[var(--border)] bg-[var(--card)] sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-14">
              <a
                href="/"
                className="text-lg font-bold text-[var(--primary)] mr-6"
              >
                Content Analyzer
              </a>
              {/* Desktop nav */}
              <div className="hidden sm:flex items-center gap-1">
                <NavLink href="/">Dashboard</NavLink>
                <NavLink href="/creators">Creators</NavLink>
                <NavLink href="/chat">Chat</NavLink>
                <NavLink href="/compare">Compare</NavLink>
              </div>
              {/* Mobile nav */}
              <MobileNav />
            </div>
          </div>
        </nav>
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 sm:py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
