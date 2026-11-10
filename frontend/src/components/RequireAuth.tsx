import { Navigate, Outlet } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useAuth, useMe } from "@/features/auth/api";
import { authStore } from "@/lib/auth";
import { queryClient } from "@/lib/queryClient";

/** Gate a route subtree on being signed in; bounce to /login otherwise. */
export function RequireAuth() {
  const authed = useAuth();
  if (!authed) return <Navigate to="/login" replace />;
  return <Outlet />;
}

/** Gate the app on holding ANY CDEW role — mirrors the backend HasAnyRole
 * default. A first sign-in through promop, phr or Firebase creates an account
 * with no roles; until an admin grants one, it sees this screen, not the app. */
export function RequireAnyRole() {
  const me = useMe();
  if (me.isPending) return <p className="p-8 text-sm text-neutral-500">loading…</p>;
  if (me.data && me.data.roles.length === 0) {
    const signOut = () => {
      authStore.clear();
      queryClient.clear();
    };
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
        <div className="max-w-sm space-y-3 text-sm">
          <h1 className="text-lg font-semibold">Awaiting access</h1>
          <p className="text-muted-foreground">
            You’re signed in as <span className="font-medium text-foreground">{me.data.email || "this account"}</span>,
            but it has no CDEW role yet. Ask a CDEW administrator to grant you one on the Users screen.
          </p>
          <Button variant="outline" onClick={signOut}>
            Sign out
          </Button>
        </div>
      </div>
    );
  }
  return <Outlet />;
}

/** Gate a route subtree on holding at least one of the given roles (admin
 * always passes — mirrors the backend HasRole gate). */
export function RequireRole({ anyOf }: { anyOf: string[] }) {
  const me = useMe();
  if (me.isPending) return <p className="p-8 text-sm text-neutral-500">loading…</p>;
  const roles = me.data?.roles ?? [];
  const ok = roles.includes("admin") || anyOf.some((r) => roles.includes(r));
  if (!ok) {
    return (
      <div className="p-8 text-sm text-red-600">
        You don’t have access to this page. Ask an admin for the required role.
      </div>
    );
  }
  return <Outlet />;
}
