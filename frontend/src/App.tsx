import { useQueryClient } from "@tanstack/react-query";

import { useAuth, useHealth, useMe } from "@/features/auth/api";
import { LoginForm } from "@/features/auth/LoginForm";
import { DocumentsPanel } from "@/features/documents/DocumentsPanel";
import { PromptsPanel } from "@/features/prompts/PromptsPanel";
import { authStore } from "@/lib/auth";

export default function App() {
  const authed = useAuth();
  const health = useHealth();
  const me = useMe(authed);
  const qc = useQueryClient();

  const signOut = () => {
    authStore.clear();
    qc.clear();
  };

  const canAuthor = me.data?.roles.includes("prompt_author") || me.data?.roles.includes("admin");

  return (
    <main className="mx-auto max-w-4xl p-8 font-sans">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Validation Workflow</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Admin tooling — clinical data extraction &amp; validation
          </p>
        </div>
        {authed && (
          <div className="text-right text-sm">
            <div>{me.data?.email}</div>
            <div className="text-xs text-neutral-500">{me.data?.roles.join(", ") || "no roles"}</div>
            <button className="mt-1 text-xs text-blue-600 hover:underline" onClick={signOut}>
              sign out
            </button>
          </div>
        )}
      </header>

      <section className="mt-6 rounded-lg border border-neutral-200 p-3 text-sm">
        <span className="font-medium">API</span>{" "}
        {health.isPending ? (
          <span className="text-neutral-500">checking…</span>
        ) : health.isError ? (
          <span className="text-red-600">
            unreachable — is the backend running on :8000? (<code>cd backend &amp;&amp; python manage.py runserver</code>)
          </span>
        ) : (
          <span className="text-green-600">ok</span>
        )}
      </section>

      {!authed ? (
        <LoginForm />
      ) : (
        <>
          <DocumentsPanel />
          {canAuthor && <PromptsPanel />}
        </>
      )}
    </main>
  );
}
