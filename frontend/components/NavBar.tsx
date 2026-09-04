"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { clearSession, getToken, me, type Role } from "@/lib/api";

const LINKS = [
  { href: "/chat", label: "Chat" },
  { href: "/dashboard", label: "Analytics" },
  { href: "/admin", label: "Admin", roles: ["admin", "superadmin"] as Role[] },
];

/** Top bar plus the client-side auth gate for every page inside (app)/. */
export default function NavBar() {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<{ username: string; role: Role } | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    // A stale or revoked token only shows up on a real call, so verify it.
    me()
      .then(setUser)
      .catch(() => {
        clearSession();
        router.replace("/login");
      });
  }, [router]);

  function logout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur">
      <nav className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-3">
        <div className="flex items-center gap-1">
          <span className="mr-3 text-sm font-bold tracking-tight text-cyan-400">
            Logistics AI
          </span>
          {LINKS.filter(
            (link) => !link.roles || (user && link.roles.includes(user.role)),
          ).map((link) => (
            <Link
              key={link.href}
              href={link.href}
              aria-current={pathname === link.href ? "page" : undefined}
              className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${
                pathname === link.href
                  ? "bg-cyan-500 text-slate-950"
                  : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-3 text-sm">
          {user && (
            <span className="text-slate-400">
              {user.username} · {user.role}
            </span>
          )}
          <button
            type="button"
            onClick={logout}
            className="rounded-lg border border-slate-700 px-3 py-1.5 font-semibold text-slate-200 hover:border-rose-400 hover:text-rose-300"
          >
            Log out
          </button>
        </div>
      </nav>
    </header>
  );
}
