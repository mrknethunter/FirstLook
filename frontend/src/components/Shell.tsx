import { Moon, Sun } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { changeLanguage, type Language } from "../i18n";
import { Toggle } from "./ui";

let themeOverride: boolean | null = null;

export function Shell({ children, compact = false }: {children: ReactNode; compact?: boolean}) {
  const { t, i18n } = useTranslation();
  const [dark, setDark] = useState(() => themeOverride ?? window.matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  return <>
    <header className="nav-surface sticky top-0 z-30">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <Link to="/" className="order-1 mr-auto inline-flex min-h-11 items-center rounded-lg bg-white px-1 py-0.5 md:mr-0">
          <img src="/firstlook-logo.png" alt="FirstLook" className="block h-8 w-auto md:h-9" />
        </Link>
        {!compact && <nav aria-label={t("nav.main")} className="order-3 flex w-full flex-wrap gap-1 text-sm font-semibold md:order-2 md:mx-auto md:w-auto">
          <Link to="/app" className="inline-flex min-h-11 items-center rounded-lg px-2 hover:underline">{t("nav.patient")}</Link>
          <Link to="/responder" className="inline-flex min-h-11 items-center rounded-lg px-2 hover:underline">{t("nav.responder")}</Link>
          <Link to="/ed" className="inline-flex min-h-11 items-center rounded-lg px-2 hover:underline">{t("nav.ed")}</Link>
        </nav>}
        <div className="order-2 flex items-center gap-2 md:order-3">
          <label className="sr-only" htmlFor="language">{t("common.language")}</label>
          <select id="language" value={i18n.language.slice(0, 2)}
            onChange={(event) => changeLanguage(event.target.value as Language)}
            className="field !min-h-11 !w-auto !px-2 text-sm" aria-label={t("common.language")}>
            <option value="en">EN</option><option value="pl">PL</option><option value="it">IT</option>
          </select>
          <div className="flex items-center gap-1" title={t("common.theme")}>
            {dark ? <Moon size={17} aria-hidden="true" /> : <Sun size={17} aria-hidden="true" />}
            <Toggle checked={dark} onCheckedChange={(value) => { themeOverride = value; setDark(value); }} label={t("common.theme")} showLabel={false} />
          </div>
        </div>
      </div>
    </header>
    <main className="mx-auto max-w-6xl px-4 py-6 md:py-8">{children}</main>
  </>;
}
