"use client";

import { useState } from "react";

export function MobileNav() {
  const [open, setOpen] = useState(false);

  return (
    <div className="sm:hidden">
      <button
        onClick={() => setOpen(!open)}
        className="p-2 rounded-md hover:bg-[var(--muted)]"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          {open ? (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          )}
        </svg>
      </button>

      {open && (
        <div className="absolute top-14 left-0 right-0 bg-[var(--card)] border-b border-[var(--border)] shadow-lg z-50">
          <div className="flex flex-col p-2">
            {[
              { href: "/", label: "Dashboard" },
              { href: "/creators", label: "Creators" },
              { href: "/chat", label: "Chat" },
              { href: "/compare", label: "Compare" },
            ].map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="px-4 py-3 rounded-md text-sm font-medium hover:bg-[var(--muted)] transition-colors"
              >
                {link.label}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
