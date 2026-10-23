import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from "react";
import { ArrowLeft, Download, GripVertical, Save, Sparkles, CheckCircle2, CalendarDays, RefreshCw, Undo2, Pencil, X, SlidersHorizontal, ChevronUp, ChevronDown } from "lucide-react";
import {
  downloadSchedule, getWorkPlan, orderKey, saveWorkPlan, suggestWorkPlan, refreshPlanSpecialties,
  type Allocation, type PlanChange, type Requirement, type WorkPlan,
} from "@/services/pcm";
import { cellText, normalize } from "@/utils/orderFilters";
import { daysBetween, formatNumber } from "@/utils/pcmDashboard";
import { formatPlanningDate } from "@/utils/laborPlanning";
import { activityMode, activityCategory, allocatedDuration, availableDay, conflictingBlocks, dayLoad, distributeBatch, pendingActivity, planningMetrics, specialtyMatches, weeklyBalance, weekStart, proposedDays, scheduleSelectedDays, resequenceWeek } from "@/utils/workPlanning";
import OrderDetails from "@/components/OrderDetails";
import NfeReportButton from "@/components/NfeReportButton";
import { matchesOrderSpecialty, orderSpecialties, plannedLabor } from "@/utils/plannedLabor";

const input = "w-full rounded-lg border border-white/15 bg-[#081729] p-2 text-sm text-white [color-scheme:dark]";
type View = "pm" | "corretiva" | "revisao";
type DragPayload = { ot: string; bloco?: string; origem?: string; lote?: string[] };
const describeError = (error: unknown) => error instanceof Error ? error.message : "Falha na operação de planejamento.";

