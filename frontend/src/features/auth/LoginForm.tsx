import { useState } from "react";

import { useLogin } from "./api";

/** Local email/password sign-in. Create a user with `manage.py bootstrap_dev`. */
export function LoginForm() {
  const [email, setEmail] = useState("you@healthtree.org");
  const [password, setPassword] = useState("devpassword123");
  const login = useLogin();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    login.mutate({ email, password });
  };

  return (
    <section className="mt-6 max-w-sm rounded-lg border border-neutral-200 p-4">
      <h2 className="font-semibold">Sign in</h2>
      <form onSubmit={submit} className="mt-3 space-y-2">
        <input
          className="w-full rounded border border-neutral-300 px-2 py-1 text-sm"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="email"
          autoComplete="username"
        />
        <input
          className="w-full rounded border border-neutral-300 px-2 py-1 text-sm"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password"
          autoComplete="current-password"
        />
        <button
          type="submit"
          disabled={login.isPending}
          className="rounded bg-neutral-900 px-3 py-1 text-sm text-white disabled:opacity-50"
        >
          {login.isPending ? "signing in…" : "Sign in"}
        </button>
        {login.isError && <p className="text-sm text-red-600">Invalid email or password.</p>}
      </form>
      <p className="mt-3 text-xs text-neutral-500">
        Dev: run <code>python manage.py bootstrap_dev --email you@healthtree.org --roles admin,reviewer,prompt_author</code>{" "}
        then sign in with <code>devpassword123</code>.
      </p>
    </section>
  );
}
