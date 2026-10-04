import { zodResolver } from "@hookform/resolvers/zod";
import { useState, type FormEvent } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { api, jsonBody } from "../lib/api";
import { Button, Card, Field } from "./ui";

const schema = z.object({ email: z.email(), password: z.string().min(1) });
type LoginFields = z.infer<typeof schema>;

export function LoginPanel({ role, onSuccess }: {
  role: "patient" | "responder" | "ed"; onSuccess: () => void;
}) {
  const { t } = useTranslation();
  const [error, setError] = useState(false);
  const [pending, setPending] = useState(false);
  const [mfa, setMfa] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[]>([]);
  const { register, handleSubmit, formState: { errors } } = useForm<LoginFields>({ resolver: zodResolver(schema) });
  async function submit(values: LoginFields) {
    setPending(true); setError(false);
    try {
      const result = await api<{mfa_required: boolean; mfa_setup_required: boolean}>("/api/v1/auth/login", { method: "POST", body: jsonBody(values) });
      if (result.mfa_required) {
        setMfa(true);
        if (result.mfa_setup_required) {
          const setup = await api<{secret: string}>("/api/v1/auth/mfa/setup", {method: "POST"});
          setSecret(setup.secret);
        }
        return;
      }
      onSuccess();
    } catch { setError(true); }
    finally { setPending(false); }
  }
  async function verifyMfa(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(false);
    try {
      const result = await api<{recovery_codes: string[]}>("/api/v1/auth/mfa/verify", {method: "POST", body: jsonBody({code})});
      setCode(""); setSecret(null);
      if (result.recovery_codes.length) setRecovery(result.recovery_codes);
      else onSuccess();
    } catch { setError(true); }
    finally { setPending(false); }
  }
  return <Card className="mx-auto max-w-md space-y-5">
    <h1 className="text-2xl font-black">{t("login.title")}</h1>
    <p className="subtle text-sm">{t(`login.${role}Hint`)}</p>
    {recovery.length > 0 ? <div className="space-y-3"><p>{t("login.recovery")}</p>
      <ul className="surface-muted space-y-1 rounded-lg p-3 font-mono text-sm">{recovery.map((item) => <li key={item}>{item}</li>)}</ul>
      <Button onClick={() => { setRecovery([]); onSuccess(); }}>{t("common.close")}</Button>
    </div> : mfa ? <form onSubmit={(event) => void verifyMfa(event)} className="space-y-4">
      {secret && <div className="surface-muted rounded-lg p-3"><p className="text-sm">{t("login.mfaSetup")}</p><code className="break-all select-all">{secret}</code></div>}
      <Field id="mfa-code" label={t("login.mfa")} autoComplete="one-time-code" required value={code} onChange={(event) => setCode(event.target.value)} />
      {error && <p role="alert" className="text-sm text-[#ad2335]">{t("login.failed")}</p>}
      <Button type="submit" disabled={pending || !code}>{t("login.submit")}</Button>
    </form> : <form onSubmit={handleSubmit(submit)} className="space-y-4" noValidate>
      <Field id="email" type="email" autoComplete="username" label={t("common.email")} {...register("email")} />
      {errors.email && <p role="alert" className="text-sm text-[#ad2335]">{t("login.failed")}</p>}
      <Field id="password" type="password" autoComplete="current-password" label={t("common.password")} {...register("password")} />
      {error && <p role="alert" className="text-sm font-semibold text-[#ad2335]">{t("login.failed")}</p>}
      <Button type="submit" disabled={pending} className="w-full">{t("login.submit")}</Button>
    </form>}
  </Card>;
}
