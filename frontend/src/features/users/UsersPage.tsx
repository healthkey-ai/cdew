import { useState } from "react";
import { type AxiosError } from "axios";
import { toast } from "sonner";
import { Loader2, UserPlus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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
      onSuccess: () => {
        setForm(EMPTY);
        toast.success("User created");
      },
      onError: (e2) => {
        const data = (e2 as AxiosError<Record<string, string[] | string>>).response?.data;
        const first = data && Object.values(data)[0];
        const msg = Array.isArray(first) ? first[0] : (first as string) || "Could not create user.";
        setErr(msg);
        toast.error(msg);
      },
    });
  };

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Users</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Provision internal CDM accounts and manage their roles. There is no public sign-up.
        </p>
      </div>

      {/* create */}
      <Card>
        <CardHeader>
          <CardTitle>Create user</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  className="h-9"
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  placeholder="user@healthtree.org"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  className="h-9"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="optional"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="pw">Temporary password</Label>
                <Input
                  id="pw"
                  className="h-9"
                  type="password"
                  required
                  autoComplete="new-password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  placeholder="min 8 characters"
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <span className="text-sm text-muted-foreground">Roles</span>
              {ROLES.map((role) => (
                <Label key={role} className="font-normal">
                  <Checkbox checked={form.roles.includes(role)} onCheckedChange={() => toggleFormRole(role)} />
                  {role}
                </Label>
              ))}
              <Button type="submit" className="ml-auto" disabled={createUser.isPending}>
                {createUser.isPending ? <Loader2 className="animate-spin" /> : <UserPlus />}
                Create user
              </Button>
            </div>
            {err && <p className="text-sm text-destructive">{err}</p>}
          </form>
        </CardContent>
      </Card>

      {/* list */}
      <Card>
        <CardHeader>
          <CardTitle>Team</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Roles</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data?.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">
                    {u.email}
                    {!u.is_active && (
                      <Badge variant="destructive" className="ml-2">
                        inactive
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{u.name || "—"}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-4">
                      {ROLES.map((role) => (
                        <Label key={role} className="text-xs font-normal">
                          <Checkbox
                            checked={u.roles.includes(role)}
                            disabled={setRoles.isPending}
                            onCheckedChange={(checked) => {
                              const roles = checked
                                ? [...u.roles, role]
                                : u.roles.filter((r) => r !== role);
                              setRoles.mutate(
                                { id: u.id, roles },
                                { onError: () => toast.error("Could not update roles") },
                              );
                            }}
                          />
                          {role}
                        </Label>
                      ))}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {users.data && users.data.length === 0 && (
                <TableRow>
                  <TableCell colSpan={3} className="py-8 text-center text-muted-foreground">
                    No users yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  );
}
