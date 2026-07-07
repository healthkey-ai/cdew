import { Navigate, Outlet } from "react-router-dom";

import { useAuth, useMe } from "@/features/auth/api";

/** Gate a route subtree on being signed in; bounce to /login otherwise. */
export function RequireAuth() {
  const authed = useAuth();
  if (!authed) return <Navigate to="/login" replace />;
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
