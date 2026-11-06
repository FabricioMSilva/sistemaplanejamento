import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  Activity, CalendarDays, Check, ChevronRight, ClipboardCheck, Clock3, Factory, Gauge, Layers3,
  RefreshCw, ScanSearch, ShieldCheck, Square, UsersRound,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { CalendarioTurnos, EquipeSalva, PlanejamentoEquipe } from "@/services/api";
import type { BmaPageMonitor } from "@/services/pcm";
import type { PcmData } from "@/utils/pcmDashboard";
import { formatNumber } from "@/utils/pcmDashboard";
import ParetoChart, { type ParetoItem } from "@/components/ParetoChart";
import PlanningDateInput from "@/components/PlanningDateInput";

type Props = {
  data: PcmData; canPlan: boolean; teamLoading: boolean; loading: boolean; dataError: string; periodApplied: boolean;
  specialties: ParetoItem[];
  preparationQueueCount: number;
  collectionMonitor: BmaPageMonitor | null;
  collectionStarting: boolean;
  collectionError: string;
  onCollectPreparation: () => void;
  onCancelPreparation: () => void;
};
const inputClass = "h-11 w-full min-w-0 rounded-lg border border-white/15 bg-[#081729] px-3 text-sm text-white focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-400/20 disabled:opacity-40";

type PlanningControlsProps = {
  inicio: string; fim: string; calendario: CalendarioTurnos | null;
  setInicio: (value: string) => void; setFim: (value: string) => void;
  canPlan: boolean; canDefineTeam: boolean; teamLoading: boolean; teamError: string;
  savedTeam: PlanejamentoEquipe | null; onTeam: () => void; onConfirmPeriod: () => void;
  savedTeams: EquipeSalva[]; savedTeamsError: string; applyingSavedTeam: boolean;
  onApplySavedTeam: (team: EquipeSalva) => void;
  periodApplied: boolean; periodUpdating: boolean; canConfirmPeriod: boolean; orderCount: number;
};

export function PcmPlanningControls(props: PlanningControlsProps) {
  const [selectedSavedTeam, setSelectedSavedTeam] = useState("");
  useEffect(() => { setSelectedSavedTeam(""); }, [props.savedTeams]);
  const teams = [...new Set((props.savedTeam?.executantes ?? [])
    .filter((member) => member.jornada === "equipe" && member.equipe)
    .map((member) => member.equipe as number))];
  const savedTeamsDisabled = !props.periodApplied || props.teamLoading || props.applyingSavedTeam;
  return (
    <section className="pcm-panel p-5" aria-label="Configuração do planejamento">
      <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr_1fr] lg:items-end">
        <div>
          <h2 className="pcm-title"><CalendarDays size={17} /> 01 · Horizonte de execução</h2>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <label className="min-w-0 text-xs text-slate-400">Início do planejamento
              <PlanningDateInput aria-label="Início do planejamento" value={props.inicio} calendario={props.calendario} equipes={teams} disabled={props.teamLoading || !!props.teamError} onChange={props.setInicio} className={`${inputClass} mt-2`} />
            </label>
            <label className="min-w-0 text-xs text-slate-400">Fim do planejamento
              <PlanningDateInput aria-label="Fim do planejamento" value={props.fim} min={props.inicio || undefined} calendario={props.calendario} equipes={teams} disabled={props.teamLoading || !!props.teamError} onChange={props.setFim} className={`${inputClass} mt-2`} />
            </label>
            <div className="col-span-2 flex flex-wrap items-center justify-between gap-3">
              <button type="button" disabled={!props.canConfirmPeriod || props.periodUpdating} onClick={props.onConfirmPeriod} className="pcm-primary-button min-h-10">
                {props.periodUpdating ? <RefreshCw size={15} className="animate-spin" /> : <Check size={15} />}
                {props.periodUpdating ? "Atualizando OTs..." : "Confirmar período"}
              </button>
              <span className="text-[11px] text-slate-500">
                {props.periodApplied ? `${formatNumber(props.orderCount)} OTs no período confirmado` : "Confirme as datas para atualizar a carteira"}
              </span>
            </div>
          </div>
        </div>
        <div>
          <h2 className="pcm-title"><UsersRound size={17} /> 02 · Capacidade da equipe</h2>
          <p className="mb-3 mt-2 text-xs text-slate-500">{props.canPlan ? `${props.savedTeam?.executantes.length} executante(s) salvos para o período.` : "Selecione executantes, funções e escalas."}</p>
          <div className="mb-3 min-w-0">
            <label className="sr-only" htmlFor="saved-team-select">Selecionar equipe salva</label>
            <select id="saved-team-select" aria-label="Selecionar equipe salva" value={selectedSavedTeam}
              onChange={(event) => {
                const teamName = event.target.value;
                setSelectedSavedTeam(teamName);
                const team = props.savedTeams.find((item) => item.nome === teamName);
                if (team) props.onApplySavedTeam(team);
              }} disabled={savedTeamsDisabled || !props.savedTeams.length}
              className="block min-h-10 w-full min-w-0 rounded-md border border-white/15 bg-[#081729] px-3 py-2 text-xs text-white disabled:opacity-50">
              <option value="">{props.savedTeamsError ? "Falha ao carregar equipes" : props.savedTeams.length ? "Selecionar equipe salva" : "Nenhuma equipe salva"}</option>
              {props.savedTeams.map((team) => <option key={team.nome} value={team.nome}>
                {team.nome} · {team.planejamento.executantes.length} executantes
              </option>)}
            </select>
          </div>
          {props.savedTeamsError && <p role="alert" className="mb-2 text-xs text-rose-300">{props.savedTeamsError}</p>}
          <button type="button" disabled={!props.canDefineTeam} onClick={props.onTeam} className="pcm-primary-button w-full">
            <UsersRound size={16} /> {props.canPlan ? "Revisar Mão de Obra" : "Definir Mão de Obra"} <ChevronRight size={16} />
          </button>
        </div>
        <div className="rounded-lg border border-sky-400/10 bg-sky-400/5 p-3 text-xs leading-relaxed text-slate-400">
          <p className="mb-1 flex items-center gap-2 font-medium text-sky-300"><ShieldCheck size={14} /> Planejamento com rastreabilidade</p>
          {props.canPlan ? "Equipe e período persistidos localmente. Alterações de datas exigem revisar e salvar a capacidade." : props.periodApplied ? "Salve ao menos um executante para liberar as carteiras preventiva e corretiva." : "Confirme as datas para atualizar as OTs e liberar a definição da mão de obra."}
        </div>
      </div>
    </section>
  );
}

