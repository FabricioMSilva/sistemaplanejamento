import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Factory, Monitor, RefreshCw } from "lucide-react";
import OrdersTable from "@/components/OrdersTable";
import LaborPlanningModal from "@/components/LaborPlanningModal";
import PcmCommandCenter from "@/components/PcmCommandCenter";
import NfeReportButton from "@/components/NfeReportButton";
import {
  listarOrdensTrabalho, listarMaoDeObra, obterCalendarioTurnos, obterEquipe,
  type CalendarioTurnos, type MaoDeObra, type OrdemTrabalho, type PlanejamentoEquipe,
} from "@/services/api";
import { applyFilters, emptyFilters, type OrderFilters } from "@/utils/orderFilters";
import { createWorkPlan, exportPortfolio, type PlanningMode } from "@/services/pcm";
import { equipeDefinida, periodoValido } from "@/utils/laborPlanning";
import { buildDashboard } from "@/utils/pcmDashboard";

export default function PlanejamentoOtsPage() {
  const router = useRouter();
  const sectors = useMemo(() => {
    const raw = router.query.setor;
    return Array.isArray(raw) ? raw : raw ? [raw] : [];
  }, [router.query.setor]);
  const [mode, setMode] = useState<"pm" | "corretiva">("pm");
  const [filters, setFilters] = useState<OrderFilters>(emptyFilters);
  const [orders, setOrders] = useState<OrdemTrabalho[]>([]);
  const [labor, setLabor] = useState<MaoDeObra | null>(null);
  const [calendar, setCalendar] = useState<CalendarioTurnos | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [capacityError, setCapacityError] = useState("");
  const [teamError, setTeamError] = useState("");
  const [inicio, setInicio] = useState("");
  const [fim, setFim] = useState("");
  const [savedTeam, setSavedTeam] = useState<PlanejamentoEquipe | null>(null);
  const [teamOpen, setTeamOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [tv, setTv] = useState(false);
  const [loadedScope, setLoadedScope] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const scope = JSON.stringify(sectors);

  useEffect(() => {
    if (!router.isReady) return;
    let cancelled = false;
    setLoading(true); setError(""); setTeamError(""); setCapacityError("");
    setTeamOpen(false); setSavedTeam(null); setLabor(null); setCalendar(null);
    setOrders([]); setInicio(""); setFim(""); setMessage(""); setFilters(emptyFilters);
    setLoadedScope("");
    if (!sectors.length) {
      setError("Nenhum setor informado. Volte à coleta e selecione o setor de manutenção.");
      setLoading(false);
      return;
    }
    Promise.allSettled([
      listarOrdensTrabalho(sectors), obterEquipe(sectors),
      listarMaoDeObra(sectors), obterCalendarioTurnos(),
    ]).then(([orderResult, teamResult, laborResult, calendarResult]) => {
      if (cancelled) return;
      const explain = (reason: unknown) => reason instanceof Error ? reason.message : "Falha de comunicação com a API.";
      if (orderResult.status === "fulfilled") setOrders(orderResult.value);
      else setError(`Carteira: ${explain(orderResult.reason)}`);
      if (teamResult.status === "fulfilled") {
        setSavedTeam(teamResult.value);
        setInicio(teamResult.value?.inicio ?? "");
        setFim(teamResult.value?.fim ?? "");
      } else setTeamError(`Equipe salva: ${explain(teamResult.reason)}`);
      const errors = [];
      if (laborResult.status === "fulfilled") setLabor(laborResult.value);
      else errors.push(`Efetivo: ${explain(laborResult.reason)}`);
      if (calendarResult.status === "fulfilled") setCalendar(calendarResult.value);
      else setMessage(`Calendário de referência: ${explain(calendarResult.reason)} A capacidade por dias disponíveis não depende do calendário.`);
      setCapacityError(errors.join(" "));
      setLoading(false);
      setLoadedScope(scope);
    });
    return () => { cancelled = true; };
  }, [router.isReady, sectors, scope, attempt]);

  const samePeriod = !loading && loadedScope === scope && equipeDefinida(savedTeam, inicio, fim, sectors);
  const validPeriod = periodoValido(inicio, fim) ? { inicio, fim } : null;
  const data = useMemo(() => buildDashboard(orders, samePeriod ? savedTeam : null, labor, calendar, validPeriod, true),
    [orders, samePeriod, savedTeam, labor, calendar, inicio, fim]);
  const canPlan = samePeriod && !teamError && !capacityError && data.validTeam;
  const canDefineTeam = !loading && !teamError && sectors.length > 0 && periodoValido(inicio, fim);
  const modeOrders = mode === "pm" ? data.pmAllRows : data.corrective.rows;
  const latestSync = orders.reduce((latest, order) => order.sincronizado_em > latest ? order.sincronizado_em : latest, "");
  const syncDate = latestSync ? new Date(latestSync) : null;

  async function openPlanning(selected: PlanningMode) {
    setActionBusy(true); setError("");
    try {
      const plan = await createWorkPlan(sectors);
      await router.push({ pathname: "/planejamento/alocacao", query: { plano: plan.id, modo: selected } });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao abrir o planejamento.");
    } finally { setActionBusy(false); }
  }
  async function exportOrders(selected: PlanningMode) {
    setActionBusy(true); setError("");
    try {
      const rows = applyFilters(selected === "pm" ? data.pm.rows : data.corrective.rows, filters);
      await exportPortfolio(sectors, inicio, fim, selected, rows);
      setMessage(`${rows.length} OTs exportadas em Excel, respeitando os filtros atuais da tabela.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao exportar a carteira.");
    } finally { setActionBusy(false); }
  }

  return (
    <>
      <Head><title>Centro de Planejamento PCM | BMA Intranet</title></Head>
      <main className={`pcm-workspace mx-auto min-h-screen px-4 py-6 sm:px-6 lg:px-8 ${tv ? "pcm-tv max-w-[2560px]" : "max-w-[1800px]"}`}>
        <header className="mb-6">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <Link href="/planejamento" className="inline-flex items-center gap-2 text-xs font-medium text-slate-400 transition hover:text-white"><ArrowLeft size={14} /> Voltar para a coleta</Link>
            <div className="flex flex-wrap items-center gap-2">
              <NfeReportButton />
              <span className="pcm-badge text-slate-400"><span className="h-1.5 w-1.5 rounded-full bg-sky-400" /> BMA · snapshot local</span>
              <button type="button" onClick={() => setTv((current) => !current)} aria-pressed={tv} className="pcm-small-button"><Monitor size={14} /> {tv ? "Sair do modo TV" : "Modo TV"}</button>
              <button type="button" disabled={loading} onClick={() => setAttempt((current) => current + 1)} className="pcm-small-button" title="Recarrega o banco local; não inicia sincronização no BMA"><RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Recarregar dados</button>
            </div>
          </div>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex items-center gap-4">
              <span className="hidden h-14 w-14 items-center justify-center rounded-2xl border border-sky-400/20 bg-gradient-to-br from-blue-500/20 to-sky-400/5 text-sky-300 sm:flex"><Factory size={28} /></span>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-sky-300">Operações industriais / PCM</p>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white sm:text-3xl">Centro de Planejamento</h1>
                <p className="mt-2 text-xs text-slate-500">Capacidade, carteira e preparação em uma única visão operacional.</p>
              </div>
            </div>
            <div className="text-right">
              <div className="mb-2 flex flex-wrap justify-end gap-2">{sectors.map((sector) => <span key={sector} className="pcm-badge text-sky-200">{sector}</span>)}</div>
              <p className="text-[10px] text-slate-500">Coleta de OTs: {syncDate && Number.isFinite(syncDate.getTime()) ? new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" }).format(syncDate) + " (Brasília)" : "não disponível"}</p>
            </div>
          </div>
        </header>
        {(error || teamError || capacityError) && <div role="alert" className="mb-5 rounded-xl border border-rose-400/20 bg-rose-400/5 p-4 text-sm text-rose-300">
          {[error, teamError, capacityError].filter(Boolean).map((text) => <p key={text}>{text}</p>)}
          <button type="button" onClick={() => setAttempt((current) => current + 1)} className="mt-3 underline">Tentar carregar novamente</button>
        </div>}
        {inicio && fim && !periodoValido(inicio, fim) && <p role="alert" className="mb-4 text-sm text-amber-300">O fim do planejamento deve ser igual ou posterior ao início.</p>}
        {savedTeam && (savedTeam.inicio !== inicio || savedTeam.fim !== fim) && <p className="mb-4 text-sm text-amber-300">Período alterado. Revise e salve a mão de obra para liberar as carteiras.</p>}
        {samePeriod && !loading && !data.validTeam && !capacityError && <p role="alert" className="mb-4 text-sm text-amber-300">Há pendências na equipe salva. Revise o cadastro, as funções e os dias disponíveis para liberar o planejamento.</p>}
        {message && <p role="status" className="mb-4 text-sm text-emerald-300">{message}</p>}
        <PcmCommandCenter data={data} orders={data.pending} inicio={inicio} fim={fim} calendario={calendar}
          setInicio={(value) => { setInicio(value); setMessage(""); }} setFim={(value) => { setFim(value); setMessage(""); }}
          canPlan={canPlan} canDefineTeam={canDefineTeam} teamLoading={loading} teamError={teamError}
          loading={loading} savedTeam={savedTeam} mode={mode} onMode={setMode}
          onTeam={() => setTeamOpen(true)} dataError={error}
          onPlan={openPlanning} onExport={exportOrders} busy={actionBusy} />
        <section className="pcm-panel mt-5 min-w-0 p-5" id="pcm-orders" aria-label="Carteira de ordens">
          {canPlan ? <OrdersTable orders={modeOrders} filters={filters} onFiltersChange={setFilters} loading={loading} /> : (
            <div className="py-7 text-center"><h2 className="text-sm font-semibold text-slate-300">Carteiras aguardando definição da mão de obra</h2>
              <p className="mt-2 text-xs text-slate-500">Informe o período, configure os executantes e salve a equipe. Os indicadores acima permanecem disponíveis para diagnóstico.</p></div>
          )}
        </section>
        <footer className="mt-6 flex flex-wrap justify-between gap-2 text-[10px] text-slate-600"><span>Centro PCM · Preparação local de manutenção</span><span>Dados BMA / SQLite · Sem publicação automática</span></footer>
        {teamOpen && <LaborPlanningModal inicio={inicio} fim={fim} setores={sectors} saved={savedTeam}
          onLaborUpdate={(result) => { setLabor(result); setCapacityError(""); }}
          onClose={() => setTeamOpen(false)} onSave={(plan) => { setSavedTeam(plan); setTeamOpen(false); setMessage(`Equipe salva: ${plan.executantes.length} executante(s). Capacidade recalculada para o período.`); }} />}
      </main>
    </>
  );
}
