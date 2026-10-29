import { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowRight, Boxes, CalendarDays, Check, CheckCircle2,
  ChevronRight, ClipboardCheck, Clock3, Factory, Gauge, Layers3, LockKeyhole, PackageCheck,
  Play, ShieldCheck, Sparkles, UsersRound, Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { CalendarioTurnos, OrdemTrabalho, PlanejamentoEquipe } from "@/services/api";
import type { PcmData } from "@/utils/pcmDashboard";
import { formatNumber } from "@/utils/pcmDashboard";
import { PcmCharts, PcmTemporal } from "@/components/PcmVisualizations";
import PlanningDateInput from "@/components/PlanningDateInput";

type Props = {
  data: PcmData; orders: OrdemTrabalho[]; inicio: string; fim: string;
  calendario: CalendarioTurnos | null;
  setInicio: (value: string) => void; setFim: (value: string) => void;
  canPlan: boolean; canDefineTeam: boolean; teamLoading: boolean; teamError: string;
  loading: boolean; savedTeam: PlanejamentoEquipe | null;
  mode: "pm" | "corretiva"; onMode: (mode: "pm" | "corretiva") => void;
  onTeam: () => void; dataError: string;
  onPlan: (mode: "pm" | "corretiva") => void;
  onExport: (mode: "pm" | "corretiva") => void;
  busy: boolean;
};
const steps = [
  { label: "Período", icon: CalendarDays }, { label: "Equipe", icon: UsersRound },
  { label: "Recursos", icon: Wrench }, { label: "Materiais", icon: Boxes },
  { label: "Ordens", icon: Layers3 }, { label: "Simulação", icon: Play },
  { label: "Aprovação", icon: ShieldCheck }, { label: "Publicação", icon: PackageCheck },
];
const inputClass = "h-11 w-full min-w-0 rounded-lg border border-white/15 bg-[#081729] px-3 text-sm text-white [color-scheme:dark] focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-400/20 disabled:opacity-40";

export default function PcmCommandCenter(props: Props) {
  const { data, orders, inicio, fim, canPlan, canDefineTeam, loading } = props;
  const equipes = [...new Set((props.savedTeam?.executantes ?? [])
    .filter((member) => member.jornada === "equipe" && member.equipe)
    .map((member) => member.equipe as number))];
  const [step, setStep] = useState(0);
  const [scenario, setScenario] = useState(100);
  const [personSearch, setPersonSearch] = useState("");
  const [exportMessage, setExportMessage] = useState("");
  const reducedMotion = useReducedMotion();
  const completed = Number(canDefineTeam) + Number(canPlan);
  const totalKnown = !loading && !props.dataError;
  const hhReady = canPlan && data.validTeam;
  const simulated = hhReady && data.availableHours !== null ? data.availableHours * scenario / 100 : null;
  const overloadDays = data.daily.filter((day) => day.capacity !== null && day.demand > day.capacity);
  const pendingPeople = data.team.filter((row) => !row.hours).length;
  const insights = [
    ...(overloadDays.length ? [{
      title: `${overloadDays.length} dia(s) com pressão de carga`,
      detail: "O HH das OTs com início programado supera a capacidade base nesses dias. Revise a distribuição antes de alocar.", tone: "warning",
    }] : []),
    ...(data.missingHours ? [{
      title: `${data.missingHours} OTs sem estimativa de mão de obra`,
      detail: "A demanda de HH está incompleta. Prepare essas ordens antes de avaliar o backlog.", tone: "warning",
    }] : []),
    ...(data.grouping && data.grouping[1] > 1 ? [{
      title: `Agrupamento em ${data.grouping[0]}`,
      detail: `${data.grouping[1]} OTs compartilham este local. Avalie agrupar intervenções, após revisar recursos e restrições.`, tone: "info",
    }] : []),
    ...(!canPlan ? [{ title: "Capacidade ainda não confirmada", detail: "Defina e salve a equipe para o período. A disponibilidade não é inferida do cadastro ativo.", tone: "info" }] : []),
    ...(pendingPeople ? [{ title: `${pendingPeople} executante(s) com pendências`, detail: "Revise cadastro ativo, especialidade e configuração de disponibilidade.", tone: "warning" }] : []),
  ];
  function exportSnapshot() {
    const lines = [
      ["Centro PCM — resumo local, não publicado no BMA"],
      ["Início", inicio], ["Fim", fim], ["OTs abertas", String(data.pending.length)],
      ["HH necessário conhecido", String(data.neededHours)], ["OTs sem HH", String(data.missingHours)],
      ["HH disponível", hhReady ? String(data.availableHours) : "Não disponível"],
      [], ["Matrícula", "Nome", "Função", "HH disponível"],
      ...data.team.map((row) => [row.member.matricula, row.person?.nome ?? "", row.craft?.descricao ?? row.member.funcao, row.hours ? String(row.hours.horas) : "Pendente"]),
    ];
    const csv = "\uFEFF" + lines.map((line) => line.map((value) => `"${value.replace(/"/g, '""').replace(/^[=+@\t\r-]/, "'$&")}"`).join(";")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `resumo-pcm-${inicio || "sem-periodo"}.csv`; anchor.click();
    URL.revokeObjectURL(url);
    setExportMessage("Resumo local exportado. Nenhuma informação foi publicada no BMA.");
  }
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
        <nav aria-label="Etapas do planejamento" className="overflow-x-auto p-4">
          <ol className="flex min-w-[760px] items-start">
            {steps.map((item, index) => {
              const done = index === 0 ? canDefineTeam : index === 1 ? canPlan : false;
              const Icon = item.icon;
              return <li key={item.label} className="relative flex-1">
                {index < 7 && <span aria-hidden="true" className={`absolute left-1/2 top-4 h-px w-full ${done ? "bg-sky-400/40" : "bg-white/10"}`} />}
                <button type="button" onClick={() => setStep(index)} aria-current={step === index ? "step" : undefined}
                  className={`relative flex w-full flex-col items-center gap-2 rounded-lg px-1 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 ${step === index ? "text-white" : "text-slate-500 hover:text-slate-300"}`}>
                  <span className={`flex h-8 w-8 items-center justify-center rounded-lg border ${done ? "border-emerald-400/30 bg-[#0b2830] text-emerald-300" : step === index ? "border-sky-400/50 bg-[#123653] text-sky-300" : "border-white/10 bg-[#0b1a2e]"}`}>
                    {done ? <Check size={16} /> : <Icon size={15} />}
                  </span>
                  <span>{index + 1}. {item.label}</span>
                  <span className="text-[9px] text-slate-500">{done ? "Configurado" : index > 1 && index !== 4 && index !== 5 ? "A integrar" : "A preparar"}</span>
                </button>
              </li>;
            })}
          </ol>
        </nav>
        <div className="flex items-center gap-3 border-t border-white/5 px-5 py-2.5">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/5" role="progressbar" aria-label="Etapas configuradas" aria-valuenow={completed} aria-valuemin={0} aria-valuemax={8}>
            <div className="h-full rounded-full bg-sky-400 transition-all" style={{ width: `${completed / 8 * 100}%` }} />
          </div>
          <span className="text-[10px] text-slate-500">{completed}/8 etapas · preparação local</span>
        </div>
      </div>

      <section aria-label="Resumo executivo" className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
        {([
          { title: "Ordens no período", value: totalKnown ? formatNumber(data.pending.length) : "—", unit: "OTs", note: data.periodFilterActive ? `${data.sectorPending.length - data.pending.length} fora do intervalo` : "Defina um período válido", icon: ClipboardCheck, color: "text-sky-300" },
          { title: "HH disponível", value: hhReady ? formatNumber(data.availableHours) : "—", unit: "h", note: hhReady ? "Equipe salva · período atual" : "Defina a mão de obra", icon: UsersRound, color: "text-emerald-300" },
          { title: "HH necessário", value: totalKnown ? formatNumber(data.neededHours) : "—", unit: "h", note: data.missingHours ? `${data.missingHours} OTs do período sem HH · soma parcial` : "Estimativa das OTs no período", icon: Clock3, color: "text-amber-300" },
          { title: "Backlog estimado", value: hhReady && totalKnown ? formatNumber(data.backlogDays) : "—", unit: "dias", note: "HH carteira ÷ cap. média/dia civil", icon: Layers3, color: "text-violet-300" },
          { title: "Disponibilidade da equipe", value: hhReady ? formatNumber(data.availability) : "—", unit: "%", note: "Selecionados ÷ efetivo elegível", icon: Activity, color: "text-sky-300" },
          { title: "Assertividade", value: "—", unit: "", note: "Requer histórico previsto × realizado", icon: Gauge, color: "text-slate-400" },
        ] satisfies { title: string; value: string; unit: string; note: string; icon: LucideIcon; color: string }[]).map((metric, index) => {
          const Icon = metric.icon;
          return <motion.article key={metric.title} initial={reducedMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: index * 0.03 }} className="pcm-panel min-w-0 p-4">
            <div className="mb-4 flex items-center justify-between gap-2"><p className="text-xs font-medium text-slate-400">{metric.title}</p><Icon size={16} className={`shrink-0 ${metric.color}`} /></div>
            <p className="whitespace-nowrap text-2xl font-semibold tracking-tight text-white xl:text-3xl">{metric.value}<span className="ml-1 text-xs font-normal text-slate-500">{metric.unit}</span></p>
            <p className="mt-2 text-[10px] leading-relaxed text-slate-500">{metric.note}</p>
          </motion.article>;
        })}
      </section>

      <section className="pcm-panel p-5" aria-label="Configuração do planejamento">
        <div className="grid gap-5 lg:grid-cols-[1.3fr_1fr_1fr] lg:items-end">
          <div>
            <h2 className="pcm-title"><CalendarDays size={17} /> 01 · Horizonte de execução</h2>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="min-w-0 text-xs text-slate-400">Início do planejamento
                <PlanningDateInput aria-label="Início do planejamento" value={inicio} calendario={props.calendario} equipes={equipes} disabled={props.teamLoading || !!props.teamError} onChange={props.setInicio} className={`${inputClass} mt-2`} />
              </label>
              <label className="min-w-0 text-xs text-slate-400">Fim do planejamento
                <PlanningDateInput aria-label="Fim do planejamento" value={fim} min={inicio || undefined} calendario={props.calendario} equipes={equipes} disabled={props.teamLoading || !!props.teamError} onChange={props.setFim} className={`${inputClass} mt-2`} />
              </label>
            </div>
          </div>
          <div>
            <h2 className="pcm-title"><UsersRound size={17} /> 02 · Capacidade da equipe</h2>
            <p className="mb-3 mt-2 text-xs text-slate-500">{canPlan ? `${props.savedTeam?.executantes.length} executante(s) salvos para o período.` : "Selecione executantes, funções e escalas."}</p>
            <button type="button" disabled={!canDefineTeam} onClick={props.onTeam} className="pcm-primary-button w-full">
              <UsersRound size={16} /> {canPlan ? "Revisar Mão de Obra" : "Definir Mão de Obra"} <ChevronRight size={16} />
            </button>
          </div>
          <div className="rounded-lg border border-sky-400/10 bg-sky-400/5 p-3 text-xs leading-relaxed text-slate-400">
            <p className="mb-1 flex items-center gap-2 font-medium text-sky-300"><ShieldCheck size={14} /> Planejamento com rastreabilidade</p>
            {canPlan ? "Equipe e período persistidos localmente. Alterações de datas exigem revisar e salvar a capacidade." : "Defina um período e salve ao menos um executante para liberar as carteiras preventiva e corretiva."}
          </div>
        </div>
      </section>
      <section aria-label="Ordens incluídas no planejamento" className="rounded-xl border border-sky-400/20 bg-sky-400/5 px-4 py-3">
        {data.periodFilterActive ? <>
          <p className="text-sm font-semibold text-sky-100">
            {data.pending.length} OT(s) na visão de planejamento · {inicio.split("-").reverse().join("/")} a {fim.split("-").reverse().join("/")}
            <span className="ml-2 font-normal text-slate-400">· {data.sectorPending.length - data.pending.length} fora do período</span>
          </p>
          <p className="mt-1 text-xs leading-relaxed text-slate-400">
            O período inclui OTs cuja data-alvo de início/término ou início/término programado esteja no intervalo, além de ordens cujo intervalo de datas atravesse o horizonte.
            Essa restrição de datas vale para a preventiva. A corretiva é uma carteira aberta: inclui as OTs tipo E dos setores selecionados com status PREPARED e Início planejado em branco, ou com status WFSCH/WSCH.
          </p>
        </> : <p className="text-sm text-amber-200">Informe um período de início e término válido para selecionar as OTs que serão consideradas no planejamento.</p>}
      </section>

      {step > 1 && step !== 4 && <section className="pcm-panel border-sky-400/20 p-5" aria-label={`Etapa ${steps[step].label}`}>
        <h2 className="pcm-title">{steps[step].label}</h2>
        {step === 5 ? <>
          <p className="pcm-caption">Simulação agregada de capacidade, sem alterar datas, equipe ou OTs.</p>
          <label className="mt-4 flex flex-wrap items-center gap-4 text-sm">
            Capacidade considerada: {scenario}%
            <input type="range" min="0" max="150" step="5" value={scenario} disabled={!hhReady}
              onChange={(event) => setScenario(Number(event.target.value))} aria-label="Percentual de capacidade na simulação" className="w-56 accent-sky-400" />
          </label>
          <p className="mt-3 text-sm text-slate-300">{formatNumber(simulated)} h simuladas · {formatNumber(data.neededHours)} h conhecidas da carteira · saldo {formatNumber(simulated === null ? null : simulated - data.neededHours)} h.</p>
          <p className="mt-2 text-xs text-amber-300">Comparação global, não escalonamento por especialidade ou OT. {data.missingHours} OTs sem estimativa. Recursos, materiais e aprovações não são validados nesta simulação.</p>
        </> : <>
          <p className="mt-3 text-sm leading-relaxed text-slate-400">
            {step === 2 && "Equipamentos, locais e planos de trabalho estão nos detalhes das OTs. Na bancada, prepare duração, pessoas e especialidade e confira os recursos. Ferramentas e habilitações especiais não são validadas automaticamente."}
            {step === 3 && "Materiais previstos, saldo de estoque, reservas e requisições ainda não estão integrados. A ausência de dados não significa que os materiais estejam disponíveis."}
            {step === 6 && "A bancada permite revisar PMs e corretivas e confirmar um plano local com histórico. Isso não substitui aprovação corporativa autenticada, permissões ou liberação operacional."}
            {step === 7 && "Publicação no BMA ainda não está implementada. Você pode exportar um resumo local para conferência; isso não altera as ordens nem publica programação."}
          </p>
          {step === 7 && <button type="button" disabled={!canPlan || !totalKnown} onClick={exportSnapshot} className="pcm-small-button mt-4"><ArrowDownToLine size={14} /> Exportar resumo local</button>}
        </>}
        {exportMessage && <p role="status" className="mt-3 text-xs text-emerald-300">{exportMessage}</p>}
      </section>}

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_300px] 2xl:grid-cols-[minmax(0,1fr)_330px]">
        <div className="min-w-0 space-y-5">
          <section className="grid gap-4 md:grid-cols-2" aria-label="Carteiras de planejamento">
            {([{ mode: "pm", title: "Planejamento Preventivo", subtitle: "PM · tipos I e S", portfolio: data.pm, icon: ClipboardCheck, color: "text-sky-300" },
              { mode: "corretiva", title: "Planejamento Corretivo", subtitle: "Correção · tipo E", portfolio: data.corrective, icon: Wrench, color: "text-amber-300" }] as const).map((item) => {
              const Icon = item.icon;
              return <article key={item.mode} className={`pcm-panel p-5 transition ${canPlan && props.mode === item.mode ? "border-sky-400/40 ring-1 ring-sky-400/10" : ""}`}>
                <div className="flex items-center gap-3"><span className={`rounded-xl bg-white/5 p-2.5 ${item.color}`}><Icon size={21} /></span><div><p className="text-[10px] uppercase tracking-widest text-slate-500">{item.subtitle}</p><h2 className="mt-1 text-sm font-semibold text-white">{item.title}</h2></div></div>
                <div className="my-5 grid grid-cols-3 gap-3">
                  {[["OTs", totalKnown ? formatNumber(item.portfolio.count) : "—"], ["HH estimado", totalKnown ? formatNumber(item.portfolio.hours) : "—"], ["Equipamentos", totalKnown ? formatNumber(item.portfolio.assets) : "—"]].map(([label, value]) =>
                    <div key={label}><p className="text-xl font-semibold text-white">{value}</p><p className="mt-1 text-[10px] text-slate-500">{label}</p></div>)}
                </div>
                <div className="mb-4 space-y-1 border-t border-white/5 pt-3 text-[11px] text-slate-500">
                  <p>{item.mode === "pm" ? "Criticidade: não coletada · descrição deve começar por PM" : "Carteira aberta completa · sem filtro de data-alvo"}</p>
                  {item.mode === "pm" && <p>PM1 Segurança · PM2 Qualidade · PM3 Manutenção · {data.pmExcluded} OT(s) I/S fora do padrão · {data.pmAlreadyPlannedExcluded} planejada(s)/parcial(is) · {data.pmUnverifiedExcluded} sem verificação</p>}
                  <p>{item.portfolio.missingHours} OTs sem HH · {item.portfolio.missingAssets} sem equipamento informado</p>
                </div>
                <div className="mb-3 flex flex-wrap gap-2">
                  <button type="button" disabled={!totalKnown || props.busy || (item.mode === "pm" && (!inicio || !fim))} onClick={() => props.onExport(item.mode)} className="pcm-small-button"><ArrowDownToLine size={14} /> Exportar Excel filtrado</button>
                  <button type="button" onClick={() => props.onMode(item.mode)} className="pcm-small-button">Ver carteira</button>
                </div>
                <button type="button" disabled={!canPlan || props.busy}
                  onClick={() => props.onPlan(item.mode)}
                  className={`flex min-h-11 w-full items-center justify-between rounded-lg border px-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/5 disabled:text-slate-500 ${canPlan && props.mode === item.mode ? "border-sky-400/30 bg-sky-400/15 text-sky-300" : "border-white/15 text-slate-300 hover:bg-white/5"}`}>
                  {item.mode === "pm" ? "Planejar PM" : "Planejar Corretiva"}
                  {canPlan ? <ArrowRight size={16} /> : <LockKeyhole size={14} />}
                </button>
              </article>;
            })}
          </section>
          <PcmTemporal data={data} inicio={inicio} fim={fim} />
          <PcmCharts data={data} />
          <section className="pcm-panel overflow-hidden" id="pcm-team">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-5">
              <div><h2 className="pcm-title"><UsersRound size={17} /> Capacidade & mão de obra</h2><p className="pcm-caption">Equipe definida para o planejamento · não inclui alocação por OT.</p></div>
              <button type="button" disabled={!canDefineTeam} onClick={props.onTeam} className="pcm-small-button">Editar equipe</button>
            </div>
            <div className="p-5">
              <input type="search" aria-label="Buscar na equipe planejada" placeholder="Buscar executante ou especialidade..." value={personSearch}
                onChange={(event) => setPersonSearch(event.target.value)} className={`${inputClass} mb-4 max-w-md`} />
              <div className="overflow-x-auto">
                <table className="w-full whitespace-nowrap text-left text-xs">
                  <thead className="border-b border-white/10 text-[10px] uppercase tracking-wider text-slate-500"><tr>
                    {["Executante", "Especialidade", "Turno / escala", "Disponibilidade", "HH disponível", "HH comprometido"].map((label) => <th key={label} scope="col" className="px-3 py-3 font-medium">{label}</th>)}
                  </tr></thead>
                  <tbody className="divide-y divide-white/5">
                    {data.team.filter((row) => `${row.person?.nome ?? ""} ${row.member.matricula} ${row.craft?.descricao ?? ""}`.toLocaleLowerCase("pt-BR").includes(personSearch.toLocaleLowerCase("pt-BR"))).map((row) =>
                      <tr key={`${row.member.orgid}-${row.member.matricula}`} className="text-slate-300">
                        <td className="px-3 py-4"><p className="font-medium">{row.person?.nome || row.member.matricula}</p><p className="mt-1 text-[10px] text-slate-500">{row.member.matricula}</p></td>
                        <td className="px-3 py-4">{row.craft?.descricao || row.member.funcao}</td>
                        <td className="px-3 py-4">
                          {row.member.jornada === "equipe" ? `Equipe ${row.member.equipe}` : row.member.jornada === "adm" ? "Administrativo" : row.member.jornada}
                          <span className="block text-xs text-slate-500">{row.member.capacidade === "dias_8h" ? "8 h por dia disponível · turno informativo" : row.member.capacidade === "dias_6h" ? "Regra anterior: 6 h por dia · revise e salve" : "Cálculo anterior por escala · revise e salve"}</span>
                        </td>
                        <td className="px-3 py-4"><span className={row.hours ? "text-emerald-300" : "text-amber-300"}>{row.hours ? `${row.hours.dias} dias configurados` : "Revisão necessária"}</span></td>
                        <td className="px-3 py-4 font-semibold">{formatNumber(row.hours?.horas ?? null)} h</td>
                        <td className="min-w-36 px-3 py-4 text-slate-500"><span>Consultar bancada integrada</span><p className="mt-1 text-[10px]">PM + corretiva e saldo por dia</p></td>
                      </tr>)}
                  </tbody>
                </table>
                {!data.team.length && <p className="py-8 text-center text-sm text-slate-500">Defina a equipe para visualizar executantes, especialidades e capacidade.</p>}
              </div>
              <p className="mt-4 text-[10px] text-slate-500">Barras de ocupação aguardam vínculo executante × OT. Não alocado não equivale a 0% ocupado.</p>
            </div>
          </section>
        </div>
        <aside className="space-y-4 xl:sticky xl:top-5" aria-label="Inteligência operacional">
          <section className="pcm-panel border-violet-400/15 p-5">
            <h2 className="pcm-title"><Sparkles size={17} className="text-violet-300" /> Insights da IA</h2>
            <p className="mt-2 text-[10px] leading-relaxed text-slate-500">Análise automática por regras locais. Sem modelo de IA conectado e sem envio de dados para serviços externos.</p>
            <div className="mt-5 space-y-4">
              {!totalKnown ? <p className="text-xs text-slate-400">Aguardando dados válidos da carteira.</p> : insights.map((item) => <article key={item.title} className="border-b border-white/5 pb-4 last:border-0 last:pb-0">
                <p className={`mb-2 flex items-start gap-2 text-xs font-semibold ${item.tone === "warning" ? "text-amber-300" : "text-sky-300"}`}><AlertTriangle size={14} className="mt-0.5 shrink-0" />{item.title}</p>
                <p className="text-xs leading-relaxed text-slate-400">{item.detail}</p>
              </article>)}
              {totalKnown && !insights.length && <p className="text-xs text-slate-400">Nenhuma regra local acionada. Isso não garante ausência de restrições operacionais.</p>}
            </div>
          </section>
          <section className="pcm-panel p-5">
            <h2 className="pcm-title"><ShieldCheck size={17} /> Prontidão & qualidade</h2>
            <ul className="mt-4 space-y-3 text-xs">
              {[
                { label: "Período configurado", ready: canDefineTeam }, { label: "Equipe salva", ready: canPlan },
                { label: "Estimativas completas", ready: totalKnown && orders.length > 0 && !data.missingHours },
                { label: "Materiais / recursos", ready: false }, { label: "Criticidade / riscos", ready: false },
                { label: "Aprovação / publicação", ready: false },
              ].map((item) => <li key={item.label} className="flex items-center justify-between gap-2 text-slate-400"><span>{item.label}</span>{item.ready ? <CheckCircle2 size={15} className="text-emerald-300" /> : <span className="text-[10px] text-slate-500">Pendente</span>}</li>)}
            </ul>
          </section>
          <section className="pcm-panel p-5">
            <h2 className="pcm-title"><Layers3 size={17} /> Distribuição da carteira</h2>
            <ul className="mt-4 space-y-3">
              {data.types.map((row) => <li key={row.name}>
                <div className="mb-1.5 flex justify-between text-xs"><span className="text-slate-400">Tipo {row.name}</span><span className="text-slate-200">{row.count} OTs</span></div>
                <div className="h-1.5 rounded-full bg-white/5"><div className="h-full rounded-full bg-sky-400/70" style={{ width: `${data.pending.length ? row.count / data.pending.length * 100 : 0}%` }} /></div>
              </li>)}
            </ul>
          </section>
          <section className="rounded-xl border border-amber-400/10 bg-amber-400/[0.03] p-4 text-[11px] leading-relaxed text-slate-500">
            <p className="mb-2 flex items-center gap-2 font-semibold text-amber-300"><AlertTriangle size={14} /> Limites da visão</p>
            Carteira = OTs abertas coletadas do setor, não apenas as que vencem no período. Datas e recursos precisam ser revisados pelo planejador. Nenhuma alteração é enviada ao BMA.
          </section>
        </aside>
      </div>
    </div>
  );
}
