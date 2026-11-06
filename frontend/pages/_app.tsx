import type { AppProps } from "next/app";
import Head from "next/head";
import { useEffect, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
import "@/styles/globals.css";
import AppShell from "@/components/layout/AppShell";
import { APP_BRAND } from "@/config/brand-assets";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { API_URL, apiFetch } from "@/services/api";

type ApiState = "checking" | "ready" | "offline";

function ApiStartupGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<ApiState>("checking");
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout>;
    const deadline = Date.now() + 20_000;

    const check = async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 2_500);
      try {
        const response = await apiFetch(`${API_URL}/api/health`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`A API respondeu com status HTTP ${response.status}.`);
        const result = await response.json();
        if (result.status !== "online") throw new Error("A API ainda não informou que está pronta.");
        if (!cancelled) setState("ready");
      } catch (cause) {
        if (cancelled) return;
        const message = cause instanceof Error ? cause.message : "A API local não respondeu.";
        setError(message);
        if (Date.now() >= deadline) {
          setState("offline");
        } else {
          retryTimer = setTimeout(check, 750);
        }
      } finally {
        clearTimeout(timeout);
      }
    };

    setState("checking");
    setError("");
    void check();
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
    };
  }, [attempt]);

  if (state === "ready") return children;

  return (
    <main className="grid min-h-screen place-items-center bg-slate-950 px-6 text-slate-100" role={state === "offline" ? "alert" : "status"}>
      <section className="w-full max-w-lg space-y-4 text-center">
        {state === "checking" ? (
          <LoaderCircle className="mx-auto size-9 animate-spin text-sky-400" aria-hidden="true" />
        ) : (
          <div className="mx-auto grid size-12 place-items-center rounded-full bg-rose-400/10 text-rose-300" aria-hidden="true">!</div>
        )}
        <h1 className="text-xl font-semibold">
          {state === "checking" ? "Conectando aos serviços locais" : "Serviço local indisponível"}
        </h1>
        {state === "checking" ? (
          <p className="text-sm text-slate-300">Aguardando a API ficar pronta. Isso pode levar alguns segundos.</p>
        ) : (
          <>
            <p className="text-sm text-slate-300">O aplicativo não conseguiu acessar a API após várias tentativas.</p>
            <p className="break-words text-sm text-rose-200">{error}</p>
            <button
              type="button"
              onClick={() => { setState("checking"); setAttempt((value) => value + 1); }}
              className="mx-auto inline-flex items-center gap-2 rounded-md border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
            >
              <RefreshCw size={16} aria-hidden="true" />
              Tentar novamente
            </button>
          </>
        )}
      </section>
    </main>
  );
}

export default function App({ Component, pageProps }: AppProps) {
  return (
    <ThemeProvider>
      <Head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{APP_BRAND.name}</title>
      </Head>
      <ApiStartupGate>
        <AppShell>
          <Component {...pageProps} />
        </AppShell>
      </ApiStartupGate>
    </ThemeProvider>
  );
}
