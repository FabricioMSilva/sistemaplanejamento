import Head from "next/head";
import { useEffect, useState } from "react";
import { CheckCircle2, ClipboardPlus, FileSpreadsheet, LoaderCircle, RefreshCw, ShieldAlert, X } from "lucide-react";
import Header from "@/components/Header";
import RondaDashboardCharts from "@/components/RondaDashboardCharts";
import { getDashboard } from "@/services/api";
import {
  getBmaPageMonitor, getRondaDashboard, startRondaCreation, startRondaExcelExport,
  pauseRondaCreation, resumeRondaCreation, startRondaSharePointCollection, stopBmaPageMonitor,
  type BmaPageMonitor, type RondaDashboard,
} from "@/services/pcm";

const MONITOR_STORAGE_KEY = "pcm:ronda-monitor";
const MONITOR_MODE_STORAGE_KEY = "pcm:ronda-monitor-mode";

export default function OtPage() {
  const [status, setStatus] = useState("offline");
  const [monitorId, setMonitorId] = useState("");
  const [monitor, setMonitor] = useState<BmaPageMonitor | null>(null);
  const [dashboard, setDashboard] = useState<RondaDashboard | null>(null);
  const [error, setError] = useState("");
  const [dashboardError, setDashboardError] = useState("");
  const [confirmCreate, setConfirmCreate] = useState(false);
  const [quantity, setQuantity] = useState<"uma" | "lote">("uma");

  useEffect(() => {
    let cancelled = false;
    getDashboard().then((data) => { if (!cancelled) setStatus(data.status_sistema); })
      .catch(() => { if (!cancelled) setStatus("offline"); });
    getRondaDashboard().then((data) => { if (!cancelled) setDashboard(data); })
      .catch((reason) => { if (!cancelled) setDashboardError(reason instanceof Error ? reason.message : "Falha ao carregar o dashboard."); });
    const savedMonitorId = window.sessionStorage.getItem(MONITOR_STORAGE_KEY);
    const savedMonitorMode = window.sessionStorage.getItem(MONITOR_MODE_STORAGE_KEY) as BmaPageMonitor["mode"];
    if (savedMonitorId) {
      setMonitorId(savedMonitorId);
      if (savedMonitorMode) setMonitor({
        monitor_id: savedMonitorId, mode: savedMonitorMode, status: "monitoring",
        message: "Reconectando ao processo em andamento...", fields: [], progress: 0,
      });
    }
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!monitorId) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const current = await getBmaPageMonitor(monitorId);
        if (cancelled) return;
        setMonitor(current);
        if (["starting", "monitoring", "pausing", "paused", "stopping"].includes(current.status)) {
          timer = window.setTimeout(poll, 1200);
        } else {
          window.sessionStorage.removeItem(MONITOR_STORAGE_KEY);
          window.sessionStorage.removeItem(MONITOR_MODE_STORAGE_KEY);
          if (current.status === "failed") setError(current.message);
          getRondaDashboard().then(setDashboard).catch(() => undefined);
        }
      } catch (reason) {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Falha ao consultar o progresso da operação.";
        if (message.includes("Monitor BMA não encontrado")) {
          const mode = monitor?.mode || window.sessionStorage.getItem(MONITOR_MODE_STORAGE_KEY) as BmaPageMonitor["mode"];
          window.sessionStorage.removeItem(MONITOR_STORAGE_KEY);
          window.sessionStorage.removeItem(MONITOR_MODE_STORAGE_KEY);
          setMonitor((current) => current ? {
            ...current, status: "failed", stage: "failed", progress: 100,
            message: "O processo foi encerrado junto com o backend. O progresso salvo no SQL pode ser retomado.",
          } : mode ? {
            monitor_id: monitorId, mode, status: "failed", stage: "failed", progress: 100,
            message: "O processo foi encerrado junto com o backend. O progresso salvo no SQL pode ser retomado.",
            fields: [],
          } : null);
          setError("A sessão do monitor não existe mais. O progresso foi recuperado do banco de dados.");
          setMonitorId("");
          getRondaDashboard().then(setDashboard).catch(() => undefined);
          return;
        }
        setError(message);
      }
    };
    void poll();
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, [monitorId]);

  async function refreshFromSharePoint() {
    setError("");
    setMonitor({ monitor_id: "", mode: "ronda_sharepoint", inspection_only: true, status: "starting",
      message: "Atualizando os registros do SharePoint...", fields: [], progress: 0 });
    try {
      const { monitor_id } = await startRondaSharePointCollection();
      window.sessionStorage.setItem(MONITOR_STORAGE_KEY, monitor_id);
      window.sessionStorage.setItem(MONITOR_MODE_STORAGE_KEY, "ronda_sharepoint");
      setMonitorId(monitor_id);
      setMonitor((current) => current ? { ...current, monitor_id } : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao atualizar os dados do SharePoint.");
      setMonitor((current) => current ? { ...current, status: "failed" } : current);
    }
  }

  async function updateRondaExcelOnSharePoint() {
    setError("");
    setMonitor({ monitor_id: "", mode: "ronda_excel_export", inspection_only: false, status: "starting",
      message: "Preparando o Excel de OTs de Ronda...", fields: [], progress: 0 });
    try {
      const { monitor_id } = await startRondaExcelExport();
      window.sessionStorage.setItem(MONITOR_STORAGE_KEY, monitor_id);
      window.sessionStorage.setItem(MONITOR_MODE_STORAGE_KEY, "ronda_excel_export");
      setMonitorId(monitor_id);
      setMonitor((current) => current ? { ...current, monitor_id } : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao iniciar a atualização do Excel no SharePoint.");
      setMonitor((current) => current ? { ...current, status: "failed" } : current);
    }
  }

  async function createAllOrders() {
    setConfirmCreate(false);
    setError("");
    setMonitor({ monitor_id: "", mode: "ronda_creation", inspection_only: false, status: "starting",
      message: "Preparando as OTs e abrindo o BMA...", fields: [], progress: 0 });
    try {
      const { monitor_id } = await startRondaCreation(true, quantity);
      window.sessionStorage.setItem(MONITOR_STORAGE_KEY, monitor_id);
      window.sessionStorage.setItem(MONITOR_MODE_STORAGE_KEY, "ronda_creation");
      setMonitorId(monitor_id);
      setMonitor((current) => current ? { ...current, monitor_id } : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao iniciar a criação das OTs.");
      setMonitor((current) => current ? { ...current, status: "failed" } : current);
    }
  }

  async function releaseFailedCreationSession() {
    if (!monitorId) return;
    setError("");
    try {
      const stopped = await stopBmaPageMonitor(monitorId);
      setMonitor(stopped);
      if (stopped.status === "stopped") {
        window.sessionStorage.removeItem(MONITOR_STORAGE_KEY);
        window.sessionStorage.removeItem(MONITOR_MODE_STORAGE_KEY);
        setMonitorId("");
        getRondaDashboard().then(setDashboard).catch(() => undefined);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao encerrar a sessão do Firefox.");
    }
  }

  async function pauseRondaBatch() {
    if (!monitorId) return;
    try { setMonitor(await pauseRondaCreation(monitorId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Falha ao pausar o lote."); }
  }

  async function resumePausedRondaBatch() {
    if (!monitorId) return;
    try { setMonitor(await resumeRondaCreation(monitorId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Falha ao retomar o lote."); }
  }

  const busy = !!monitor && ["starting", "monitoring", "pausing", "paused", "stopping"].includes(monitor.status);
  const retryFailed = (dashboard?.falhas_criacao ?? 0) > 0;
  const hasCreatableOrders = (dashboard?.aptas ?? 0) > 0;
  const selectableCount = dashboard?.aptas ?? 0;
  const requestedCount = quantity === "uma" ? Math.min(1, selectableCount) : selectableCount;
  const metricCards = [
    { label: "Registros SQL", value: dashboard?.total ?? 0, icon: ClipboardPlus },
    { label: "Pendentes", value: dashboard?.pendentes ?? 0, icon: RefreshCw },
    { label: "Aptas para criar", value: dashboard?.aptas ?? 0, icon: CheckCircle2 },
    { label: "Bloqueadas", value: dashboard?.bloqueadas ?? 0, icon: ShieldAlert },
    { label: "OTs criadas", value: dashboard?.criadas ?? 0, icon: ClipboardPlus },
  ];

  return (
    <>
      <Head><title>Criar OT | Planning & Scheduling Michelin</title></Head>
      <main className="mx-auto min-h-screen max-w-7xl px-4 py-6">
        <Header status={status} />
        <section className="mt-6 space-y-6" aria-label="Dashboard de OTs de Ronda">
          <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-primary">BMA · SharePoint</p>
              <h1 className="mt-1 text-2xl font-semibold text-foreground">Rondas NFE</h1>
              <p className="mt-1 text-sm text-muted-foreground">Acompanhamento de execuções e pendências das rondas.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="pcm-small-button" disabled={busy} onClick={() => void refreshFromSharePoint()}>
                {busy && monitor?.mode === "ronda_sharepoint" ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                Atualizar dados
              </button>
              <button type="button" className="pcm-small-button" disabled={busy || (dashboard?.total ?? 0) === 0}
                onClick={() => void updateRondaExcelOnSharePoint()}>
                {busy && monitor?.mode === "ronda_excel_export" ? <LoaderCircle size={16} className="animate-spin" /> : <FileSpreadsheet size={16} />}
                Atualizar Excel SharePoint
              </button>
              <button type="button" className="pcm-primary-button" disabled={busy || !hasCreatableOrders}
                onClick={() => { setQuantity("uma"); setConfirmCreate(true); }}>
                {busy && monitor?.mode === "ronda_creation" ? <LoaderCircle size={16} className="animate-spin" /> : <ClipboardPlus size={16} />}
                Criar OTs
              </button>
            </div>
          </div>

          {(busy || error || dashboardError) && <div className="space-y-2" role="status">
            {busy && <div className="flex items-center gap-3 rounded-md border border-border bg-surface p-3">
              <LoaderCircle size={17} className="animate-spin text-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-foreground">{monitor?.message}</p>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full bg-primary transition-[width]" style={{ width: `${monitor?.progress ?? 0}%` }} />
                </div>
              </div>
              <span className="text-xs tabular-nums text-muted-foreground">{monitor?.progress ?? 0}%</span>
              {monitor?.mode === "ronda_creation" && ["starting", "monitoring"].includes(monitor.status) && <button
                type="button" className="pcm-small-button" onClick={() => void pauseRondaBatch()}>
                Pausar lote
              </button>}
              {monitor?.mode === "ronda_creation" && monitor.status === "pausing" && <span className="text-xs text-muted-foreground">
                Pausará após a OT atual
              </span>}
              {monitor?.mode === "ronda_creation" && monitor.status === "paused" && <button
                type="button" className="pcm-primary-button" onClick={() => void resumePausedRondaBatch()}>
                Retomar lote
              </button>}
            </div>}
            {!!monitor?.events?.length && <ol aria-live="polite" className="max-h-28 space-y-1 overflow-y-auto rounded-md border border-border bg-surface px-3 py-2 text-xs text-muted-foreground">
              {monitor.events.slice(-5).reverse().map((event, index) => <li key={`${event.at}-${index}`}>
                <time dateTime={event.at}>{new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(event.at))}</time>
                {" · "}{event.message}
              </li>)}
            </ol>}
            {error && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 text-sm text-destructive">
              <p>{error}</p>
              {monitor?.mode === "ronda_creation" && monitor.status === "failed"
                && monitor.message.includes("Firefox ficará aberto") && <button
                  type="button" className="pcm-small-button" onClick={() => void releaseFailedCreationSession()}>
                  <X size={15} /> Encerrar sessão Firefox
                </button>}
              {monitor?.mode === "ronda_creation" && monitor.status === "failed" && <button
                type="button" className="pcm-primary-button"
                onClick={() => { setQuantity("lote"); setConfirmCreate(true); }}>
                <RefreshCw size={15} /> Retomar lote
              </button>}
            </div>}
            {dashboardError && <p role="alert" className="text-sm text-destructive">{dashboardError}</p>}
          </div>}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Indicadores das rondas">
            {metricCards.map(({ label, value, icon: Icon }) => <article key={label} className="rounded-md border border-border bg-surface p-4">
              <div className="flex items-center justify-between gap-3 text-muted-foreground">
                <span className="text-xs font-medium">{label}</span><Icon size={16} aria-hidden="true" />
              </div>
              <p className="mt-3 text-2xl font-semibold tabular-nums text-foreground">{value.toLocaleString("pt-BR")}</p>
            </article>)}
          </div>

          <section aria-labelledby="round-summary-title" className="border-t border-border pt-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="round-summary-title" className="text-base font-semibold text-foreground">Pendências por modalidade</h2>
              <p className="text-xs text-muted-foreground">{dashboard?.atualizado_em
                ? `SQL atualizado em ${new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(dashboard.atualizado_em))}`
                : "Aguardando primeira sincronização"}</p>
            </div>
            <div className="mt-3 divide-y divide-border">
              {(dashboard?.rondas ?? []).map((round) => <div key={round.nome} className="flex flex-wrap items-center gap-3 py-3">
                <span className="min-w-48 flex-1 text-sm font-medium text-foreground">{round.nome}</span>
                <span className="text-sm text-muted-foreground">{round.total} pendentes</span>
                <span className="text-sm font-semibold text-success">{round.aptas} aptas</span>
              </div>)}
              {!dashboard?.rondas.length && <p className="py-8 text-center text-sm text-muted-foreground">Nenhuma lista sincronizada ainda.</p>}
            </div>
          </section>

          {retryFailed && <section role="alert" className="rounded-md border border-warning/40 bg-warning/5 p-4">
            <h2 className="text-sm font-semibold text-foreground">{dashboard?.falhas_criacao} tentativa(s) interrompida(s)</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Tentativas sem número de OT podem ser processadas novamente. Registros com número confirmado não entram na fila.
            </p>
            <ul className="mt-2 grid gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
              {(dashboard?.falhas ?? []).filter((failure) => failure.status === "erro" && !failure.numero_ot).slice(0, 8).map((failure) => <li key={failure.sharepoint_id}>
                ID {failure.sharepoint_id} · {failure.ronda} · sem número confirmado
              </li>)}
            </ul>
          </section>}

          {dashboard?.graficos && <RondaDashboardCharts data={dashboard.graficos} />}
        </section>
      </main>

      {confirmCreate && <div className="fixed inset-0 z-[120] grid place-items-center bg-black/60 p-4" role="presentation">
        <section role="dialog" aria-modal="true" aria-labelledby="confirm-create-title" className="pcm-panel w-full max-w-lg p-5">
          <h2 id="confirm-create-title" className="text-lg font-semibold text-foreground">Confirmar criação das OTs</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Serão processadas {requestedCount} OT(s). O sistema abrirá o Firefox, entrará no BMA e no Quick Report;
            cada número criado será salvo no SQL. A lista SharePoint não será alterada.
          </p>
          <div className="mt-4 inline-flex rounded-md border border-border p-1" role="group" aria-label="Quantidade de OTs">
            {([{ value: "uma", label: "1 OT" }, { value: "lote", label: "Lote todo" }] as const).map((option) => <button
              key={option.value} type="button" aria-pressed={quantity === option.value}
              onClick={() => setQuantity(option.value)}
              className={`rounded px-3 py-2 text-sm ${quantity === option.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}>
              {option.label}
            </button>)}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" className="pcm-small-button" onClick={() => setConfirmCreate(false)}><X size={15} /> Cancelar</button>
            <button type="button" className="pcm-primary-button"
              onClick={() => void createAllOrders()}><ClipboardPlus size={15} /> Confirmar e criar</button>
          </div>
        </section>
      </div>}
    </>
  );
}
