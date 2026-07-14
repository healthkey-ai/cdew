import { NavLink, Outlet } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { LogOut, Moon, Sun } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useHealth, useMe } from "@/features/auth/api";
import { authStore } from "@/lib/auth";
import { cn } from "@/lib/utils";

const navCls = ({ isActive }: { isActive: boolean }) =>
  cn(
    buttonVariants({ variant: isActive ? "secondary" : "ghost", size: "sm" }),
    !isActive && "text-muted-foreground",
  );

/** Authed app shell: sticky top nav (role-gated) + dark-mode toggle + routed page. */
export function AppLayout() {
  const me = useMe();
  const health = useHealth();
  const qc = useQueryClient();
  const { resolvedTheme, setTheme } = useTheme();

  const roles = me.data?.roles ?? [];
  const canAuthor = roles.includes("prompt_author") || roles.includes("admin");
  const isAdmin = roles.includes("admin");

  const signOut = () => {
    authStore.clear();
    qc.clear();
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-2.5">
          <div className="flex items-center gap-5">
            <div className="flex items-center gap-2">
              <span className="text-base font-bold tracking-tight">CDEW</span>
              <span
                title={health.isError ? "API unreachable" : health.isPending ? "checking API…" : "API ok"}
                className={cn(
                  "size-2 rounded-full",
                  health.isError ? "bg-destructive" : health.isPending ? "bg-muted-foreground/40" : "bg-success",
                )}
              />
            </div>
            <nav className="flex items-center gap-1">
              <NavLink to="/inbox" className={navCls}>
                Inbox
              </NavLink>
              <NavLink to="/review" className={navCls}>
                Review
              </NavLink>
              <NavLink to="/processed" className={navCls}>
                Processed
              </NavLink>
              <Separator orientation="vertical" className="mx-1 h-5" />
              <NavLink to="/workflow" className={navCls}>
                Workflow
              </NavLink>
              {(canAuthor || isAdmin) && <Separator orientation="vertical" className="mx-1 h-5" />}
              {canAuthor && (
                <NavLink to="/taxonomies" className={navCls}>
                  Taxonomies
                </NavLink>
              )}
              {canAuthor && (
                <NavLink to="/extractors" className={navCls}>
                  Extractors
                </NavLink>
              )}
              {isAdmin && (
                <NavLink to="/users" className={navCls}>
                  Users
                </NavLink>
              )}
            </nav>
          </div>

          <div className="flex items-center gap-2">
            <div className="hidden text-right sm:block">
              <div className="text-xs font-medium leading-tight">{me.data?.email}</div>
              <div className="text-[11px] leading-tight text-muted-foreground">
                {roles.join(", ") || "no roles"}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Toggle theme"
              onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
            >
              <Sun className="hidden dark:block" />
              <Moon className="block dark:hidden" />
            </Button>
            <Button variant="ghost" size="icon" aria-label="Sign out" onClick={signOut}>
              <LogOut />
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
