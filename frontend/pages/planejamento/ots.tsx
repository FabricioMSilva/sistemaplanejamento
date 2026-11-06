import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, LoaderCircle } from "lucide-react";
import LaborPlanningModal from "@/components/LaborPlanningModal";
import PcmCommandCenter, { PcmPlanningControls } from "@/components/PcmCommandCenter";
import PlanningWorkflowSteps from "@/components/PlanningWorkflowSteps";
import { createWorkPlan, getBmaPageMonitor, startBmaPreparationCollection, stopBmaPageMonitor, type BmaPageMonitor } from "@/services/pcm";
import {
  listarOrdensTrabalho, listarMaoDeObra, listarEspecialidades, listarEquipesSalvas,
  obterCalendarioTurnos, obterEquipe, salvarEquipe,
  type CalendarioTurnos, type EquipeSalva, type Especialidade, type MaoDeObra, type OrdemTrabalho,
  type PlanejamentoEquipe,
} from "@/services/api";
import { configurarDiasDisponiveis, equipeDefinida, periodoValido, reutilizarEquipe } from "@/utils/laborPlanning";
import { buildDashboard, preparationOrders, specialtyPareto } from "@/utils/pcmDashboard";

type PlanejamentoOtsPageProps = { sectors?: string[]; onPlanCreated?: (planId: string) => void };

