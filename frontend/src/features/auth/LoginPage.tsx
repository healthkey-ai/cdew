import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-lg">CDEW</CardTitle>
          <CardDescription>Clinical Data Extraction Workflow</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={submit} className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                className="h-9"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@healthtree.org"
                autoComplete="username"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                className="h-9"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </div>
            <Button type="submit" size="lg" className="w-full" disabled={login.isPending}>
              {login.isPending && <Loader2 className="animate-spin" />}
              {login.isPending ? "Signing in…" : "Sign in"}
            </Button>
            {login.isError && <p className="text-sm text-destructive">Invalid email or password.</p>}
          </form>

          <p className="border-t pt-3 text-xs text-muted-foreground">
            No account? Accounts are created by an administrator on the Users screen — CDEW has no
            public sign-up. Dev:{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
              manage.py bootstrap_dev --email you@healthtree.org --roles admin,reviewer,prompt_author
            </code>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
