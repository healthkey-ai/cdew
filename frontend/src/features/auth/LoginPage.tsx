import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { isAxiosError } from "axios";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthConfig, useFirebaseLogin, useLogin, usePartnerLogin } from "./api";

const LOCAL = "local";

/** The server's safe message (it never echoes credentials), else a fallback. */
function errorText(err: unknown, fallback: string) {
  if (isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

/** Full-page staff sign-in (design §11, #31). Staff sign in with a promop or phr
 * account, an org's Firebase (Google), or a CDEW-local account; every option
 * ends in a CDEW token pair. New partner sign-ins arrive with no roles — an
 * admin grants them on the Users page. There is no self-service sign-up. */
export function LoginPage() {
  const nav = useNavigate();
  const config = useAuthConfig();
  const local = useLogin();
  const partner = usePartnerLogin();
  const firebase = useFirebaseLogin();

  const hosts = config.data?.providers ?? [];
  const [chosen, setChosen] = useState<string | null>(null);
  const method = chosen ?? hosts[0]?.key ?? LOCAL;
  const [email, setEmail] = useState(import.meta.env.DEV ? "you@healthtree.org" : "");
  const [password, setPassword] = useState(import.meta.env.DEV ? "devpassword123" : "");

  const done = () => nav("/inbox", { replace: true });
  const active = method === LOCAL ? local : partner;
  const busy = local.isPending || partner.isPending || firebase.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (method === LOCAL) local.mutate({ email, password }, { onSuccess: done });
    else partner.mutate({ provider: method, email, password }, { onSuccess: done });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-lg">CDEW</CardTitle>
          <CardDescription>Clinical Data Extraction Workflow</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {config.data?.firebase && (
            <>
              <Button
                type="button"
                variant="outline"
                size="lg"
                className="w-full"
                disabled={busy}
                onClick={() => firebase.mutate(config.data!.firebase!, { onSuccess: done })}
              >
                {firebase.isPending && <Loader2 className="animate-spin" />}
                Continue with Google
              </Button>
              {firebase.isError && (
                <p className="text-sm text-destructive">{errorText(firebase.error, "Google sign-in failed.")}</p>
              )}
              <Separator />
            </>
          )}

          {hosts.length > 0 && (
            <Tabs value={method} onValueChange={(v) => setChosen(String(v))}>
              <TabsList className="w-full">
                {hosts.map((h) => (
                  <TabsTrigger key={h.key} value={h.key}>
                    {h.label}
                  </TabsTrigger>
                ))}
                <TabsTrigger value={LOCAL}>CDEW account</TabsTrigger>
              </TabsList>
            </Tabs>
          )}

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
            <Button type="submit" size="lg" className="w-full" disabled={busy}>
              {active.isPending && <Loader2 className="animate-spin" />}
              {active.isPending ? "Signing in…" : "Sign in"}
            </Button>
            {active.isError && (
              <p className="text-sm text-destructive">{errorText(active.error, "Invalid email or password.")}</p>
            )}
          </form>

          <p className="border-t pt-3 text-xs text-muted-foreground">
            Staff sign in with their HealthKey account. A first sign-in has no access until an
            administrator grants a role on the Users screen — CDEW has no public sign-up. Dev:{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
              manage.py bootstrap_dev --email you@healthtree.org --roles admin,reviewer,prompt_author
            </code>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