export default function PcmCommandCenter(props: Props) {
  const { data, canPlan, loading } = props;
  const reducedMotion = useReducedMotion();
  const totalKnown = !loading && !props.dataError;
  const hhReady = canPlan && data.validTeam;
  const collectionMonitor = props.collectionMonitor;
  const collectionActive = !!collectionMonitor && ["starting", "monitoring", "stopping"].includes(collectionMonitor.status);
  const collectionProgress = collectionMonitor?.progress ?? 0;
  return (
    <div className="space-y-5">
      <div className="pcm-panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-sky-400/20 bg-sky-400/10 text-sky-300"><Factory size={22} /></span>
            <div><p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-sky-300">Maintenance intelligence</p><h2 className="text-sm font-semibold text-white">Preparação & planejamento integrado</h2></div>
          </div>
          <span className={`pcm-badge ${canPlan ? "text-emerald-300" : "text-amber-300"}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${canPlan ? "bg-emerald-400" : "bg-amber-400"}`} />
            {props.teamLoading ? "Restaurando configuração" : canPlan ? "Equipe definida · planejamento liberado" : "Preparação pendente"}
          </span>
        </div>
        <section className="border-t border-white/5 p-4" aria-label="Pareto de mão de obra da Preparação">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-slate-400">HH planejado por especialidade comparado à capacidade da equipe salva.</p>
            <div className="flex items-center gap-2">
              <button type="button" disabled={loading || !props.periodApplied || props.collectionStarting || collectionActive || !props.preparationQueueCount}
                onClick={props.onCollectPreparation} className="pcm-primary-button min-h-10">
                {props.collectionStarting || collectionActive ? <RefreshCw size={15} className="animate-spin" /> : <ScanSearch size={15} />}
                {props.collectionStarting || collectionActive ? "Coletando especialidades" : "Coletar Especialidades"}
                {!collectionActive && <span className="text-[10px] opacity-70">{props.preparationQueueCount} OTs</span>}
              </button>
              {collectionActive && <button type="button" onClick={props.onCancelPreparation} className="pcm-small-button" title="Cancelar coleta">
                <Square size={14} /> Cancelar
              </button>}
            </div>
          </div>
          {collectionMonitor && <div className="mt-4 rounded-lg border border-white/10 bg-black/10 p-3" role="status">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-slate-200">{collectionMonitor.message}</span>
              <span className="text-slate-400">{collectionMonitor.current_order_index ?? collectionMonitor.collected_count ?? 0}/{collectionMonitor.queue_total ?? 0} · {collectionProgress}%</span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-label="Progresso da coleta da Preparação" aria-valuenow={collectionProgress} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-emerald-400 transition-all" style={{ width: `${collectionProgress}%` }} />
            </div>
            <p className="mt-2 text-[10px] text-slate-400">{collectionMonitor.collected_count ?? 0} lida(s) · {collectionMonitor.rows_found ?? 0} com linhas · {collectionMonitor.empty_count ?? 0} vazia(s) · {collectionMonitor.failed_count ?? 0} falha(s)</p>
            {!!collectionMonitor.failed_wonums?.length && <details className="mt-2 text-[10px] text-amber-300">
              <summary className="cursor-pointer">Ver detalhes das {collectionMonitor.failed_wonums.length} falhas</summary>
              <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto break-words pl-4">
                {collectionMonitor.failed_wonums.map((failure) => <li key={failure.wonum}>{failure.wonum}: {failure.message}</li>)}
              </ul>
            </details>}
          </div>}
          {props.collectionError && <p role="alert" className="mt-3 text-xs text-rose-300">{props.collectionError}</p>}
          <div className="mt-4 min-w-0">
            <ParetoChart title="HH planejado x HH disponível por especialidade" items={props.specialties} />
          </div>
        </section>
      </div>

      <section className="pcm-panel overflow-hidden" aria-label="Indicadores do período">
        <div className="flex flex-wrap items-end justify-between gap-2 border-b border-white/10 px-5 py-4">
          <div><p className="text-[10px] font-semibold uppercase tracking-wider text-sky-300">Leitura da carteira</p>
            <h2 className="mt-1 text-sm font-semibold text-white">Indicadores do período</h2></div>
          <span className="text-[10px] text-slate-500">{data.periodFilterActive ? "PM e corretivas · filtro de datas aplicado" : "Informe datas para calcular o período"}</span>
        </div>
        <dl className="grid grid-cols-2 sm:grid-cols-3 2xl:grid-cols-6">
        {([
          { title: "Ordens no período", value: totalKnown ? formatNumber(data.pending.length) : "—", unit: "OTs", note: data.periodFilterActive ? `${data.sectorPending.length - data.pending.length} fora do intervalo` : "Defina um período válido", icon: ClipboardCheck, color: "text-sky-300" },
          { title: "HH disponível", value: hhReady ? formatNumber(data.availableHours) : "—", unit: "h", note: hhReady ? "Equipe salva · período atual" : "Defina a mão de obra", icon: UsersRound, color: "text-emerald-300" },
          { title: "HH necessário", value: totalKnown ? formatNumber(data.neededHours) : "—", unit: "h", note: data.missingHours ? `${data.missingHours} OTs do período sem HH · soma parcial` : "Estimativa das OTs no período", icon: Clock3, color: "text-amber-300" },
          { title: "Backlog estimado", value: hhReady && totalKnown ? formatNumber(data.backlogDays) : "—", unit: "dias", note: "HH carteira ÷ cap. média/dia civil", icon: Layers3, color: "text-violet-300" },
          { title: "Disponibilidade da equipe", value: hhReady ? formatNumber(data.availability) : "—", unit: "%", note: "Selecionados ÷ efetivo elegível", icon: Activity, color: "text-sky-300" },
          { title: "Assertividade", value: "—", unit: "", note: "Requer histórico previsto × realizado", icon: Gauge, color: "text-slate-400" },
        ] satisfies { title: string; value: string; unit: string; note: string; icon: LucideIcon; color: string }[]).map((metric, index) => {
          const Icon = metric.icon;
          return <motion.div key={metric.title} initial={reducedMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: index * 0.03 }} className="min-w-0 border-b border-r border-white/10 p-4 last:border-r-0 sm:p-5">
            <div className="mb-3 flex items-center justify-between gap-2"><dt className="text-xs font-medium text-slate-400">{metric.title}</dt><Icon size={16} className={`shrink-0 ${metric.color}`} /></div>
            <dd className="whitespace-nowrap text-2xl font-semibold text-white">{metric.value}<span className="ml-1 text-xs font-normal text-slate-500">{metric.unit}</span></dd>
            <p className="mt-2 min-h-7 text-[10px] leading-relaxed text-slate-500">{metric.note}</p>
          </motion.div>;
        })}
        </dl>
      </section>
    </div>
  );
}
