"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, KeyRound, Loader2, Server, ShieldCheck, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Brand } from "@/components/brand";
import { useSession } from "@/components/session-provider";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { api, type LoginBody } from "@/lib/api";
import { ENV_LABEL } from "@/lib/format";

export default function LoginPage() {
  const { status, user, loading, setUser, refreshStatus } = useSession();
  const router = useRouter();
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [windows, setWindows] = useState(false);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [host, setHost] = useState("");
  const [alias, setAlias] = useState("");
  const [environment, setEnvironment] = useState("desarrollo");
  const [trustCert, setTrustCert] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  const firstRun = status ? !status.has_inventory : false;
  const servers = status?.servers ?? [];
  const chosen = selected ?? servers.map((s) => s.id);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const body: LoginBody = windows
      ? { auth: "windows" }
      : { auth: "sql", login: login.trim(), password };
    if (firstRun) Object.assign(body, { host: host.trim(), alias: alias.trim() || undefined, environment, trust_server_certificate: trustCert });
    else body.servers = chosen;
    try {
      const res = await api.login(body);
      setUser(res.user);
      const failed = Object.entries(res.warnings);
      if (failed.length) toast.warning(`Sin acceso en: ${failed.map(([k, v]) => `${k} (${v})`).join(", ")}`);
      else if (res.databases.length)
        toast.success(`Conectado a ${res.servers.filter((s) => s.ok).length} servidor(es)`, {
          description: `Puedes descubrir datos en ${res.databases.length} bases de datos.`,
        });
      await refreshStatus();
      router.replace(firstRun ? "/admin" : "/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-svh lg:grid-cols-[1.1fr_1fr]">
      <aside className="from-primary relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br to-[oklch(0.32_0.12_262)] p-10 text-white lg:flex">
        <div className="flex items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-lg bg-white/15 backdrop-blur">
            <Sparkles className="size-4" />
          </div>
          <span className="text-lg font-semibold tracking-tight">ConverData</span>
        </div>
        <div className="max-w-md space-y-6">
          <h1 className="text-3xl leading-tight font-semibold tracking-tight">
            Pregunta en español dónde está un dato. El agente te dice dónde vive, qué significa y cuánto confiar.
          </h1>
          <ul className="space-y-3 text-sm text-white/85">
            {[
              "Base de datos, tabla, ambiente y servidor de cada candidato",
              "Descripción con su fuente, reglas de negocio, relaciones y responsables",
              "Solo ves lo que tu login de base de datos ya puede leer",
            ].map((t) => (
              <li key={t} className="flex gap-2.5">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-white/70" />
                {t}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-white/60">Los datos de clientes no salen del banco: el catálogo guarda solo metadatos.</p>
        <div className="pointer-events-none absolute -right-24 -bottom-24 size-96 rounded-full bg-white/5" />
        <div className="pointer-events-none absolute -top-16 right-24 size-56 rounded-full bg-white/5" />
      </aside>

      <main className="flex items-center justify-center p-4 sm:p-8">
        <div className="w-full max-w-md space-y-6">
          <div className="lg:hidden">
            <Brand />
          </div>
          {!status ? (
            <Card>
              <CardHeader>
                <Skeleton className="h-6 w-40" />
                <Skeleton className="h-4 w-64" />
              </CardHeader>
              <CardContent className="space-y-3">
                <Skeleton className="h-9 w-full" />
                <Skeleton className="h-9 w-full" />
              </CardContent>
            </Card>
          ) : (
            <Card className="shadow-sm">
              <form onSubmit={submit}>
                <CardHeader className="pb-4">
                  {firstRun && (
                    <Badge variant="secondary" className="mb-2 w-fit gap-1">
                      <Sparkles className="size-3" /> Configuración inicial
                    </Badge>
                  )}
                  <CardTitle className="text-xl">{firstRun ? "Conecta el agente a tu SQL Server" : "Inicia sesión"}</CardTitle>
                  <CardDescription>
                    {firstRun
                      ? "Aún no hay catálogo. Entra con un login que pueda ver la definición de las bases (VIEW ANY DEFINITION) y el agente descubrirá los esquemas."
                      : "Usa tu usuario de base de datos. Verás solo lo que ese login puede leer."}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  {firstRun && (
                    <div className="space-y-4 rounded-lg border bg-muted/40 p-4">
                      <div className="space-y-2">
                        <Label htmlFor="host">Servidor</Label>
                        <div className="relative">
                          <Server className="text-muted-foreground absolute top-2.5 left-3 size-4" />
                          <Input
                            id="host"
                            className="bg-background pl-9"
                            placeholder={status.demo ? "demo-sql" : "sqlprod01.banco.local,1433"}
                            value={host}
                            onChange={(e) => setHost(e.target.value)}
                            required
                          />
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-2">
                          <Label htmlFor="alias">Nombre visible</Label>
                          <Input id="alias" className="bg-background" placeholder="SQL Producción" value={alias} onChange={(e) => setAlias(e.target.value)} />
                        </div>
                        <div className="space-y-2">
                          <Label>Ambiente</Label>
                          <Select value={environment} onValueChange={setEnvironment}>
                            <SelectTrigger className="bg-background w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {Object.entries(ENV_LABEL).map(([k, v]) => (
                                <SelectItem key={k} value={k}>
                                  {v}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <label className="flex items-center justify-between gap-3 text-sm">
                        <span className="text-muted-foreground">Confiar en certificado autofirmado (solo desarrollo)</span>
                        <Switch checked={trustCert} onCheckedChange={setTrustCert} />
                      </label>
                    </div>
                  )}

                  {!firstRun && servers.length > 1 && (
                    <div className="space-y-2">
                      <Label>Servidores</Label>
                      <div className="flex flex-wrap gap-2">
                        {servers.map((s) => {
                          const on = chosen.includes(s.id);
                          return (
                            <button
                              type="button"
                              key={s.id}
                              onClick={() => setSelected(on ? chosen.filter((x) => x !== s.id) : [...chosen, s.id])}
                              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition ${
                                on ? "border-primary bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted"
                              }`}
                            >
                              <Server className="size-3" /> {s.alias}
                              <span className="opacity-60">· {ENV_LABEL[s.environment] ?? s.environment}</span>
                            </button>
                          );
                        })}
                      </div>
                      <p className="text-muted-foreground text-xs">Se usa la misma credencial en los servidores marcados.</p>
                    </div>
                  )}
                  {!firstRun && servers.length === 1 && (
                    <div className="text-muted-foreground flex items-center gap-2 text-sm">
                      <Server className="size-4" /> {servers[0].alias}
                      <Badge variant="outline">{ENV_LABEL[servers[0].environment] ?? servers[0].environment}</Badge>
                    </div>
                  )}

                  {status.windows_auth && (
                    <label className="flex items-center justify-between gap-3 text-sm">
                      <span>Usar autenticación de Windows</span>
                      <Switch checked={windows} onCheckedChange={setWindows} />
                    </label>
                  )}

                  {!windows && (
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <Label htmlFor="login">Usuario de base de datos</Label>
                        <Input id="login" autoComplete="username" value={login} onChange={(e) => setLogin(e.target.value)} required autoFocus={!firstRun} />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="password">Contraseña</Label>
                        <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
                      </div>
                    </div>
                  )}

                  {error && (
                    <Alert variant="destructive">
                      <AlertTitle>No se pudo iniciar sesión</AlertTitle>
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}
                  {status.demo && (
                    <Alert>
                      <KeyRound />
                      <AlertTitle>Modo demo</AlertTitle>
                      <AlertDescription>
                        <p>
                          Servidores simulados con metadatos de prueba (sin datos reales). Usuarios <code>analista</code> (consulta, sin
                          RRHH), <code>responsable</code> (responsable de datos) y <code>demo</code> (administrador); contraseña{" "}
                          <code>demo</code>.
                        </p>
                      </AlertDescription>
                    </Alert>
                  )}
                </CardContent>
                <CardFooter className="flex-col gap-3 pt-2">
                  <Button type="submit" className="w-full" size="lg" disabled={submitting || (!firstRun && chosen.length === 0)}>
                    {submitting && <Loader2 className="animate-spin" />}
                    {firstRun ? "Conectar y continuar" : "Entrar"}
                  </Button>
                  <Separator />
                  <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
                    <ShieldCheck className="size-3.5" /> La contraseña solo vive cifrada en memoria del servicio durante tu sesión.
                  </p>
                </CardFooter>
              </form>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}
