import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { LoginPanel } from "./components/LoginPanel";
import { Button, Card } from "./components/ui";
import { api, getPrincipal } from "./lib/api";
import { validateDemoViewerUrl } from "./lib/demoEntry";
import { EdBoard } from "./pages/EdBoard";
import { PatientApp } from "./pages/PatientApp";
import { ShlViewer } from "./pages/ShlViewer";

function DemoEntry() {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    void fetch("/api/v1/demo/entry", { credentials: "same-origin", cache: "no-store", referrerPolicy: "no-referrer" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Unavailable");
        const body: unknown = await response.json();
        if (!body || typeof body !== "object" || !("viewer_url" in body)) throw new Error("Invalid response");
        const viewerUrl = validateDemoViewerUrl((body as {viewer_url: unknown}).viewer_url, window.location.origin);
        if (active) window.location.replace(viewerUrl);
      }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);
  return <Shell compact><Card><h1 className="text-2xl font-black">FirstLook</h1><p role="status">{t(failed ? "demo.unavailable" : "demo.opening")}</p></Card></Shell>;
}

function Home() {
  const { t } = useTranslation();
  return <Shell><div className="grid gap-6 py-8 md:grid-cols-2 md:py-16">
    <div className="space-y-5"><p className="font-bold text-[#a72024] dark:text-[#ff8989]">{t("brand.tagline")}</p>
      <h1 className="text-4xl font-black leading-tight sm:text-5xl">{t("home.title")}</h1>
      <p className="subtle max-w-prose text-lg">{t("home.body")}</p>
      <Link to="/demo"><Button>{t("home.demo")}</Button></Link></div>
    <Card className="space-y-4"><h2 className="text-xl font-black">FirstLook</h2>
      <div className="grid gap-3"><Link to="/app" className="surface-muted min-h-14 rounded-xl p-4 font-bold hover:underline">{t("nav.patient")}</Link>
        <Link to="/responder" className="surface-muted min-h-14 rounded-xl p-4 font-bold hover:underline">{t("nav.responder")}</Link>
        <Link to="/ed" className="surface-muted min-h-14 rounded-xl p-4 font-bold hover:underline">{t("nav.ed")}</Link></div>
    </Card>
  </div></Shell>;
}

function Responder() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => { void getPrincipal().then((principal) => setSignedIn(principal?.role === "responder")).catch(() => {}); }, []);
  return <Shell><div className="mx-auto max-w-xl space-y-4"><Card className="space-y-3"><div className="flex items-center justify-between gap-3"><h1 className="text-2xl font-black">{t("nav.responder")}</h1>{signedIn && <Button variant="outline" onClick={() => { void api("/api/v1/auth/logout", {method: "POST"}).then(() => { qc.clear(); window.location.assign("/"); }); }}>{t("common.signOut")}</Button>}</div>
    <p>{t("viewer.responderHint")}</p><p className="subtle text-sm">{t("responder.scanHint")}</p>
    <Link to="/demo" className="text-[#a72024] underline dark:text-[#ff8989]">{t("home.demo")}</Link>
  </Card>{!signedIn && <LoginPanel role="responder" onSuccess={() => { void getPrincipal().then((principal) => setSignedIn(principal?.role === "responder")); }} />}</div></Shell>;
}

export default function App() {
  return <Routes>
    <Route path="/" element={<Home />} />
    <Route path="/demo" element={<DemoEntry />} />
    <Route path="/s" element={<ShlViewer />} />
    <Route path="/responder" element={<Responder />} />
    <Route path="/app" element={<PatientApp />} />
    <Route path="/ed" element={<EdBoard />} />
    <Route path="*" element={<Home />} />
  </Routes>;
}