export default function AllocationPage() {
  const router = useRouter();
  const id = typeof router.query.plano === "string" ? router.query.plano : "";
  const [plan, setPlan] = useState<WorkPlan | null>(null);
  const [view, setView] = useState<View>("pm");
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const [specialtyFilter, setSpecialtyFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [batchPerson, setBatchPerson] = useState("");
  const [limit, setLimit] = useState(60);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [blockId, setBlockId] = useState("");
  const [day, setDay] = useState("");
  const [hours, setHours] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);
  const [executionDays, setExecutionDays] = useState<string[]>([]);
  const [reviewed, setReviewed] = useState(false);
  const [specialtiesRefreshed, setSpecialtiesRefreshed] = useState(false);
  const [dropTarget, setDropTarget] = useState("");
  const [insertionTarget, setInsertionTarget] = useState("");
  const gallery = useRef<HTMLDivElement>(null);
  const handleDrag = useRef<{ payload: DragPayload; x: number; y: number; startX: number; startY: number; moved: boolean } | null>(null);
  const suppressCardClick = useRef(false);
  const [handleDragging, setHandleDragging] = useState(false);
  useEffect(() => {
    if (!editorOpen) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const editor = document.getElementById("activity-editor");
    editor?.querySelector<HTMLButtonElement>("button")?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setEditorOpen(false); return; }
      if (event.key !== "Tab") return;
      const elements = Array.from(editor?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), summary") ?? []);
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", trap);
    return () => { document.removeEventListener("keydown", trap); previous?.focus(); };
  }, [editorOpen]);

  useEffect(() => {
    if (!handleDragging) return;
    let frame: number;
    const scroll = () => {
      const drag = handleDrag.current;
      if (!drag) return;
      const dy = drag.y > window.innerHeight - 80 ? 16 : drag.y < 80 ? -16 : 0;
      if (dy) window.scrollBy(0, dy);
      const scroller = document.getElementById("schedule-scroll");
      if (scroller) {
        const bounds = scroller.getBoundingClientRect();
        if (drag.x > bounds.left && drag.y > bounds.top && drag.y < bounds.bottom) {
          scroller.scrollBy(drag.x > bounds.right - 55 ? 14 : drag.x < bounds.left + 55 ? -14 : 0,
            drag.y > bounds.bottom - 55 ? 14 : drag.y < bounds.top + 55 ? -14 : 0);
        }
      }
      const target = document.elementFromPoint(drag.x, drag.y)?.closest<HTMLElement>("[data-person]");
      setDropTarget(target?.dataset.person ? `${target.dataset.person}:${target.dataset.day ?? "nome"}` : "");
      const block = document.elementFromPoint(drag.x, drag.y)?.closest<HTMLElement>("[data-schedule-block]");
      setInsertionTarget(drag.payload.bloco && block && target ? `${target.dataset.person}:${block.dataset.scheduleBlock}` : "");
      frame = requestAnimationFrame(scroll);
    };
    frame = requestAnimationFrame(scroll);
    return () => cancelAnimationFrame(frame);
  }, [handleDragging]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setPlan(null); setError(""); setBusy(true);
    getWorkPlan(id).then((doc) => {
      if (cancelled) return;
      setPlan(doc); setDay(doc.inicio);
      setView(router.query.modo === "corretiva" ? "corretiva" : router.query.modo === "revisao" ? "revisao" : "pm");
      setDirty(false);
      setSpecialtiesRefreshed(false);
    }).catch((failure: unknown) => { if (!cancelled) setError(describeError(failure)); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [id]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    const routeStart = (url: string) => {
      if (!window.confirm("Há alterações não salvas. Sair e descartá-las?")) {
        const cancelled = Object.assign(new Error("Navegação cancelada: planejamento não salvo."), { cancelled: true });
        router.events.emit("routeChangeError", cancelled, url, { shallow: false });
        throw cancelled;
      }
    };
    window.addEventListener("beforeunload", warn);
    router.events.on("routeChangeStart", routeStart);
    return () => { window.removeEventListener("beforeunload", warn); router.events.off("routeChangeStart", routeStart); };
  }, [dirty, router.events]);

  const days = plan ? daysBetween(plan.inicio, plan.fim) : [];
  const metrics = plan ? planningMetrics(plan) : null;
  const conflicts = useMemo(() => plan ? conflictingBlocks(plan) : new Set<string>(), [plan]);
  const currentOrder = plan?.ordens.find((o) => orderKey(o) === selected);
  const requirement = plan?.requisitos[selected];
  const selectedPlacement = plan?.posicionamentos?.find((p) => p.ot === selected);
  const recommendedDays = currentOrder ? proposedDays(currentOrder, days) : [];
  const crafts = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of plan?.pessoas ?? []) map.set(JSON.stringify([p.orgid, p.funcao]), `${p.funcao_descricao} (${p.orgid}/${p.funcao})`);
    return [...map];
  }, [plan?.pessoas]);
  const specialtyOptions = useMemo(() => {
    const options = new Map<string, string>();
    if (!plan) return [];
    for (const p of plan.pessoas) options.set(p.funcao, `${p.funcao_descricao} (${p.funcao})`);
    for (const o of plan.ordens) {
      for (const s of orderSpecialties(o, plan.requisitos[orderKey(o)]))
        if (!options.has(s.code)) options.set(s.code, `Especialidade ${s.code}`);
    }
    return [...options].sort((a, b) => a[1].localeCompare(b[1]));
  }, [plan]);
  const visible = plan?.ordens.filter((o) => (view === "revisao" || activityMode(o) === view)
    && pendingActivity(plan, orderKey(o))
    && !plan.posicionamentos?.some((p) => p.ot === orderKey(o))
    && matchesOrderSpecialty(o, plan.requisitos[orderKey(o)], specialtyFilter)
    && (!categoryFilter || activityCategory(o) === categoryFilter)
    && normalize(`${o.wonum} ${cellText(o, "description")} ${cellText(o, "location")}`).includes(normalize(search))) ?? [];
  const checked = visible.filter((o) => plan?.requisitos[orderKey(o)].selecionada).map(orderKey);
  const excluded = plan?.ordens.filter((o) => {
    const req = plan.requisitos[orderKey(o)];
    return !req.duracao || allocatedDuration(plan, orderKey(o)) < req.duracao - 1e-6;
  }) ?? [];

  function edit(next: WorkPlan) {
    setPlan(next); setDirty(true); setReviewed(false); setMessage(""); setError("");
  }
  function markOrders(keys: string[], checked: boolean) {
    if (!plan) return;
    const requirements = { ...plan.requisitos };
    for (const key of keys) requirements[key] = { ...requirements[key], selecionada: checked };
    edit({ ...plan, requisitos: requirements });
  }
  function assignBatch(person: string, keys = checked, fromDay = plan?.inicio, exactDay = false) {
    if (!plan || !keys.length) { setError("Marque ao menos uma OT para distribuir."); return; }
    const result = distributeBatch(plan, keys, person, fromDay, exactDay);
    const added = result.blocos.length - plan.blocos.length;
    const snapshot = { ...plan, blocos: result.blocos };
    const placements = (plan.posicionamentos ?? []).filter((p) => !keys.includes(p.ot));
    for (const key of keys) {
      if (exactDay && pendingActivity(snapshot, key))
        placements.push({ ot: key, executante: person, dia: fromDay ?? plan.inicio });
    }
    edit({ ...snapshot, posicionamentos: placements }); setSuggestions(result.mensagens);
    if (!added && result.mensagens.length) {
      if (exactDay) setMessage("Cartão da OT posicionado no quadrado escolhido. Dados/horas pendentes ficam sinalizados no cartão; você já pode salvar o rascunho.");
      else setError(result.mensagens.join(" "));
    } else {
      setMessage(added ? "OT(s) posicionada(s) nos quadrados dos dias do executante. Atividades totalmente alocadas saíram da carteira; parciais continuam com horas pendentes." : "As OTs escolhidas já estão totalmente alocadas; nenhum bloco foi duplicado.");
      if (added) requestAnimationFrame(() => {
        const grid = document.getElementById("integrated-schedule");
        const cell = Array.from(grid?.querySelectorAll<HTMLElement>("td[data-person]") ?? []).find((element) =>
          element.dataset.person === person && result.blocos.some((b) =>
            keys.includes(b.ot) && b.executantes.includes(person) && b.dia === element.dataset.day));
        cell?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
      });
    }
  }
  function editRequirement(patch: Partial<Requirement>) {
    if (plan && requirement) edit({ ...plan, requisitos: { ...plan.requisitos, [selected]: { ...requirement, ...patch } } });
  }
  function selectOrder(key: string) {
    setSelected(key); setBlockId(""); setMembers([]); setHours("");
  }
  function openEditor(key: string) {
    if (!plan) return;
    selectOrder(key);
    const placement = plan.posicionamentos?.find((p) => p.ot === key);
    const order = plan.ordens.find((o) => orderKey(o) === key);
    const recommended = order ? proposedDays(order, days) : [];
    setExecutionDays(placement ? days.filter((d) => d >= placement.dia && weekStart(d) === weekStart(placement.dia))
      : recommended.length ? recommended : days.filter((d) => weekStart(d) === weekStart(plan.inicio)));
    setDay(placement?.dia ?? plan.inicio);
    const req = plan.requisitos[key];
    const candidates = plan.pessoas.filter((p) => specialtyMatches(p, req));
    const preferred = placement ? [placement.executante] : [];
    setMembers([...preferred, ...candidates.map((p) => p.id).filter((p) => !preferred.includes(p))]
      .slice(0, req.pessoas ?? preferred.length));
    setEditorOpen(true);
    requestAnimationFrame(() => document.getElementById("activity-editor")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  function change(confirmar = false): PlanChange {
    if (!plan) throw new Error("Planejamento não carregado.");
    return { revisao: plan.revisao, requisitos: plan.requisitos, blocos: plan.blocos,
      indisponibilidades: plan.indisponibilidades, motivo: "Atualização do planejamento", confirmar,
      atualizar_especialidades: specialtiesRefreshed, posicionamentos: plan.posicionamentos ?? [] };
  }
  async function save(confirming = false) {
    if (!plan) return;
    if ((confirming || plan.status === "confirmado") && conflicts.size) { setError("Resolva os blocos vermelhos antes de confirmar ou alterar um planejamento confirmado."); return; }
    if ((confirming || plan.status === "confirmado") && plan.posicionamentos?.length) {
      setError("Há cartões posicionados com dados/horas pendentes. Complete ou retire antes de confirmar."); return;
    }
    if (confirming && !reviewed) { setError("Confira as atividades incluídas e excluídas e marque a revisão."); return; }
    setBusy(true); setError("");
    try {
      const saved = await saveWorkPlan(plan.id, change(confirming));
      setPlan(saved); setDirty(false); setReviewed(false);
      setSpecialtiesRefreshed(false);
      setMessage(`Revisão ${saved.revisao} salva e PDF arquivado localmente. Nenhum envio ao BMA ou SharePoint foi realizado.`);
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }
  async function suggest() {
    if (!plan || view === "revisao") return;
    const keys = checked;
    if (!keys.length) { setError("Marque as OTs que deseja incluir na sugestão."); return; }
    setBusy(true); setError("");
    try {
      const result = await suggestWorkPlan(plan.id, view, change(), keys);
      const next = { ...plan, blocos: result.blocos };
      edit({ ...next, posicionamentos: plan.posicionamentos?.filter((p) => pendingActivity(next, p.ot)) }); setSuggestions(result.mensagens);
      setMessage("Sugestão aplicada somente na tela. Revise os blocos e salve; nenhuma alocação existente foi removida.");
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }
  async function refreshSpecialties() {
    if (!plan) return;
    setBusy(true); setError("");
    try {
      const result = await refreshPlanSpecialties(plan.id, change());
      edit(result.plano); setSpecialtiesRefreshed(true);
      setMessage(`Especialidades de ${result.atualizadas} OT(s) relidas do banco local. Alocações e escolhas manuais preservadas. Salve para registrar na revisão.`);
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }
  function beginPointer(event: PointerEvent<HTMLElement>, payload: DragPayload) {
    if (busy || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    suppressCardClick.current = false;
    handleDrag.current = { payload, x: event.clientX, y: event.clientY,
      startX: event.clientX, startY: event.clientY, moved: false };
  }
  function movePointer(event: PointerEvent<HTMLElement>) {
    const moving = handleDrag.current;
    if (!moving) return;
    moving.x = event.clientX; moving.y = event.clientY;
    if (Math.hypot(moving.x - moving.startX, moving.y - moving.startY) > 5) {
      moving.moved = true; suppressCardClick.current = true; setHandleDragging(true);
    }
  }
  function cancelPointer() {
    handleDrag.current = null; setHandleDragging(false); setDropTarget(""); setInsertionTarget("");
  }
  function finishPointer(event: PointerEvent<HTMLElement>) {
    const moving = handleDrag.current;
    cancelPointer();
    if (!moving?.moved || !plan) return;
    event.preventDefault(); event.stopPropagation();
    const element = document.elementFromPoint(event.clientX, event.clientY);
    const target = element?.closest<HTMLElement>("[data-person]");
    if (!target?.dataset.person) { setError("Solte em um cartão ou quadrado do cronograma."); return; }
    try {
      const payload = moving.payload, person = target.dataset.person;
      if (payload.bloco) {
        const original = plan.blocos.find((b) => b.id === payload.bloco);
        const before = element?.closest<HTMLElement>("[data-schedule-block]")?.dataset.scheduleBlock;
        edit({ ...plan, blocos: resequenceWeek(plan, payload.bloco, payload.origem ?? person, person,
          target.dataset.day ?? original?.dia ?? plan.inicio, before) });
        setMessage("Sequência reprogramada na mesma semana. Duração e equipe preservadas; confira os novos dias e salve a revisão.");
      } else {
        selectOrder(payload.ot);
        assignBatch(person, payload.lote ?? [payload.ot], target.dataset.day ?? plan.inicio, !!target.dataset.day);
      }
    } catch (failure) { setError(describeError(failure)); }
  }
  function drag(event: DragEvent, payload: DragPayload) {
    const batch = payload.lote ?? (!payload.bloco && checked.includes(payload.ot) ? checked : undefined);
    event.dataTransfer.setData("application/x-pcm", JSON.stringify({ ...payload, lote: batch }));
    event.dataTransfer.effectAllowed = payload.bloco ? "move" : "copy";
  }
  function drop(event: DragEvent, targetDay: string | undefined, person: string, beforeBlockId?: string) {
    event.preventDefault(); event.stopPropagation();
    setDropTarget(""); setInsertionTarget("");
    if (!plan || busy) return;
    try {
      const payload: unknown = JSON.parse(event.dataTransfer.getData("application/x-pcm"));
      if (!payload || typeof payload !== "object" || !("ot" in payload) || typeof payload.ot !== "string") throw new Error("Arraste uma OT ou um bloco desta bancada.");
      const block = "bloco" in payload && typeof payload.bloco === "string" ? payload.bloco : undefined;
      const source = "origem" in payload && typeof payload.origem === "string" ? payload.origem : undefined;
      if (!block) {
        const keys = "lote" in payload && Array.isArray(payload.lote) && payload.lote.every((k): k is string => typeof k === "string") ? payload.lote : [payload.ot];
        selectOrder(payload.ot);
        assignBatch(person, keys, targetDay ?? plan.inicio, !!targetDay); return;
      }
      const original = plan.blocos.find((b) => b.id === block);
      const blocks = resequenceWeek(plan, block, source ?? person, person, targetDay ?? original?.dia ?? plan.inicio, beforeBlockId);
      edit({ ...plan, blocos: blocks }); selectOrder(payload.ot);
      setMessage("Sequência reprogramada na mesma semana. Duração e equipe preservadas; confira os novos dias e salve a revisão.");
    } catch (failure) { setError(describeError(failure)); }
  }
  function manualBlock() {
    if (!plan || !selected) return;
    if (!blockId) {
      try {
        const blocks = scheduleSelectedDays(plan, selected, executionDays, members);
        const next = { ...plan, blocos: blocks, requisitos: { ...plan.requisitos,
          [selected]: { ...plan.requisitos[selected], pessoas: members.length } } };
        edit({ ...next, posicionamentos: plan.posicionamentos?.filter((p) => p.ot !== selected) });
        setEditorOpen(false);
        setMessage("Atividade adicionada ao cronograma nos dias marcados, usando o saldo diário dos executantes.");
        requestAnimationFrame(() => document.getElementById("integrated-schedule")?.scrollIntoView({ behavior: "smooth", block: "start" }));
      } catch (failure) { setError(describeError(failure)); }
      return;
    }
    const duration = Number(hours);
    if (!hours || !Number.isFinite(duration) || duration <= 0 || duration > 1000 || !day || !members.length) {
      setError("Informe dia, horas positivas (até 1000) e executantes."); return;
    }
    const block: Allocation = { id: blockId || crypto.randomUUID(), ot: selected, dia: day,
      inicio: 0, horas: duration, executantes: members };
    if (plan.blocos.some((b) => b.ot === selected && b.id !== blockId && b.executantes.length !== members.length)) {
      setError("A quantidade de executantes deve ser igual nos blocos da OT. Retire os blocos anteriores para alterar."); return;
    }
    const next = { ...plan, blocos: [...plan.blocos.filter((b) => b.id !== blockId), block],
      requisitos: { ...plan.requisitos, [selected]: { ...plan.requisitos[selected], pessoas: members.length } } };
    edit({ ...next, posicionamentos: pendingActivity(next, selected) ? plan.posicionamentos : plan.posicionamentos?.filter((p) => p.ot !== selected) });
    setBlockId(""); setMembers([]); setHours("");
    setEditorOpen(false);
    setMessage("Atividade incluída no dia. A confirmação valida a capacidade semanal individual, especialidades, disponibilidade e duração total.");
  }
  function postpone(key: string) {
    if (!plan) return;
    if (!window.confirm("Retirar todos os blocos desta OT? Ela voltará à carteira não alocada; registre o motivo na preparação e na revisão.")) return;
    edit({ ...plan, blocos: plan.blocos.filter((b) => b.ot !== key), posicionamentos: plan.posicionamentos?.filter((p) => p.ot !== key) });
  }
  async function pdf(revision: number) {
    if (!plan) return;
    setBusy(true); setError("");
    try { await downloadSchedule(plan.id, revision); } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }

  return <>
    <Head><title>Bancada de planejamento | Centro PCM</title></Head>
    <main className="pcm-workspace mx-auto min-h-screen max-w-[2000px] space-y-5 p-4 lg:p-7">
      <header className="pcm-panel flex flex-wrap items-center justify-between gap-4 p-5">
        <div>
          <Link href="/planejamento/acompanhamento" className="mb-3 inline-flex items-center gap-2 text-xs text-sky-300"><ArrowLeft size={14} /> Acompanhamento</Link>
          <h1 className="text-2xl font-semibold text-white">Bancada de Planejamento PCM</h1>
          {plan && <><p className="mt-2 text-sm text-slate-400">{formatPlanningDate(plan.inicio)} a {formatPlanningDate(plan.fim)} · {plan.planejador} · {plan.status} · revisão {plan.revisao}</p>
            <Link href={{ pathname: "/planejamento/ots", query: { setor: plan.setores } }} className="mt-2 inline-flex text-xs text-sky-300">Voltar ao Centro PCM</Link></>}
        </div>
        {plan && <div className="flex flex-wrap gap-2">
          <NfeReportButton />
          <Link href="/planejamento" className="pcm-small-button"><RefreshCw size={15} /> Atualizar banco pelo BMA</Link>
          <button className="pcm-small-button" disabled={busy} onClick={() => void refreshSpecialties()}><RefreshCw size={15} /> Reler especialidades do banco</button>
          <button className="pcm-small-button" disabled={busy || dirty} onClick={() => void pdf(plan.revisao)}><Download size={15} /> PDF da revisão salva</button>
          <button className="pcm-primary-button" disabled={busy} onClick={() => void save()}><Save size={15} /> {plan.status === "confirmado" ? "Salvar reprogramação" : "Salvar rascunho"}</button>
        </div>}
      </header>
      {error && <p role="alert" className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-4 text-sm text-rose-200">{error}</p>}
      {message && <p role="status" className="rounded-lg border border-sky-400/30 bg-sky-400/10 p-4 text-sm text-sky-200">{message}</p>}
      {!plan ? <p className="text-slate-400">{busy ? "Carregando planejamento..." : "Abra um planejamento pela carteira ou pelo acompanhamento."}</p> : <>
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Capacidade compartilhada">
          {[["Capacidade disponível", metrics?.capacity], ["Comprometido PM", metrics?.pm], ["Comprometido corretiva", metrics?.corrective], ["Saldo para encaixe", metrics?.remaining]].map(([label, value]) =>
            <div key={String(label)} className="pcm-panel p-4"><p className="text-xs text-slate-400">{label}</p><p className="mt-2 text-2xl font-semibold text-white">{formatNumber(typeof value === "number" ? value : null)} HH</p></div>)}
        </section>
        {!!conflicts.size && <p role="alert" className="rounded-lg border border-rose-400/40 bg-rose-400/10 p-4 text-sm text-rose-200">{conflicts.size} alocação(ões) com capacidade semanal excedida. {plan.status === "rascunho" ? "Prévia pode ser salva como rascunho; confirmação bloqueada." : "Plano já confirmado: ajuste a capacidade semanal antes de salvar a revisão."} Redistribua para outro integrante com saldo ou retire atividades.</p>}
        <details className="rounded-lg border border-amber-400/20 bg-amber-400/5 p-3 text-xs leading-relaxed text-amber-100">
          <summary className="cursor-pointer">{dirty ? "Alterações não salvas" : "Rascunho local"} · Regras e integrações</summary>
          {dirty ? "Há alterações na tela ainda não salvas. " : "Revisão persistida localmente. "}
          Equipe, dias disponíveis e carteira são snapshots da criação deste plano; indisponibilidades já registradas continuam consideradas.
          Planejamento por dia, sem hora de início. Referência de 8 h por dia disponível; a carga diária pode superar 8 h, mas cada executante deve respeitar sua capacidade em cada semana (segunda a domingo). Qualificações especiais, bloqueios e materiais devem ser conferidos pelo planejador.
          Restrições de data são validadas por dia; confira horários específicos e possibilidade de interromper/dividir a atividade.
          <strong className="ml-1">BMA e SharePoint: integração pendente; não houve envio.</strong>
        </details>
        <nav className="flex flex-wrap gap-2" aria-label="Fluxo de alocação">
          {([["pm", "1 · Planejar PM"], ["corretiva", "2 · Encaixar corretiva"], ["revisao", "3 · Revisar e confirmar"]] as const).map(([key, label]) =>
            <button key={key} className={view === key ? "pcm-primary-button" : "pcm-small-button"} disabled={busy} aria-pressed={view === key} onClick={() => { setView(key); setLimit(60); }}>{label}</button>)}
          {view !== "revisao" && <button className="pcm-small-button ml-auto" disabled={busy} onClick={() => void suggest()}><Sparkles size={15} /> Sugerir encaixe {view === "pm" ? "PM" : "corretivo"}</button>}
        </nav>
        <p className="text-xs text-slate-400">Filtre na galeria, marque as OTs e arraste o lote até o executante. No cronograma, solte sobre um cartão para executar antes dele e reprogramar a sequência da semana.</p>
        <fieldset disabled={busy} className="min-w-0 space-y-5 disabled:opacity-60">
          <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)]">
            <section className="pcm-panel min-w-0 p-3 lg:sticky lg:top-3" aria-label="Galeria vertical de OTs">
              <h2 className="pcm-title">Carteira {view === "revisao" ? "integrada" : view.toUpperCase()} · {visible.length} OTs pendentes</h2>
              <details className="my-3 rounded-lg border border-white/10 p-2" id="portfolio-filters">
                <summary className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-sky-200"><SlidersHorizontal size={15} /> Filtros · {visible.length} OTs</summary>
              <input className={`${input} my-3`} aria-label="Buscar atividade" placeholder="OT, descrição ou local..." value={search} onChange={(e) => { setSearch(e.target.value); setLimit(60); }} />
              <select className={`${input} mb-3`} aria-label="Filtrar tipo de OT" value={categoryFilter} onChange={(e) => { setCategoryFilter(e.target.value); setLimit(60); }}>
                <option value="">Todos os tipos</option><option value="pm1">PM1</option><option value="pm2">PM2</option><option value="pm3">PM3</option>
                <option value="outras-pm">Outras PM</option><option value="corretiva">Corretiva</option>
              </select>
              <select className={`${input} mb-3`} aria-label="Filtrar carteira por especialidade" value={specialtyFilter} onChange={(e) => { setSpecialtyFilter(e.target.value); setLimit(60); }}>
                <option value="">Todas as especialidades</option><option value="indefinida">Especialidade não definida</option><option value="qualquer">Qualquer especialidade (Todos)</option>
                {specialtyOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
              <p className="text-[11px] text-slate-400">Especialidade exigida pela OT no BMA; na ausência, usa a preparação manual. Dados ausentes não são inferidos pela descrição.</p>
              <button type="button" className="pcm-small-button mt-2" onClick={() => { setSearch(""); setCategoryFilter(""); setSpecialtyFilter(""); }}>Limpar filtros</button>
              </details>
              <div className="mb-3 space-y-2 rounded-lg border border-sky-400/20 bg-sky-400/5 p-2">
                <label className="flex items-center gap-2 text-xs text-sky-200"><input type="checkbox" aria-label="Selecionar todas as OTs filtradas"
                  checked={visible.length > 0 && checked.length === visible.length} disabled={!visible.length}
                  ref={(element) => { if (element) element.indeterminate = checked.length > 0 && checked.length < visible.length; }}
                  onChange={(e) => markOrders(visible.map(orderKey), e.target.checked)} /> Selecionar todas as filtradas ({visible.length})</label>
                <p className="text-[11px] text-sky-200">{checked.length} OT(s) pendentes marcadas · lote somente dos filtros atuais</p>
                <div draggable={!busy && checked.length > 0} onDragStart={(e) => { if (checked[0]) drag(e, { ot: checked[0], lote: checked }); }} className="cursor-grab rounded border border-dashed border-sky-400/40 p-3 text-xs text-sky-200"><GripVertical size={14} className="inline" /> Arraste o lote marcado até o nome do executante</div>
                <details><summary className="cursor-pointer text-[11px] text-slate-400">Distribuir sem arrastar</summary>
                <select className={input} aria-label="Executante para distribuir lote" value={batchPerson} onChange={(e) => setBatchPerson(e.target.value)}><option value="">Escolha executante para o lote</option>{plan.pessoas.map((p) => <option key={p.id} value={p.id}>{p.nome} · {p.funcao_descricao}</option>)}</select>
                <button className="pcm-small-button" disabled={!batchPerson || !checked.length} onClick={() => { try { assignBatch(batchPerson); } catch (failure) { setError(describeError(failure)); } }}>Distribuir marcadas no período</button>
                </details>
              </div>
              <div className="mb-2 flex items-center justify-between text-[10px] text-slate-400"><span>Galeria · arraste os cartões</span><div className="flex gap-1">
                <button type="button" aria-label="Rolar galeria para cima" className="rounded border border-white/10 p-1" onClick={() => gallery.current?.scrollBy({ top: -240, behavior: "smooth" })}><ChevronUp size={14} /></button>
                <button type="button" aria-label="Rolar galeria para baixo" className="rounded border border-white/10 p-1" onClick={() => gallery.current?.scrollBy({ top: 240, behavior: "smooth" })}><ChevronDown size={14} /></button>
              </div></div>
              <div ref={gallery} className="max-h-[60vh] snap-y snap-proximity space-y-2 overflow-y-auto overscroll-contain pr-1 lg:max-h-[calc(100vh-290px)]" aria-label="OTs filtradas">
                {visible.slice(0, limit).map((order) => {
                  const key = orderKey(order), req = plan.requisitos[key], done = allocatedDuration(plan, key);
                  return <div key={key} className="relative flex snap-start items-start gap-2">
                    <input className="mt-4" type="checkbox" aria-label={`Planejar ${order.wonum}`} checked={req.selecionada ?? false} onChange={(e) => markOrders([key], e.target.checked)} />
                    <button type="button" draggable={!busy} onDragStart={(e) => drag(e, { ot: key })}
                    onClick={() => { selectOrder(key); setEditorOpen(false); }} className={`block w-full rounded-lg border p-3 text-left ${selected === key ? "border-sky-400 bg-sky-400/10" : "border-white/10 bg-white/[.02]"}`}>
                    <span className="flex items-center justify-between text-xs font-semibold text-sky-200"><span>{order.wonum} · {activityMode(order).toUpperCase()}</span>
                      <span data-drag-ot={key} aria-label={`Arrastar ${order.wonum} para pessoa e dia`}
                        title="Clique, segure e arraste até a célula de pessoa e dia"
                        onPointerDown={(e) => beginPointer(e, { ot: key, lote: checked.includes(key) ? checked : [key] })}
                        onPointerMove={movePointer} onPointerUp={finishPointer} onPointerCancel={cancelPointer}
                        onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
                        onClick={(e) => e.stopPropagation()}
                        className="mr-8 touch-none select-none cursor-grab rounded p-2 text-sky-200 hover:bg-sky-400/20 active:cursor-grabbing"><GripVertical size={18} /></span>
                    </span>
                    <span className="mt-1 block text-xs text-slate-300">{cellText(order, "description")}</span>
                    <span className="mt-2 block text-[11px] text-slate-400">{formatNumber(req.duracao)} h · {req.pessoas ?? "?"} pessoa(s) · {activityCategory(order).toUpperCase()}</span>
                    <span className="mt-1 block text-[11px] text-sky-200">Especialidade {plannedLabor(order).length ? "BMA" : "preparada"}: {orderSpecialties(order, req).map((s) => specialtyOptions.find(([code]) => code === s.code)?.[1] ?? s.code).join(" · ") || (req.todas_especialidades ? "Todos (escolha manual)" : "não coletada / não definida")}</span>
                    {done > 0 && <span className="mt-1 block text-[11px] text-emerald-300">Parcial · faltam {formatNumber(Math.max(0, (req.duracao ?? 0) - done))} h</span>}
                  </button><button type="button" aria-label={`Editar OT ${order.wonum}`} title="Preparar / editar atividade"
                    className="absolute right-3 top-5 rounded p-2 text-sky-200 hover:bg-sky-400/20" onClick={() => openEditor(key)}><Pencil size={16} /></button></div>;
                })}
                {!visible.length && <p className="text-sm text-slate-500">Nenhuma OT nesta seleção.</p>}
                {visible.length > limit && <button className="pcm-small-button" onClick={() => setLimit(limit + 60)}>Mostrar mais atividades</button>}
              </div>
            </section>
            {editorOpen && <div className="fixed inset-0 z-50 overflow-y-auto bg-black/70 p-3 sm:p-8" role="dialog" aria-modal="true" aria-label="Preparação e edição da atividade"
              onKeyDown={(e) => { if (e.key === "Escape") setEditorOpen(false); }}>
            <section className="pcm-panel mx-auto max-w-4xl space-y-4 p-5" id="activity-editor">
              <div className="flex items-center justify-between gap-3"><h2 className="pcm-title">Preparação e edição da atividade</h2>
                <button type="button" aria-label="Fechar edição da atividade" className="pcm-small-button" onClick={() => setEditorOpen(false)}><X size={16} /></button></div>
              {!currentOrder || !requirement ? <p className="py-10 text-sm text-slate-400">Selecione uma OT. Preencha os requisitos e arraste para um integrante/dia, ou aloque pelo formulário.</p> : <>
                <h3 className="text-sm font-semibold text-sky-200">{currentOrder.wonum} · {cellText(currentOrder, "description")}</h3>
                {selectedPlacement && <div className="rounded-lg border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-100">
                  <p>OT já posicionada: {plan.pessoas.find((p) => p.id === selectedPlacement.executante)?.nome} · {formatPlanningDate(selectedPlacement.dia)}. Complete os dados para contabilizar as horas e liberar a confirmação.</p>
                </div>}
                <p className="text-xs text-slate-500">BMA: duração {cellText(currentOrder, "estdur") || "não informada"} h · HH estimado {cellText(currentOrder, "estlabhrs") || "não informado"}. Duração não é HH: 4 h × 2 pessoas = 8 HH. Requisitos abaixo são preparação local.</p>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="text-xs text-slate-400">Duração total (h por pessoa)<input className={`${input} mt-1`} type="number" min=".01" max="1000" step=".25" value={requirement.duracao ?? ""} onChange={(e) => editRequirement({ duracao: e.target.value ? Number(e.target.value) : null })} /></label>
                  <div className="text-xs text-slate-400">Pessoas simultâneas<output className={`${input} mt-1 block`} aria-label="Pessoas simultâneas">{members.length} selecionada(s) · BMA: {plannedLabor(currentOrder).map((r) => r.quantity).filter(Boolean).join(" + ") || "não informado"}</output></div>
                  <label className="text-xs text-slate-400">Prioridade<select className={`${input} mt-1`} value={requirement.prioridade} onChange={(e) => editRequirement({ prioridade: Number(e.target.value) })}>{[1, 2, 3, 4, 5].map((p) => <option key={p} value={p}>{p} {p === 1 ? "· mais alta" : ""}</option>)}</select></label>
                </div>
                <label className="block text-xs text-slate-400">Especialidade exigida
                  <select className={`${input} mt-1`} value={requirement.todas_especialidades ? "todos" : requirement.funcao ? JSON.stringify([requirement.orgid, requirement.funcao]) : ""} onChange={(e) => {
                    setMembers([]);
                    if (e.target.value === "todos") {
                      editRequirement({ todas_especialidades: true, orgid: "", funcao: "" });
                      return;
                    }
                    const craft = crafts.find(([key]) => key === e.target.value);
                    const person = plan.pessoas.find((p) => JSON.stringify([p.orgid, p.funcao]) === craft?.[0]);
                    editRequirement({ todas_especialidades: false, orgid: person?.orgid ?? "", funcao: person?.funcao ?? "" });
                  }}><option value="">Selecione (não inferida)</option><option value="todos">Todos — qualquer especialidade da equipe</option>{crafts.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
                </label>
                <div className="border-t border-white/10 pt-4">
                  <h3 className="text-sm font-semibold text-white">{blockId ? "Editar bloco selecionado" : "Alocar bloco diário"}</h3>
                  <div className="my-3 grid gap-3 sm:grid-cols-2">
                    {blockId ? <><label className="text-xs text-slate-400">Dia<select className={`${input} mt-1`} value={day} onChange={(e) => setDay(e.target.value)}>{days.map((d) => <option key={d} value={d}>{formatPlanningDate(d)}</option>)}</select></label>
                    <label className="text-xs text-slate-400">Horas da atividade neste dia<input className={`${input} mt-1`} type="number" min=".01" max="1000" step=".25" value={hours} onChange={(e) => setHours(e.target.value)} /></label></>
                      : <fieldset className="sm:col-span-2"><legend className="mb-2 text-xs text-slate-400">Dias da execução · verde: proposta BMA</legend>
                        <div className="flex flex-wrap gap-2">{days.map((d) => <label key={d} className={`flex items-center gap-2 rounded border p-2 text-xs ${recommendedDays.includes(d) ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-200" : "border-white/15 text-slate-300"}`}>
                          <input type="checkbox" aria-label={`Executar em ${formatPlanningDate(d)}`} checked={executionDays.includes(d)}
                            onChange={(e) => setExecutionDays(e.target.checked ? [...executionDays, d] : executionDays.filter((v) => v !== d))} />
                          {formatPlanningDate(d)}</label>)}</div></fieldset>}
                  </div>
                  <p className="mb-2 text-xs text-slate-500">A quantidade simultânea acompanha os executantes selecionados. A duração restante usa o espaço livre de cada dia marcado e continua no próximo, na mesma semana.</p>
                  <div className="grid gap-2 sm:grid-cols-2">{plan.pessoas.filter((p) => specialtyMatches(p, requirement)).map((p) =>
                    <label key={p.id} className="flex gap-2 text-xs text-slate-300"><input type="checkbox" aria-label={`Executante ${p.nome}`} checked={members.includes(p.id)} onChange={(e) => {
                      const next = e.target.checked ? [...members, p.id] : members.filter((m) => m !== p.id);
                      setMembers(next);
                      if (!plan.blocos.some((b) => b.ot === selected)) editRequirement({ pessoas: next.length || null });
                    }} /> {p.nome} · {availableDay(plan, p.id, day) ? `${formatNumber(weeklyBalance(plan, p.id, day).remaining)} h de saldo semanal` : "Indisponível"}</label>)}</div>
                  <div className="mt-4 flex flex-wrap gap-2"><button type="button" onClick={manualBlock} className="pcm-primary-button">{blockId ? "Aplicar edição do bloco" : "Adicionar bloco"}</button>
                    {blockId && <button className="pcm-small-button" onClick={() => { setBlockId(""); setMembers([]); setHours(""); }}>Cancelar edição</button>}
                    {blockId && <button className="pcm-small-button text-rose-300" onClick={() => {
                      edit({ ...plan, blocos: plan.blocos.filter((b) => b.id !== blockId) }); setBlockId(""); setMembers([]); setHours("");
                    }}>Remover bloco</button>}
                    <button type="button" onClick={() => postpone(selected)} className="pcm-small-button text-amber-300">Retirar OT para reencaixe</button></div>
                </div>
                <details><summary className="cursor-pointer text-xs text-sky-300">Instruções e dados originais do BMA</summary><div className="mt-3"><OrderDetails order={currentOrder} /></div></details>
              </>}
            </section></div>}
          <section id="integrated-schedule" className="pcm-panel min-w-0 overflow-hidden p-4" aria-label="Grade de capacidade por integrante e dia">
            <h2 className="pcm-title"><CalendarDays size={18} /> Cronograma integrado · PM + corretiva</h2>
            <p className="my-2 text-xs text-slate-400">Arraste uma OT para distribuir pelos dias. Arraste uma alocação para mudar o dia ou o integrante. Clique para editar horas de trabalho e equipe, sem horário de início; o formulário também funciona sem arrastar.</p>
            <div id="schedule-scroll" className="max-h-[80vh] overflow-auto overscroll-contain">
              <table className="w-full border-separate border-spacing-2 text-left text-xs">
                <thead className="sticky top-0 z-20 bg-[#102235]"><tr><th className="sticky left-0 z-20 min-w-40 bg-[#102235] p-2">Executante / especialidade</th>{days.map((d) => <th key={d} className="min-w-44 p-2">{formatPlanningDate(d)}</th>)}</tr></thead>
                <tbody>{plan.pessoas.map((person) => <tr key={person.id}>
                  <th data-person={person.id} className={`sticky left-0 z-10 rounded-lg border border-dashed bg-[#102235] p-2 align-top font-normal ${dropTarget === `${person.id}:nome` ? "border-sky-300 ring-2 ring-sky-300/40" : "border-sky-400/30"}`}
                    onDragOver={(e) => { if (!busy) { e.preventDefault(); setDropTarget(`${person.id}:nome`); } }} onDrop={(e) => drop(e, undefined, person.id)}>
                    <p className="font-semibold text-white">{person.nome}</p><p className="mt-1 text-slate-500">{person.funcao_descricao}</p>
                    <p className="mt-2 text-[11px] text-sky-300">Solte o lote aqui · distribuir no período</p>
                    {[...new Set(days.map(weekStart))].map((week) => {
                      const balance = weeklyBalance(plan, person.id, week);
                      return <p key={week} className={`mt-1 ${balance.remaining < -1e-6 ? "text-rose-300" : "text-slate-400"}`}>Semana {formatPlanningDate(week)}: {formatNumber(balance.load)}/{formatNumber(balance.capacity)} h · saldo {formatNumber(balance.remaining)} h</p>;
                    })}
                  </th>
                  {days.map((d) => {
                    const available = availableDay(plan, person.id, d), load = dayLoad(plan, person.id, d);
                    const overloaded = weeklyBalance(plan, person.id, d).remaining < -1e-6;
                    const dailyCapacity = available ? 8 : 0;
                    const dailyRemaining = Math.max(0, dailyCapacity - load);
                    const percentage = dailyCapacity ? load / dailyCapacity * 100 : 0;
                    return <td key={d} aria-label={`${person.nome} · ${formatPlanningDate(d)}`} data-person={person.id} data-day={d}
                      onDragOver={(e) => { if (!busy && available) { e.preventDefault(); setDropTarget(`${person.id}:${d}`); } }}
                      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropTarget(""); }}
                      onDrop={(e) => drop(e, d, person.id)}
                      className={`rounded-lg border p-2 align-top ${dropTarget === `${person.id}:${d}` ? "border-sky-300 bg-sky-400/20 ring-2 ring-sky-300/40" : !available ? "border-white/5 bg-white/[.01] opacity-60" : overloaded ? "border-rose-400/60 bg-rose-400/10" : "border-white/10 bg-white/[.03]"}`}>
                      {dropTarget === `${person.id}:${d}` && <p className="mb-2 font-semibold text-sky-200">Soltar para associar a este executante e dia</p>}
                      <div className="mb-2" title={`Referência diária: ${dailyCapacity} h. Acima de 8 h é permitido com saldo semanal. Cartões pendentes não reservam horas.${overloaded ? " Capacidade semanal excedida." : ""}`}>
                        <div className={`mb-1 flex items-center justify-between gap-1 text-[10px] leading-tight tabular-nums ${overloaded ? "text-rose-300" : load > dailyCapacity ? "text-amber-200" : "text-slate-400"}`}>
                          <span>{available ? `${formatNumber(percentage)}%` : "Indisp."}</span>
                          <span>{formatNumber(load)} h ocup. · {formatNumber(dailyRemaining)} h disp.</span>
                        </div>
                        <div role="progressbar" aria-label={`Carga do dia de ${person.nome} em ${formatPlanningDate(d)}`}
                          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, percentage)}
                          aria-valuetext={`${available ? `${formatNumber(percentage)}%` : "Indisponível"} · ${formatNumber(load)} h ocupadas · ${formatNumber(dailyRemaining)} h disponíveis`}
                          className="h-1 overflow-hidden rounded bg-white/10">
                          <div className={`h-full ${overloaded ? "bg-rose-400" : load > dailyCapacity ? "bg-amber-400" : "bg-sky-400"}`}
                            style={{ width: `${dailyCapacity ? Math.min(100, percentage) : load > 0 ? 100 : 0}%` }} />
                        </div>
                      </div>
                      {(plan.posicionamentos ?? []).filter((p) => p.executante === person.id && p.dia === d).map((p) => {
                        const order = plan.ordens.find((o) => orderKey(o) === p.ot);
                        return <div key={p.ot} data-placement-ot={p.ot} className="group relative mb-2 rounded border border-amber-400/60 bg-amber-400/10 p-2 text-amber-100">
                          <button type="button" draggable={!busy} onDragStart={(e) => drag(e, { ot: p.ot, lote: [p.ot] })}
                            onClick={() => openEditor(p.ot)}
                            title="Rascunho com dados/horas pendentes. Clique para preparar; arraste para mover."
                            className="block w-full cursor-grab text-left">
                            <strong className="block pr-5">{order?.wonum} - {order && activityMode(order).toUpperCase()}</strong>
                            <span className="mt-1 block">{order && cellText(order, "description")}</span>
                          </button>
                          <button type="button" aria-label={`Voltar OT ${order?.wonum} à carteira`} title="Voltar à carteira"
                            className="absolute right-1 top-1 rounded p-1 text-amber-200 opacity-0 hover:bg-amber-400/20 focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
                            onClick={() => edit({ ...plan, posicionamentos: plan.posicionamentos?.filter((item) => item.ot !== p.ot) })}><Undo2 size={13} /></button>
                        </div>;
                      })}
                      {plan.blocos.filter((b) => b.dia === d && b.executantes.includes(person.id)).map((b) => {
                        const order = plan.ordens.find((o) => orderKey(o) === b.ot);
                        return <button key={b.id} type="button" draggable={!busy} onDragStart={(e) => drag(e, { ot: b.ot, bloco: b.id, origem: person.id })}
                          onPointerDown={(e) => beginPointer(e, { ot: b.ot, bloco: b.id, origem: person.id })}
                          onPointerMove={movePointer} onPointerUp={finishPointer} onPointerCancel={cancelPointer}
                          data-schedule-block={b.id}
                          onDragOver={(e) => { if (!busy) { e.preventDefault(); e.stopPropagation(); setInsertionTarget(`${person.id}:${b.id}`); } }}
                          onDragLeave={() => setInsertionTarget("")}
                          onDragEnd={() => { setInsertionTarget(""); setDropTarget(""); }}
                          onDrop={(e) => drop(e, d, person.id, b.id)}
                          title={`${formatNumber(b.horas)} h neste dia · ${b.executantes.length} pessoa(s)${conflicts.has(b.id) ? " · Capacidade semanal excedida" : ""}. Clique para editar.`}
                          onClick={() => { if (suppressCardClick.current) { suppressCardClick.current = false; return; } openEditor(b.ot); setBlockId(b.id); setDay(b.dia); setHours(String(b.horas)); setMembers(b.executantes); }}
                          className={`mb-2 block w-full touch-none cursor-grab rounded border p-2 text-left active:cursor-grabbing ${insertionTarget === `${person.id}:${b.id}` ? "border-t-4 border-t-sky-300 ring-2 ring-sky-300/40" : ""} ${conflicts.has(b.id) ? "border-rose-400 bg-rose-400/20 text-rose-100" : order && activityMode(order) === "pm" ? "border-sky-400/25 bg-sky-400/10 text-sky-100" : "border-amber-400/25 bg-amber-400/10 text-amber-100"}`}>
                          <strong>{order?.wonum} - {order && activityMode(order).toUpperCase()}</strong>
                          <span className="mt-1 block">{order && cellText(order, "description")}</span>
                        </button>;
                      })}
                    </td>;
                  })}
                </tr>)}</tbody>
              </table>
            </div>
          </section>
          </div>
          {view === "revisao" && <section className="pcm-panel space-y-4 p-5">
            <h2 className="pcm-title"><CheckCircle2 size={18} /> Revisão integrada e confirmação local</h2>
            <p className="text-sm text-slate-300">{new Set(plan.blocos.map((b) => b.ot)).size} atividades com blocos · {excluded.length} não alocadas ou parciais.</p>
            <p className="text-xs text-slate-400">Confira a grade completa acima. Atividades parciais não podem ser confirmadas: complete a duração ou retire a OT. Nenhuma atividade de fora será incluída automaticamente.</p>
            <div className="max-h-80 space-y-2 overflow-y-auto">{excluded.map((o) => <div key={orderKey(o)} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-400/15 p-3 text-xs">
              <span>{o.wonum} · {activityMode(o).toUpperCase()} · {cellText(o, "description")}<span className="mt-1 block text-slate-500">Alocado {formatNumber(allocatedDuration(plan, orderKey(o)))}/{formatNumber(plan.requisitos[orderKey(o)].duracao)} h · {plan.requisitos[orderKey(o)].observacao || "Sem observação registrada"}</span></span>
              <button className="pcm-small-button" onClick={() => openEditor(orderKey(o))}>Preparar / encaixar</button>
            </div>)}</div>
            <label className="flex gap-2 text-sm text-slate-300"><input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} /> Conferi atividades incluídas, saldo, recursos e atividades que ficaram de fora.</label>
            <button className="pcm-primary-button" disabled={!reviewed || conflicts.size > 0 || !!plan.posicionamentos?.length} onClick={() => void save(true)}><CheckCircle2 size={16} /> {plan.status === "confirmado" ? "Confirmar revisão local" : "Confirmar planejamento local"}</button>
            <button className="pcm-small-button ml-3" disabled title="Integração ainda não configurada">Enviar informações ao BMA · a configurar</button>
          </section>}
        </fieldset>
        {!!suggestions.length && <details open className="pcm-panel p-4"><summary className="cursor-pointer text-sm text-amber-200">Pendências da última distribuição / sugestão ({suggestions.length})</summary><ul className="mt-3 max-h-60 space-y-1 overflow-y-auto text-xs text-slate-400">{suggestions.map((s, i) => <li key={i}>{s}</li>)}</ul></details>}
      </>}
      {handleDragging && <div className="pointer-events-none fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-sky-300 bg-[#081729] px-5 py-3 text-sm text-sky-100 shadow-xl">Arrastando OT · solte na célula do executante e dia</div>}
    </main>
  </>;
}