export default function PlanejamentoOtsPage({ sectors: sectorsProp, onPlanCreated }: PlanejamentoOtsPageProps = {}) {
  const router = useRouter();
  const routeSectors = useMemo(() => {
    const raw = router.query.setor;
    return Array.isArray(raw) ? raw : raw ? [raw] : [];
  }, [router.query.setor]);
  const sectors = sectorsProp ?? routeSectors;
  const [orders, setOrders] = useState<OrdemTrabalho[]>([]);
  const [labor, setLabor] = useState<MaoDeObra | null>(null);
  const [specialtyCatalog, setSpecialtyCatalog] = useState<Especialidade[]>([]);
  const [calendar, setCalendar] = useState<CalendarioTurnos | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [capacityError, setCapacityError] = useState("");
  const [teamError, setTeamError] = useState("");
  const [inicio, setInicio] = useState("");
  const [fim, setFim] = useState("");
  const [confirmedPeriod, setConfirmedPeriod] = useState<{ inicio: string; fim: string } | null>(null);
  const [periodUpdating, setPeriodUpdating] = useState(false);
  const [savedTeam, setSavedTeam] = useState<PlanejamentoEquipe | null>(null);
  const [savedTeams, setSavedTeams] = useState<EquipeSalva[]>([]);
  const [savedTeamsError, setSavedTeamsError] = useState("");
  const [applyingSavedTeam, setApplyingSavedTeam] = useState(false);
  const [teamOpen, setTeamOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [tv, setTv] = useState(false);
  const [loadedScope, setLoadedScope] = useState("");
  const [collectionMonitorId, setCollectionMonitorId] = useState<string | null>(null);
  const [collectionMonitor, setCollectionMonitor] = useState<BmaPageMonitor | null>(null);
  const [collectionStarting, setCollectionStarting] = useState(false);
  const [collectionError, setCollectionError] = useState("");
  const [creatingPlan, setCreatingPlan] = useState(false);
  const scope = JSON.stringify(sectors);
  const specialtyOrgIds = useMemo(() => [...new Set([
    ...(labor?.profissionais ?? []).map((person) => person.orgid),
    ...(savedTeam?.executantes ?? []).map((member) => member.orgid),
  ])].sort(), [labor, savedTeam]);

  useEffect(() => {
    if (!specialtyOrgIds.length) {
      setSpecialtyCatalog([]);
      return;
    }
    let cancelled = false;
    Promise.all(specialtyOrgIds.map(listarEspecialidades)).then((catalogs) => {
      if (!cancelled) setSpecialtyCatalog(catalogs.flat());
    }).catch(() => {
      if (!cancelled) setSpecialtyCatalog([]);
    });
    return () => { cancelled = true; };
  }, [specialtyOrgIds]);

  useEffect(() => {
    if (!router.isReady) return;
    let cancelled = false;
    setLoading(true); setError(""); setTeamError(""); setCapacityError("");
    setTeamOpen(false); setSavedTeam(null); setSavedTeams([]); setSavedTeamsError("");
    setLabor(null); setCalendar(null);
    setOrders([]); setInicio(""); setFim(""); setConfirmedPeriod(null); setMessage("");
    setLoadedScope("");
    if (!sectors.length) {
      setError("Nenhum setor informado. Volte à coleta e selecione o setor de manutenção.");
      setLoading(false);
      return;
    }
    Promise.allSettled([
      listarOrdensTrabalho(sectors), obterEquipe(sectors), listarEquipesSalvas(sectors),
      listarMaoDeObra(sectors), obterCalendarioTurnos(),
    ]).then(([orderResult, teamResult, savedTeamsResult, laborResult, calendarResult]) => {
      if (cancelled) return;
      const explain = (reason: unknown) => reason instanceof Error ? reason.message : "Falha de comunicação com a API.";
      if (orderResult.status === "fulfilled") setOrders(orderResult.value);
      else setError(`Carteira: ${explain(orderResult.reason)}`);
      if (teamResult.status === "fulfilled") {
        setSavedTeam(teamResult.value);
        setInicio(teamResult.value?.inicio ?? "");
        setFim(teamResult.value?.fim ?? "");
        setConfirmedPeriod(teamResult.value ? { inicio: teamResult.value.inicio, fim: teamResult.value.fim } : null);
      } else setTeamError(`Equipe salva: ${explain(teamResult.reason)}`);
      if (savedTeamsResult.status === "fulfilled") setSavedTeams(savedTeamsResult.value);
      else setSavedTeamsError(`Equipes salvas: ${explain(savedTeamsResult.reason)}`);
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

  useEffect(() => {
    const toggleTv = () => setTv((current) => !current);
    const reloadData = () => setAttempt((current) => current + 1);
    window.addEventListener("pcm:toggle-tv", toggleTv);
    window.addEventListener("pcm:reload-data", reloadData);
    return () => {
      window.removeEventListener("pcm:toggle-tv", toggleTv);
      window.removeEventListener("pcm:reload-data", reloadData);
    };
  }, []);

  useEffect(() => {
    if (!collectionMonitorId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current = await getBmaPageMonitor(collectionMonitorId);
        if (cancelled) return;
        setCollectionMonitor(current);
        if (["completed", "failed", "stopped"].includes(current.status)) {
          try {
            const refreshedOrders = await listarOrdensTrabalho(sectors);
            if (!cancelled) setOrders(refreshedOrders);
          } catch (reason) {
            if (!cancelled) setCollectionError(reason instanceof Error ? reason.message : "Falha ao atualizar a carteira.");
          }
          return;
        }
      } catch (reason) {
        if (cancelled) return;
        const detail = reason instanceof Error ? reason.message : "Falha ao consultar o progresso da coleta.";
        if (detail === "Monitor BMA não encontrado.") {
          setCollectionMonitorId(null);
          setCollectionMonitor(null);
          setCollectionError("O monitor da coleta expirou ou foi reiniciado. A carteira permanece disponível para uma nova coleta.");
          return;
        }
        setCollectionError(detail);
      }
      if (!cancelled) timer = setTimeout(poll, 1200);
    };
    timer = setTimeout(poll, 800);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [collectionMonitorId, sectors]);

  const periodApplied = !!confirmedPeriod && periodoValido(inicio, fim)
    && confirmedPeriod.inicio === inicio && confirmedPeriod.fim === fim;
  const activePeriod = confirmedPeriod && periodoValido(confirmedPeriod.inicio, confirmedPeriod.fim) ? confirmedPeriod : null;
  const samePeriod = !loading && loadedScope === scope && !!activePeriod
    && equipeDefinida(savedTeam, activePeriod.inicio, activePeriod.fim, sectors);
  const data = useMemo(() => buildDashboard(orders, samePeriod ? savedTeam : null, labor, calendar, activePeriod, true),
    [orders, samePeriod, savedTeam, labor, calendar, activePeriod]);
  const preparationQueue = useMemo(() => preparationOrders(orders, activePeriod), [orders, activePeriod]);
  const specialtyNames = useMemo(() => new Map(
    specialtyCatalog.map((craft) => [craft.codigo, craft.descricao] as const),
  ), [specialtyCatalog]);
  for (const row of data.team) {
    if (row.craft?.descricao) specialtyNames.set(row.member.funcao, row.craft.descricao);
  }
  const availableBySpecialty = useMemo(() => {
    const hours = new Map<string, number>();
    for (const row of data.team) {
      if (row.hours) hours.set(row.member.funcao, (hours.get(row.member.funcao) ?? 0) + row.hours.horas);
    }
    return hours;
  }, [data.team]);
  const specialties = useMemo(() => specialtyPareto(
    data.pending, "all", activePeriod, specialtyNames, availableBySpecialty, data.validTeam,
  ), [data.pending, activePeriod, specialtyNames, availableBySpecialty, data.validTeam]);
  const canPlan = periodApplied && samePeriod && !teamError && !capacityError && data.validTeam;
  const canDefineTeam = periodApplied && !loading && !teamError && sectors.length > 0 && periodoValido(inicio, fim);
  const latestSync = orders.reduce((latest, order) => order.sincronizado_em > latest ? order.sincronizado_em : latest, "");
  const syncDate = latestSync ? new Date(latestSync) : null;
  async function confirmPeriod() {
    if (!periodoValido(inicio, fim) || !sectors.length || periodUpdating) return;
    const requestedPeriod = { inicio, fim };
    setPeriodUpdating(true);
    setError("");
    setMessage("");
    try {
      const refreshedOrders = await listarOrdensTrabalho(sectors);
      setOrders(refreshedOrders);
      setConfirmedPeriod(requestedPeriod);
      setMessage("Período confirmado. A quantidade de OTs foi atualizada para a carteira local.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao atualizar as OTs do período.");
    } finally { setPeriodUpdating(false); }
  }
  async function applySavedTeam(team: EquipeSalva) {
    if (!periodApplied || applyingSavedTeam) return;
    setApplyingSavedTeam(true);
    setError("");
    setMessage("");
    try {
      const plan: PlanejamentoEquipe = {
        ...team.planejamento,
        setores: sectors,
        inicio,
        fim,
        executantes: reutilizarEquipe(team.planejamento, inicio, fim)
          .map((member) => {
            const configured = configurarDiasDisponiveis(member, inicio, fim);
            return { ...configured, jornada: configured.jornada || "adm" };
          }),
      };
      await salvarEquipe(plan);
      setSavedTeam(plan);
      setMessage(`Equipe “${team.nome}” aplicada e salva para o período confirmado.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao aplicar a equipe salva.");
    } finally { setApplyingSavedTeam(false); }
  }
  async function collectPreparation() {
    if (!preparationQueue.length || collectionStarting) return;
    const firstOrder = preparationQueue[0];
    setCollectionStarting(true);
    setCollectionError("");
    try {
      const { monitor_id } = await startBmaPreparationCollection(
        preparationQueue.map(({ siteid, wonum }) => ({ siteid, wonum })),
      );
      setCollectionMonitorId(monitor_id);
      setCollectionMonitor({
        monitor_id,
        status: "starting",
        mode: "preparation_collection",
        inspection_only: true,
        message: `Abrindo o BMA em janela oculta para coletar ${preparationQueue.length} OT(s).`,
        fields: [],
        queue_total: preparationQueue.length,
        current_order_index: 1,
        current_wonum: firstOrder.wonum,
        selected_wonums: preparationQueue.map((order) => order.wonum),
      });
    } catch (reason) {
      setCollectionError(reason instanceof Error ? reason.message : "Falha ao iniciar a coleta da Preparação.");
    } finally { setCollectionStarting(false); }
  }
  async function cancelPreparationCollection() {
    if (!collectionMonitorId) return;
    try {
      setCollectionMonitor(await stopBmaPageMonitor(collectionMonitorId));
    } catch (reason) {
      setCollectionError(reason instanceof Error ? reason.message : "Falha ao cancelar a coleta.");
    }
  }

  async function continueToAllocation() {
    if (!canPlan || creatingPlan) return;
    setCreatingPlan(true);
    setError("");
    try {
      const plan = await createWorkPlan(sectors);
      if (onPlanCreated) onPlanCreated(plan.id);
      else await router.push({ pathname: "/planejamento", query: { etapa: "3", setor: sectors, plano: plan.id } });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao criar o planejamento.");
    } finally {
      setCreatingPlan(false);
    }
  }

  return (
    <>
      <Head><title>Centro de Planejamento | Planning & Scheduling Michelin</title></Head>
      <main className={`pcm-workspace mx-auto min-h-screen px-4 py-6 sm:px-6 lg:px-8 ${tv ? "pcm-tv max-w-[2560px]" : "max-w-[1800px]"}`}>
        <PlanningWorkflowSteps active={2} />
        <header className="mb-6">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <Link href="/planejamento" className="inline-flex items-center gap-2 text-xs font-medium text-slate-400 transition hover:text-white"><ArrowLeft size={14} /> Voltar para a coleta</Link>
          </div>
          <PcmPlanningControls inicio={inicio} fim={fim} calendario={calendar}
            setInicio={(value) => { setInicio(value); setMessage(""); }} setFim={(value) => { setFim(value); setMessage(""); }}
            canPlan={canPlan} canDefineTeam={canDefineTeam} teamLoading={loading} teamError={teamError}
            savedTeam={savedTeam} onTeam={() => setTeamOpen(true)} onConfirmPeriod={confirmPeriod}
            savedTeams={savedTeams} savedTeamsError={savedTeamsError} applyingSavedTeam={applyingSavedTeam}
            onApplySavedTeam={applySavedTeam}
            periodApplied={periodApplied} periodUpdating={periodUpdating} canConfirmPeriod={!loading && !teamError && periodoValido(inicio, fim)}
            orderCount={data.pending.length} />
          <section aria-label="Ordens incluídas no planejamento" className="mt-3 rounded-xl border border-sky-400/20 bg-sky-400/5 px-4 py-3">
            {data.periodFilterActive && activePeriod ? <>
              <p className="text-sm font-semibold text-sky-100">
                {data.pending.length} OT(s) na visão de planejamento · {activePeriod.inicio.split("-").reverse().join("/")} a {activePeriod.fim.split("-").reverse().join("/")}
                <span className="ml-2 font-normal text-slate-400">· {data.sectorPending.length - data.pending.length} fora do período</span>
              </p>
              <p className="mt-1 text-xs leading-relaxed text-slate-400">
                PM e tipo E seguem o mesmo filtro. As datas limite da OT (Não iniciar antes de / Não terminar depois de) precisam cruzar o período; sem esses limites, usamos as datas previstas.
              </p>
              {!periodApplied && <p className="mt-1 text-xs text-amber-200">As datas selecionadas mudaram. Confirme o período para atualizar a quantidade de OTs.</p>}
            </> : <p className="text-sm text-amber-200">Informe as datas e confirme o período para atualizar a quantidade de OTs consideradas no planejamento.</p>}
          </section>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-2">{sectors.map((sector) => <span key={sector} className="pcm-badge text-sky-200">{sector}</span>)}</div>
            <p className="text-[10px] text-slate-500">Coleta de OTs: {syncDate && Number.isFinite(syncDate.getTime()) ? new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" }).format(syncDate) + " (Brasília)" : "não disponível"}</p>
          </div>
        </header>
        {(error || teamError || capacityError) && <div role="alert" className="mb-5 rounded-xl border border-rose-400/20 bg-rose-400/5 p-4 text-sm text-rose-300">
          {[error, teamError, capacityError].filter(Boolean).map((text) => <p key={text}>{text}</p>)}
          <button type="button" onClick={() => setAttempt((current) => current + 1)} className="mt-3 underline">Tentar carregar novamente</button>
        </div>}
        {inicio && fim && !periodoValido(inicio, fim) && <p role="alert" className="mb-4 text-sm text-amber-300">O fim do planejamento deve ser igual ou posterior ao início.</p>}
        {periodApplied && savedTeam && (savedTeam.inicio !== inicio || savedTeam.fim !== fim) && <p className="mb-4 text-sm text-amber-300">Período alterado. Revise e salve a mão de obra para liberar as carteiras.</p>}
        {samePeriod && !loading && !data.validTeam && !capacityError && <p role="alert" className="mb-4 text-sm text-amber-300">Há pendências na equipe salva. Revise o cadastro, as funções e os dias disponíveis para liberar o planejamento.</p>}
        {message && <p role="status" className="mb-4 text-sm text-emerald-300">{message}</p>}
        {loading && <p role="status" className="mb-4 flex items-center gap-2 text-sm text-sky-200"><LoaderCircle size={17} className="animate-spin" /> Carregando carteira, equipe e capacidade. Aguarde antes de continuar.</p>}
        <PcmCommandCenter data={data} canPlan={canPlan} teamLoading={loading} loading={loading} dataError={error} periodApplied={periodApplied}
          specialties={specialties}
          preparationQueueCount={preparationQueue.length} collectionMonitor={collectionMonitor}
          collectionStarting={collectionStarting} collectionError={collectionError}
          onCollectPreparation={collectPreparation} onCancelPreparation={cancelPreparationCollection} />
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[.02] p-4">
          <p className="text-sm text-slate-300">{canPlan ? "Horizonte e equipe prontos. Continue para distribuir a carga." : "Confirme o horizonte e salve uma equipe válida para liberar a próxima etapa."}</p>
          <button type="button" className="pcm-primary-button" disabled={!canPlan || creatingPlan || loading} onClick={() => void continueToAllocation()}>
            {creatingPlan ? <LoaderCircle size={16} className="animate-spin" /> : <ArrowRight size={16} />}
            {creatingPlan ? "Preparando planejamento..." : "Continuar para distribuição"}
          </button>
        </div>
        {teamOpen && <LaborPlanningModal inicio={inicio} fim={fim} setores={sectors} saved={savedTeam}
          onLaborUpdate={(result) => { setLabor(result); setCapacityError(""); }}
          onClose={() => setTeamOpen(false)} onSave={(plan) => { setSavedTeam(plan); setTeamOpen(false); setMessage(`Equipe salva: ${plan.executantes.length} executante(s). Capacidade recalculada para o período.`); }} />}
      </main>
    </>
  );
}
