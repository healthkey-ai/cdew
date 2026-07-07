import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useLogin } from "./api";

/** Full-page local email/password sign-in. External SSO exchanges its token via
 * PartnerAuthentication; this is the local/dev login. Accounts are provisioned
 * by an admin on the Users page (design §11) — there is no self-serve signup. */
export function LoginPage() {
  const nav = useNavigate();
  const login = useLogin();
  const [email, setEmail] = useState("you@healthtree.org");
  const [password, setPassword] = useState("devpassword123");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    login.mutate({ email, password }, { onSuccess: () => nav("/inbox", { replace: true }) });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 p-4">
      <div className="w-full max-w-sm rounded-xl border border-neutral-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-bold">CDEW</h1>
        <p className="mt-1 text-sm text-neutral-500">Clinical Data Extraction Workflow</p>

        <form onSubmit={submit} className="mt-5 space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-600">Email</label>
            <input
              className="w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@healthtree.org"
              autoComplete="username"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-600">Password</label>
            <input
              className="w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
            />
          </div>
          <button
            type="submit"
            disabled={login.isPending}
            className="w-full rounded bg-neutral-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {login.isPending ? "signing in…" : "Sign in"}
          </button>
          {login.isError && <p className="text-sm text-red-600">Invalid email or password.</p>}
        </form>

        <p className="mt-4 border-t border-neutral-100 pt-3 text-xs text-neutral-500">
          No account? Accounts are created by an administrator on the Users screen — CDEW has no public
          sign-up. Dev: run{" "}
          <code className="break-all">
            python manage.py bootstrap_dev --email you@healthtree.org --roles admin,reviewer,prompt_author
          </code>
          .
        </p>
      </div>
    </div>
  );
}
