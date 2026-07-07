import { useState } from "react";

import { type AxiosError } from "axios";

import { ROLES, useCreateUser, useSetRoles, useUsers } from "./api";

const EMPTY = { email: "", name: "", password: "", roles: [] as string[] };

/** Admin-gated user provisioning (design §11) — the create-user / "signup"
 * surface. Create local accounts and edit their role grants. */
export function UsersPage() {
  const users = useUsers();
  const createUser = useCreateUser();
  const setRoles = useSetRoles();

  const [form, setForm] = useState(EMPTY);
  const [err, setErr] = useState<string | null>(null);

  const toggleFormRole = (role: string) =>
    setForm((f) => ({
      ...f,
      roles: f.roles.includes(role) ? f.roles.filter((r) => r !== role) : [...f.roles, role],
    }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    createUser.mutate(form, {
      onSuccess: () => setForm(EMPTY),
      onError: (e2) => {
        const data = (e2 as AxiosError<Record<string, string[] | string>>).response?.data;
        const first = data && Object.values(data)[0];
        setErr(Array.isArray(first) ? first[0] : (first as string) || "Could not create user.");
      },
    });
  };

  return (
    <section>
      <h1 className="text-lg font-semibold">Users</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Provision internal CDM accounts and manage their roles. There is no public sign-up.
      </p>

      {/* create */}
      <form onSubmit={submit} className="mt-4 rounded-lg border border-neutral-200 p-4">
        <h2 className="text-sm font-medium">Create user</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <input
            className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            placeholder="email"
            type="email"
            required
          />
          <input
            className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="name (optional)"
          />
          <input
            className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            placeholder="temporary password (min 8)"
            type="password"
            autoComplete="new-password"
            required
          />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span className="text-xs text-neutral-500">roles:</span>
          {ROLES.map((role) => (
            <label key={role} className="flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                checked={form.roles.includes(role)}
                onChange={() => toggleFormRole(role)}
              />
              {role}
            </label>
          ))}
          <button
            type="submit"
            disabled={createUser.isPending}
            className="ml-auto rounded bg-neutral-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {createUser.isPending ? "creating…" : "Create user"}
          </button>
        </div>
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      </form>

      {/* list */}
      <table className="mt-6 w-full text-left text-sm">
        <thead className="text-neutral-500">
          <tr>
            <th className="py-1">email</th>
            <th>name</th>
            <th>roles</th>
          </tr>
        </thead>
        <tbody>
          {users.data?.map((u) => (
            <tr key={u.id} className="border-t border-neutral-100 align-top">
              <td className="py-2">
                {u.email}
                {!u.is_active && <span className="ml-1 text-xs text-red-500">(inactive)</span>}
              </td>
              <td className="py-2 text-neutral-600">{u.name || "—"}</td>
              <td className="py-2">
                <div className="flex flex-wrap gap-3">
                  {ROLES.map((role) => (
                    <label key={role} className="flex items-center gap-1 text-xs">
                      <input
                        type="checkbox"
                        checked={u.roles.includes(role)}
                        disabled={setRoles.isPending}
                        onChange={(e) => {
                          const roles = e.target.checked
                            ? [...u.roles, role]
                            : u.roles.filter((r) => r !== role);
                          setRoles.mutate({ id: u.id, roles });
                        }}
                      />
                      {role}
                    </label>
                  ))}
                </div>
              </td>
            </tr>
          ))}
          {users.data && users.data.length === 0 && (
            <tr>
              <td colSpan={3} className="py-2 text-neutral-500">
                no users yet
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
