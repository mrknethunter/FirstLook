import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, jsonBody } from "../lib/api";
import { Button, Card, Field } from "./ui";

export function RegisterPanel() {
  const { t, i18n } = useTranslation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [consent, setConsent] = useState(false);
  const [status, setStatus] = useState<"idle" | "pending" | "success" | "error">("idle");
  async function submit(event: FormEvent) {
    event.preventDefault(); setStatus("pending");
    try {
      await api("/api/v1/auth/register", {method: "POST", body: jsonBody({
        email, password, locale: i18n.language.slice(0, 2), profile_storage_consent: consent,
      })});
      setPassword(""); setStatus("success");
    } catch { setStatus("error"); }
  }
  return <Card className="mx-auto max-w-md space-y-4"><h2 className="text-xl font-black">{t("register.title")}</h2>
    {status === "success" ? <p role="status">{t("register.success")}</p> : <form onSubmit={submit} className="space-y-4">
      <Field id="register-email" type="email" autoComplete="email" required label={t("common.email")} value={email} onChange={(event) => setEmail(event.target.value)} />
      <Field id="register-password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required label={t("common.password")} value={password} onChange={(event) => setPassword(event.target.value)} />
      <label className="flex min-h-11 items-start gap-3 text-sm"><input type="checkbox" className="mt-1 h-5 w-5" required checked={consent} onChange={(event) => setConsent(event.target.checked)} />{t("register.consent")}</label>
      {status === "error" && <p role="alert" className="text-[#ad2335]">{t("register.failed")}</p>}
      <Button disabled={status === "pending" || !consent} type="submit">{t("register.submit")}</Button>
    </form>}
  </Card>;
}
