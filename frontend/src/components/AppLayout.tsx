import { NavLink, Outlet } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { useHealth, useMe } from "@/features/auth/api";
import { authStore } from "@/lib/auth";
import { cn } from "@/lib/utils";

const navLink = ({ isActive }: { isActive: boolean }) =>
  cn(
    "rounded px-3 py-1.5 text-sm transition-colors",
    isActive ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100",
  );

/** Authed app shell: top nav (role-gated) + the routed page below. */
export function AppLayout() {
  const me = useMe();
  const health = useHealth();
  const qc = useQueryClient();

  const roles = me.data?.roles ?? [];
  const canAuthor = roles.includes("prompt_author") || roles.includes("admin");
  const isAdmin = roles.includes("admin");

  const signOut = () => {
    authStore.clear();
    qc.clear();
  };

  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-neutral-200">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold">CDEW</span>
              <span
                title={health.isError ? "API unreachable" : "API ok"}
                className={cn(
                  "inline-block h-2 w-2 rounded-full",
                  health.isError ? "bg-red-500" : health.isPending ? "bg-neutral-300" : "bg-green-500",
                )}
              />
            </div>
            <nav className="flex items-center gap-1">
              <NavLink to="/inbox" className={navLink}>
                Inbox
              </NavLink>
              {canAuthor && (
                <NavLink to="/taxonomies" className={navLink}>
                  Taxonomies
                </NavLink>
              )}
              {canAuthor && (
                <NavLink to="/extractors" className={navLink}>
                  Extractors
                </NavLink>
              )}
              {isAdmin && (
                <NavLink to="/users" className={navLink}>
                  Users
                </NavLink>
              )}
            </nav>
          </div>

          <div className="flex items-center gap-3 text-right text-sm">
            <div>
              <div className="text-neutral-800">{me.data?.email}</div>
              <div className="text-xs text-neutral-500">{roles.join(", ") || "no roles"}</div>
            </div>
            <button className="text-xs text-blue-600 hover:underline" onClick={signOut}>
              sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
