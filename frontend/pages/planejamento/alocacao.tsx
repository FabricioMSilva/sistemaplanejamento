import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from "react";
import { AlertCircle, ArrowLeft, CheckCircle2, Download, ExternalLink, GripVertical, LoaderCircle, Save, Send, Sparkles, CalendarDays, RefreshCw, Undo2, Pencil, X, SlidersHorizontal, ChevronLeft, ChevronRight, UsersRound } from "lucide-react";
import {
  downloadSchedule, getBmaPageMonitor, getBmaSendStatus, getWorkPlan, openOrderInBma, orderKey, saveWorkPlan, sendPlanningToBmaReader, stopBmaPageMonitor,
  suggestWorkPlan, refreshPlanSpecialties, updateWorkPlanTeam,
  type Allocation, type BmaPageMonitor, type BmaSendStatus, type PlanChange, type Requirement, type WorkPlan,
} from "@/services/pcm";
import LaborPlanningModal from "@/components/LaborPlanningModal";
import { cellText, hasExistingPlanningInfo, isCorrectiveAvailable, normalize } from "@/utils/orderFilters";
import { daysBetween, formatNumber, localDate } from "@/utils/pcmDashboard";
import { formatPlanningDate } from "@/utils/laborPlanning";
import { activityMode, activityCategory, activityDateConstraintError, activityPlanningComplete, allocatedDuration, availableDay, conflictingBlocks, dayLoad, provisionalDayLoad, distributeBatch, isTargetDay, pendingActivity, planningMetrics, prepareDraggedOrder, specialtyMatches, specialtyWorkload, weeklyBalance, weekStart, resequenceWeek } from "@/utils/workPlanning";
import OrderDetails from "@/components/OrderDetails";
import NfeReportButton from "@/components/NfeReportButton";
import { matchesOrderSpecialty, missingPlanningData, orderSpecialties, plannedLabor } from "@/utils/plannedLabor";

const input = "w-full rounded-lg border border-white/15 bg-[#081729] p-2 text-sm text-white [color-scheme:dark]";
type View = "pm" | "corretiva";
type DragPayload = { ot: string; bloco?: string; origem?: string; lote?: string[] };
const describeError = (error: unknown) => error instanceof Error ? error.message : "Falha na operação de planejamento.";
const BMA_BADGES: Record<string, [string, string]> = {
  planejada: ["Planejada no BMA", "border-emerald-400/50 bg-emerald-400/15 text-emerald-200"],
  ja_planejada: ["Já planejada no BMA", "border-emerald-400/50 bg-emerald-400/15 text-emerald-200"],
  pendente_planejador: ["Revisar planejamento", "border-amber-400/50 bg-amber-400/15 text-amber-200"],
  erro: ["Erro no envio ao BMA", "border-rose-400/50 bg-rose-400/15 text-rose-200"],
  nao_encontrada: ["Não encontrada no BMA", "border-rose-400/50 bg-rose-400/15 text-rose-200"],
};
const dayMonth = (value: string) => {
  const day = localDate(value);
  return day ? `${day.slice(8, 10)}/${day.slice(5, 7)}` : "—";
};

export default function AllocationPage() {
  const router = useRouter();
  const id = typeof router.query.plano === "string" ? router.query.plano : "";
  const [plan, setPlan] = useState<WorkPlan | null>(null);
  const [view, setView] = useState<View>("pm");
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const [specialtyFilter, setSpecialtyFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [limit, setLimit] = useState(60);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [teamEditorOpen, setTeamEditorOpen] = useState(false);
  const [bmaMonitorId, setBmaMonitorId] = useState("");
  const [bmaMonitor, setBmaMonitor] = useState<BmaPageMonitor | null>(null);
  const [bmaMonitorError, setBmaMonitorError] = useState("");
  const [bmaStatus, setBmaStatus] = useState<Record<string, BmaSendStatus>>({});
  const [dirty, setDirty] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [blockId, setBlockId] = useState("");
  const [day, setDay] = useState("");
  const [hours, setHours] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [executantFilter, setExecutantFilter] = useState<string[] | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [specialtiesRefreshed, setSpecialtiesRefreshed] = useState(false);
  const [dropTarget, setDropTarget] = useState("");
  const [dropTargetTone, setDropTargetTone] = useState<"target" | "outside" | null>(null);
  const [insertionTarget, setInsertionTarget] = useState("");
  const gallery = useRef<HTMLDivElement>(null);
  const handleDrag = useRef<{ payload: DragPayload; x: number; y: number; startX: number; startY: number; moved: boolean } | null>(null);
  const activeDraggedOrder = useRef("");
  const suppressCardClick = useRef(false);
  const [handleDragging, setHandleDragging] = useState(false);
  function highlightDropTarget(person: string, targetDay?: string) {
    setDropTarget(`${person}:${targetDay ?? "nome"}`);
    const order = plan?.ordens.find((item) => orderKey(item) === activeDraggedOrder.current);
    setDropTargetTone(targetDay && order
      ? !activityDateConstraintError(order, targetDay) && isTargetDay(order, targetDay) ? "target" : "outside"
      : null);
  }
  function clearDropTarget() {
    setDropTarget(""); setDropTargetTone(null);
  }
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
          window.scrollBy(drag.x > bounds.right - 55 ? 14 : drag.x < bounds.left + 55 ? -14 : 0,
            drag.y > bounds.bottom - 55 ? 14 : drag.y < bounds.top + 55 ? -14 : 0);
        }
      }
      const target = document.elementFromPoint(drag.x, drag.y)?.closest<HTMLElement>("[data-person]");
      if (target?.dataset.person) highlightDropTarget(target.dataset.person, target.dataset.day);
      else clearDropTarget();
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
      setView(router.query.modo === "corretiva" ? "corretiva" : "pm");
      setDirty(false);
      setSpecialtiesRefreshed(false);
    }).catch((failure: unknown) => { if (!cancelled) setError(describeError(failure)); })
      .finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; };
  }, [id]);

  useEffect(() => {
    if (!bmaMonitorId) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const state = await getBmaPageMonitor(bmaMonitorId);
        if (cancelled) return;
        setBmaMonitor(state);
        if (state.progress !== 100 && !["completed", "failed", "stopped"].includes(state.status))
          timer = window.setTimeout(() => void poll(), 900);
      } catch (failure) {
        if (!cancelled) setBmaMonitorError(describeError(failure));
      }
    };
    void poll();
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); };
  }, [bmaMonitorId]);

  useEffect(() => {
    if (!id || !["completed", "failed", "stopped", undefined].includes(bmaMonitor?.status)) return;
    let cancelled = false;
    getBmaSendStatus(id).then((rows) => {
      if (!cancelled) setBmaStatus(Object.fromEntries(rows.map((row) => [row.numero_ot, row])));
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [id, bmaMonitor?.status]);

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
  const weeks = [...new Set(days.map(weekStart))];
  const metrics = plan ? planningMetrics(plan) : null;
  const specialtyRows = useMemo(() => plan ? specialtyWorkload(plan) : [], [plan]);
  const conflicts = useMemo(() => plan ? conflictingBlocks(plan) : new Set<string>(), [plan]);
  const currentOrder = plan?.ordens.find((o) => orderKey(o) === selected);
  const requirement = plan?.requisitos[selected];
  const selectedPlacement = plan?.posicionamentos?.find((p) => p.ot === selected);
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
  const visible = plan?.ordens.filter((o) => activityMode(o) === view
    && (view !== "pm" || !hasExistingPlanningInfo(o))
    && (view !== "corretiva" || isCorrectiveAvailable(o))
    && pendingActivity(plan, orderKey(o))
    && !plan.posicionamentos?.some((p) => p.ot === orderKey(o))
    && matchesOrderSpecialty(o, plan.requisitos[orderKey(o)], specialtyFilter)
    && (!categoryFilter || activityCategory(o) === categoryFilter)
    && normalize(`${o.wonum} ${cellText(o, "description")} ${cellText(o, "location")}`).includes(normalize(search))) ?? [];
  const checked = visible.filter((o) => plan?.requisitos[orderKey(o)].selecionada).map(orderKey);
  const displayedStatus = plan ? dirty ? (busy ? "salvando" : "alterações pendentes") : plan.status : "";
  const firstPlannedPm = plan ? [...plan.blocos]
    .sort((left, right) => left.dia.localeCompare(right.dia) || left.inicio - right.inicio || left.ot.localeCompare(right.ot))
    .map((block) => plan.ordens.find((order) => orderKey(order) === block.ot))
    .find((order) => order && activityMode(order) === "pm") : undefined;
  const hasPlannedPm = Boolean(firstPlannedPm);

  function edit(next: WorkPlan) {
    setPlan(next); setDirty(true); setMessage(""); setError("");
  }
  function markOrders(keys: string[], checked: boolean) {
    if (!plan) return;
    const requirements = { ...plan.requisitos };
    for (const key of keys) requirements[key] = { ...requirements[key], selecionada: checked };
    edit({ ...plan, requisitos: requirements });
  }
  function assignBatch(person: string, keys = checked, fromDay = plan?.inicio, exactDay = false) {
    if (!plan || !keys.length) { setError("Marque ao menos uma OT para distribuir."); return; }
    if (exactDay && fromDay) {
      if (fromDay < plan.inicio || fromDay > plan.fim) { setError("Dia fora do horizonte do planejamento."); return; }
      const dateError = keys.map((key) => {
        const order = plan.ordens.find((item) => orderKey(item) === key);
        return order && activityDateConstraintError(order, fromDay);
      }).find(Boolean);
      if (dateError) { setError(dateError); return; }
    }
    const prepared = keys.reduce((current, key) => prepareDraggedOrder(current, key), plan);
    const result = distributeBatch(prepared, keys, person, fromDay, exactDay);
    const added = result.blocos.length - plan.blocos.length;
    const requirements = { ...prepared.requisitos };
    if (exactDay) for (const key of keys) requirements[key] = { ...requirements[key], selecionada: true };
    const snapshot = { ...prepared, requisitos: requirements, blocos: result.blocos };
    const placements = (prepared.posicionamentos ?? []).filter((p) => !keys.includes(p.ot));
    for (const key of keys) {
      if (exactDay && pendingActivity(snapshot, key))
        placements.push({ ot: key, executante: person, dia: fromDay ?? plan.inicio });
    }
    const next = { ...snapshot, posicionamentos: placements };
    edit(next); setSuggestions(result.mensagens);
    if (!added && result.mensagens.length) {
      if (exactDay) setMessage("OT posicionada no dia escolhido. Revise duração, equipe ou especialidade no cartão se os dados do BMA não forem suficientes.");
      else setError(result.mensagens.join(" "));
    } else {
      setMessage(added ? "OT(s) planejada(s) com os dados disponíveis do BMA e padrões locais quando ausentes. Clique no bloco para revisar ou alterar horas, equipe e especialidade." : "As OTs escolhidas já estão totalmente alocadas; nenhum bloco foi duplicado.");
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
    setDay(placement?.dia ?? plan.inicio);
    const req = plan.requisitos[key];
    const candidates = plan.pessoas.filter((p) => specialtyMatches(p, req));
    const preferred = placement ? [placement.executante] : [];
    setMembers([...preferred, ...candidates.map((p) => p.id).filter((p) => !preferred.includes(p))]
      .slice(0, req.pessoas ?? preferred.length));
    setEditorOpen(true);
    requestAnimationFrame(() => document.getElementById("activity-editor")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  function change(source: WorkPlan | null = plan): PlanChange {
    if (!source) throw new Error("Planejamento não carregado.");
    return { revisao: source.revisao, requisitos: source.requisitos, blocos: source.blocos,
      indisponibilidades: source.indisponibilidades, motivo: "Atualização do planejamento", confirmar: false,
      atualizar_especialidades: specialtiesRefreshed, posicionamentos: source.posicionamentos ?? [] };
  }
  async function save(source: WorkPlan | null = plan) {
    if (!source) return;
    const sourceConflicts = conflictingBlocks(source);
    if (source.status === "confirmado" && sourceConflicts.size) { setError("Resolva os blocos vermelhos antes de alterar este planejamento."); return; }
    if (source.status === "confirmado" && source.posicionamentos?.length) {
      setError("Complete ou retire os cartões posicionados antes de salvar as alterações."); return;
    }
    setBusy(true); setError("");
    try {
      const saved = await saveWorkPlan(source.id, change(source));
      setPlan(saved); setDirty(false);
      setSpecialtiesRefreshed(false);
      setMessage(`Alterações salvas na revisão ${saved.revisao}.`);
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }
  async function suggest() {
    if (!plan) return;
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
  async function persistPlanTeam(team: WorkPlan["equipe"]) {
    if (!plan) return;
    const hasDraft = dirty;
    setBusy(true); setError("");
    try {
      const updated = await updateWorkPlanTeam(plan.id, plan.revisao, team);
      setPlan((current) => current ? {
        ...updated,
        ...(hasDraft ? {
          requisitos: current.requisitos, blocos: current.blocos,
          indisponibilidades: current.indisponibilidades, posicionamentos: current.posicionamentos,
        } : {}),
      } : updated);
      setDirty(hasDraft); setSpecialtiesRefreshed(false);
    } finally { setBusy(false); }
  }
  function beginPointer(event: PointerEvent<HTMLElement>, payload: DragPayload) {
    if (busy || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    suppressCardClick.current = false;
    activeDraggedOrder.current = payload.lote?.[0] ?? payload.ot;
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
    handleDrag.current = null; activeDraggedOrder.current = ""; setHandleDragging(false); clearDropTarget(); setInsertionTarget("");
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
        if (!target.dataset.day) { setError("Solte a OT em uma célula do cronograma com dia definido."); return; }
        selectOrder(payload.ot);
        assignBatch(person, payload.lote ?? [payload.ot], target.dataset.day, true);
      }
    } catch (failure) { setError(describeError(failure)); }
  }
  function drag(event: DragEvent, payload: DragPayload) {
    const batch = payload.lote ?? (!payload.bloco && checked.includes(payload.ot) ? checked : undefined);
    activeDraggedOrder.current = batch?.[0] ?? payload.ot;
    event.dataTransfer.setData("application/x-pcm", JSON.stringify({ ...payload, lote: batch }));
    event.dataTransfer.effectAllowed = payload.bloco ? "move" : "copy";
  }
  function drop(event: DragEvent, targetDay: string | undefined, person: string, beforeBlockId?: string) {
    event.preventDefault(); event.stopPropagation();
    clearDropTarget(); setInsertionTarget("");
    if (!plan || busy) return;
    try {
      const payload: unknown = JSON.parse(event.dataTransfer.getData("application/x-pcm"));
      if (!payload || typeof payload !== "object" || !("ot" in payload) || typeof payload.ot !== "string") throw new Error("Arraste uma OT ou um bloco desta bancada.");
      const block = "bloco" in payload && typeof payload.bloco === "string" ? payload.bloco : undefined;
      const source = "origem" in payload && typeof payload.origem === "string" ? payload.origem : undefined;
      if (!block) {
        const keys = "lote" in payload && Array.isArray(payload.lote) && payload.lote.every((k): k is string => typeof k === "string") ? payload.lote : [payload.ot];
        if (!targetDay) { setError("Solte a OT em uma célula do cronograma com dia definido."); return; }
        selectOrder(payload.ot);
        assignBatch(person, keys, targetDay, true); return;
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
      if (selectedPlacement) {
        assignBatch(selectedPlacement.executante, [selected], selectedPlacement.dia, true);
        setEditorOpen(false);
        return;
      }
      setEditorOpen(false);
      setMessage("Preparação mantida no rascunho. Arraste a OT para a célula do executante e do dia desejados no cronograma.");
      return;
    }
    const duration = Number(hours);
    if (!hours || !Number.isFinite(duration) || duration <= 0 || duration > 1000 || !day || !members.length) {
      setError("Informe dia, horas positivas (até 1000) e executantes."); return;
    }
    const block: Allocation = { id: blockId || crypto.randomUUID(), ot: selected, dia: day,
      inicio: 0, horas: duration, executantes: members };
    const related = plan.blocos.filter((b) => b.ot === selected && b.id !== blockId);
    const nextRequirement = { ...plan.requisitos[selected], pessoas: members.length };
    if (related.some((b) => weekStart(b.dia) !== weekStart(day))) {
      setError("Mantenha todos os blocos da OT na mesma semana."); return;
    }
    if (members.some((member) => !specialtyMatches(plan.pessoas.find((p) => p.id === member)!, nextRequirement)
      || ![day, ...related.map((b) => b.dia)].every((scheduledDay) => availableDay(plan, member, scheduledDay)))) {
      setError("A equipe precisa ser compatível com a especialidade e estar disponível em todos os dias da OT."); return;
    }
    const next = { ...plan, blocos: [...plan.blocos.filter((b) => b.id !== blockId)
      .map((item) => item.ot === selected ? { ...item, executantes: members } : item), block],
      requisitos: { ...plan.requisitos, [selected]: nextRequirement } };
    edit({ ...next, posicionamentos: pendingActivity(next, selected) ? plan.posicionamentos : plan.posicionamentos?.filter((p) => p.ot !== selected) });
    setBlockId(""); setMembers([]); setHours("");
    setEditorOpen(false);
      setMessage("Atividade incluída no dia. Salve as alterações para registrar este rascunho.");
    const finalPlan = { ...next, posicionamentos: pendingActivity(next, selected) ? plan.posicionamentos : plan.posicionamentos?.filter((p) => p.ot !== selected) };
    setPlan(finalPlan);
  }
  function postpone(key: string, confirmRemoval = true) {
    if (!plan) return;
    if (confirmRemoval && !window.confirm("Retirar todos os blocos desta OT? Ela voltará à carteira não alocada; registre o motivo na preparação e na revisão.")) return;
    edit({ ...plan, blocos: plan.blocos.filter((b) => b.ot !== key), posicionamentos: plan.posicionamentos?.filter((p) => p.ot !== key) });
    if (!confirmRemoval) setMessage(`${plan.ordens.find((order) => orderKey(order) === key)?.wonum ?? key} voltou à galeria de atividades.`);
  }
  async function createPdf() {
    if (!plan) return;
    setBusy(true); setError("");
    try {
      let saved = plan;
      if (dirty) {
        saved = await saveWorkPlan(plan.id, change(plan));
        setPlan(saved); setDirty(false); setSpecialtiesRefreshed(false);
      }
      await downloadSchedule(saved.id, saved.revisao);
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }
  async function sendPlanningToBma() {
    if (!plan || !firstPlannedPm) return;
    if (!window.confirm("Gravar no BMA as PMs (I/S) e corretivas (E) do cronograma? O BMA será acessado em segundo plano: datas planejadas e matrículas serão conferidas e ajustadas ao planejamento, com salvamento. Corretivas em WFSCH/WSCH também serão roteadas no workflow para PREPARED. OTs já planejadas são ignoradas.")) return;
    setBusy(true); setError(""); setBmaMonitorError("");
    try {
      let saved = plan;
      if (dirty) {
        saved = await saveWorkPlan(plan.id, change(plan));
        setPlan(saved); setDirty(false); setSpecialtiesRefreshed(false);
      }
      const { monitor_id, total } = await sendPlanningToBmaReader(saved.id);
      setBmaMonitor({ monitor_id, status: "starting", mode: "planning_send", message: "Abrindo BMA...",
        fields: [], stage: "starting", progress: 0, queue_total: total, current_order_index: 0,
        current_wonum: null, completed_wonums: [], failed_wonum: null, opened_wonum: null,
        processadas: 0, planejadas: 0, pendentes: 0, com_erro: 0, resultados: [] });
      setBmaMonitorId(monitor_id);
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }
  async function openInBma(wonum: string) {
    setError(""); setBmaMonitorError("");
    try {
      const { monitor_id } = await openOrderInBma(wonum);
      setBmaMonitor({ monitor_id, status: "starting", mode: "open_ot", message: "Abrindo BMA...", fields: [],
        stage: "starting", progress: 0, queue_total: 1, current_wonum: wonum });
      setBmaMonitorId(monitor_id);
    } catch (failure) { setError(describeError(failure)); }
  }
  async function stopBmaProgress() {
    try { setBmaMonitor(await stopBmaPageMonitor(bmaMonitorId)); }
    catch (failure) { setBmaMonitorError(describeError(failure)); }
  }
  function downloadBmaResults() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(bmaMonitor?.resultados ?? [], null, 2)], { type: "application/json" }));
    const link = Object.assign(document.createElement("a"), { href: url, download: `leitura-bma-${plan?.id ?? "planejamento"}.json` });
    link.click(); URL.revokeObjectURL(url);
  }
  function closeBmaProgress() { setBmaMonitorId(""); setBmaMonitor(null); setBmaMonitorError(""); }

  return <>
    <Head><title>Bancada de planejamento | Centro PCM</title></Head>
    <main className="pcm-workspace mx-auto min-h-screen w-full max-w-none space-y-5 p-4 lg:p-7">
      <header className="pcm-panel flex flex-wrap items-center justify-between gap-4 p-5">
        <div>
          <Link href="/planejamento/acompanhamento" className="mb-3 inline-flex items-center gap-2 text-xs text-sky-300"><ArrowLeft size={14} /> Acompanhamento</Link>
          <h1 className="text-2xl font-semibold text-white">Bancada de Planejamento PCM</h1>
          {plan && <><p className="mt-2 text-sm text-slate-400">{formatPlanningDate(plan.inicio)} a {formatPlanningDate(plan.fim)} · {plan.planejador} · <span className={displayedStatus === "confirmado" ? "font-semibold text-emerald-300" : "text-amber-200"}>{displayedStatus}</span> · revisão {plan.revisao}</p>
            <Link href={{ pathname: "/planejamento/ots", query: { setor: plan.setores } }} className="mt-2 inline-flex text-xs text-sky-300">Voltar ao Centro PCM</Link></>}
        </div>
        {plan && <div className="flex flex-wrap gap-2">
          <NfeReportButton />
          <Link href="/planejamento" className="pcm-small-button"><RefreshCw size={15} /> Atualizar banco pelo BMA</Link>
          <button className="pcm-small-button" disabled={busy} onClick={() => setTeamEditorOpen(true)}><UsersRound size={15} /> Editar mão de obra</button>
          <button className="pcm-small-button" disabled={busy} onClick={() => void refreshSpecialties()}><RefreshCw size={15} /> Reler especialidades do banco</button>
          <button className="pcm-primary-button" disabled={busy} onClick={() => void save()}><Save size={15} /> Salvar rascunho</button>
        </div>}
      </header>
      {error && <p role="alert" className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-4 text-sm text-rose-200">{error}</p>}
      {message && <p role="status" className="rounded-lg border border-sky-400/30 bg-sky-400/10 p-4 text-sm text-sky-200">{message}</p>}
      {teamEditorOpen && plan && <LaborPlanningModal inicio={plan.inicio} fim={plan.fim} setores={plan.setores} saved={plan.equipe}
        onLaborUpdate={() => {}} persistTeam={persistPlanTeam}
        onClose={() => setTeamEditorOpen(false)} onSave={(team) => {
          setTeamEditorOpen(false);
          setMessage(`Equipe deste planejamento atualizada: ${team.executantes.length} executante(s). A equipe padrão do Centro PCM não foi alterada.`);
        }} />}
      {!plan ? <p className="text-slate-400">{busy ? "Carregando planejamento..." : "Abra um planejamento pela carteira ou pelo acompanhamento."}</p> : <>
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Capacidade compartilhada">
          {[["Capacidade disponível", metrics?.capacity], ["Comprometido PM", metrics?.pm], ["Comprometido corretiva", metrics?.corrective], ["Saldo para encaixe", metrics?.remaining]].map(([label, value]) =>
            <div key={String(label)} className="pcm-panel p-4"><p className="text-xs text-slate-400">{label}</p><p className="mt-2 text-2xl font-semibold text-white">{formatNumber(typeof value === "number" ? value : null)} HH</p></div>)}
        </section>
        <section aria-label="Horas de PM e capacidade por especialidade" className="pcm-panel min-w-0 overflow-hidden p-4">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="pcm-title">PM · HH por especialidade</h2>
            <p className="text-[11px] text-slate-400">Demanda BMA (`laborhrs`) ou estimativa disponível · capacidade da equipe em dias × 8 h, descontadas indisponibilidades.</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-xs">
              <thead><tr className="border-b border-white/10 text-slate-400">
                <th className="p-2 font-medium">Especialidade exigida</th><th className="p-2 text-right font-medium">OTs PM</th>
                <th className="p-2 text-right font-medium">Demanda PM (HH)</th><th className="p-2 text-right font-medium">Capacidade (HH)</th>
                <th className="p-2 text-right font-medium">Comprometido (HH)</th><th className="p-2 text-right font-medium">Saldo livre (HH)</th>
                <th className="p-2 text-right font-medium">Sem estimativa</th>
              </tr></thead>
              <tbody>{specialtyRows.map((row) => <tr key={`${row.orgid}:${row.funcao || "sem-funcao"}`} className="border-b border-white/5 last:border-0">
                <th scope="row" className="p-2 font-medium text-slate-200">{row.nome}<span className="mt-1 block text-[10px] text-slate-500">{row.funcao ? `${row.orgid}/${row.funcao}` : "Especialidade não definida"}</span></th>
                <td className="p-2 text-right tabular-nums text-slate-300">{row.ordensPM}</td>
                <td className="p-2 text-right tabular-nums text-sky-200">{formatNumber(row.horasPM)}</td>
                <td className="p-2 text-right tabular-nums text-slate-300">{formatNumber(row.capacidade)}</td>
                <td className="p-2 text-right tabular-nums text-slate-300">{formatNumber(row.comprometido)}</td>
                <td className={`p-2 text-right tabular-nums ${row.saldo < 0 ? "text-rose-300" : "text-emerald-200"}`}>{formatNumber(row.saldo)}</td>
                <td className="p-2 text-right tabular-nums text-amber-200">{row.estimativasPendentes}</td>
              </tr>)}
                {!specialtyRows.length && <tr><td colSpan={7} className="p-3 text-slate-500">Sem equipe ou especialidades cadastradas neste plano.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[10px] text-slate-500">O saldo livre desconta blocos PM e corretivos alocados. Horas sem estimativa não entram como zero na leitura das pendências.</p>
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
        <fieldset disabled={busy} className="min-w-0 space-y-5 disabled:opacity-60">
          <section className="pcm-allocation-dock sticky top-0 z-40 mx-auto w-[90vw] rounded-xl border border-white/10 p-2 backdrop-blur-xl" aria-label="Controles e galeria de atividades">
            <div className="flex flex-wrap items-center gap-2">
              <nav className="flex min-w-0 flex-nowrap gap-1 overflow-x-auto" aria-label="Fluxo de alocação">
                {([ ["pm", "1 · Planejar PM", "PM"], ["corretiva", "2 · Encaixar corretiva", "Corretiva"] ] as const).map(([key, label, compact]) =>
                  <button key={key} className={view === key ? "pcm-primary-button min-h-8 shrink-0 px-2 py-1 text-[11px] sm:px-2.5 sm:text-xs" : "pcm-small-button min-h-8 shrink-0 px-2 py-1 text-[11px] sm:px-2.5 sm:text-xs"} disabled={busy || key === "corretiva" && !hasPlannedPm} title={key === "corretiva" && !hasPlannedPm ? "Planeje ao menos uma PM para liberar corretivas." : undefined} aria-pressed={view === key} onClick={() => { setView(key); setLimit(60); }}><span className="sm:hidden">{compact}</span><span className="hidden sm:inline">{label}</span></button>) }
                <button type="button" className="pcm-small-button min-h-8 shrink-0 px-2 py-1 text-[11px] sm:px-2.5 sm:text-xs" disabled={busy || !hasPlannedPm} title={!hasPlannedPm ? "Planeje ao menos uma PM para liberar o envio." : "Gravar no BMA datas e matrículas das PMs I/S do cronograma."} onClick={() => void sendPlanningToBma()}>
                  <Send size={14} /><span className="sm:hidden">3 · BMA</span><span className="hidden sm:inline">3 · Enviar Planejamento</span>
                </button>
                <button type="button" aria-label="4 · Criar PDF" title={busy ? "Aguarde a operação atual terminar." : !hasPlannedPm ? "Planeje ao menos uma PM para criar o PDF." : dirty ? "O rascunho será salvo antes de baixar o PDF." : "Baixar o PDF do planejamento salvo."}
                  className="pcm-small-button min-h-8 shrink-0 px-2 py-1 text-[11px] sm:px-2.5 sm:text-xs" disabled={busy || !hasPlannedPm} onClick={() => void createPdf()}>
                  <Download size={14} /><span className="sm:hidden">4 · PDF</span><span className="hidden sm:inline">4 · Criar PDF</span>
                </button>
              </nav>
              <button className="pcm-small-button ml-auto min-h-8 shrink-0 px-2 py-1" aria-label={`Sugerir encaixe ${view === "pm" ? "PM" : "corretiva"}`} title={`Sugerir encaixe ${view === "pm" ? "PM" : "corretiva"}`} disabled={busy} onClick={() => void suggest()}><Sparkles size={14} /><span className="hidden sm:inline">Sugerir</span></button>
              <details id="portfolio-filters" className="relative shrink-0">
                <summary className="pcm-small-button min-h-8 cursor-pointer list-none px-2 py-1"><SlidersHorizontal size={14} /><span className="hidden sm:inline">Filtros</span></summary>
                <div className="absolute right-0 top-full z-50 grid w-[min(88vw,28rem)] gap-2 rounded-lg border border-white/15 bg-[#102235] p-3 shadow-xl sm:grid-cols-2">
                  <input className={`${input} h-8 py-1 text-xs sm:col-span-2`} aria-label="Buscar atividade" placeholder="OT, descrição ou local" value={search} onChange={(e) => { setSearch(e.target.value); setLimit(60); }} />
                  <select className={`${input} h-8 py-1 text-xs`} aria-label="Filtrar tipo de OT" value={categoryFilter} onChange={(e) => { setCategoryFilter(e.target.value); setLimit(60); }}>
                    <option value="">Todos os tipos</option><option value="pm1">PM1</option><option value="pm2">PM2</option><option value="pm3">PM3</option><option value="outras-pm">Outras PM</option><option value="corretiva">Corretiva</option>
                  </select>
                  <select className={`${input} h-8 min-w-0 py-1 text-xs`} aria-label="Filtrar carteira por especialidade" value={specialtyFilter} onChange={(e) => { setSpecialtyFilter(e.target.value); setLimit(60); }}>
                    <option value="">Todas as especialidades</option><option value="indefinida">Especialidade não definida</option><option value="qualquer">Qualquer especialidade (Todos)</option>
                    {specialtyOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                  </select>
                  <button type="button" className="pcm-small-button min-h-8 justify-self-start px-2 py-1 sm:col-span-2" onClick={() => { setSearch(""); setCategoryFilter(""); setSpecialtyFilter(""); }}>Limpar filtros</button>
                </div>
              </details>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/10 pt-2 text-[11px]">
              <label className="flex items-center gap-2 text-sky-200"><input type="checkbox" aria-label="Selecionar todas as OTs filtradas"
                checked={visible.length > 0 && checked.length === visible.length} disabled={!visible.length}
                ref={(element) => { if (element) element.indeterminate = checked.length > 0 && checked.length < visible.length; }}
                onChange={(e) => markOrders(visible.map(orderKey), e.target.checked)} /> Selecionar todas ({visible.length})</label>
              <span className="text-slate-400">{checked.length} selecionada(s)</span>
              <div draggable={!busy && checked.length > 0} onDragStart={(e) => { if (checked[0]) drag(e, { ot: checked[0], lote: checked }); }}
                className={`flex cursor-grab items-center gap-1 rounded border border-dashed px-2 py-1 text-sky-200 ${checked.length ? "border-sky-400/40 bg-sky-400/5" : "border-white/10 text-slate-500"}`}>
                <GripVertical size={13} /> Arrastar lote
              </div>
              <span className="ml-auto text-slate-400">Carteira {view.toUpperCase()} · {visible.length} pendentes</span>
              <div className="flex gap-1">
                <button type="button" aria-label="Rolar galeria para a esquerda" title="Anterior" className="pcm-small-button min-h-7 px-1.5 py-1" onClick={() => gallery.current?.scrollBy({ left: -320, behavior: "smooth" })}><ChevronLeft size={14} /></button>
                <button type="button" aria-label="Rolar galeria para a direita" title="Próxima" className="pcm-small-button min-h-7 px-1.5 py-1" onClick={() => gallery.current?.scrollBy({ left: 320, behavior: "smooth" })}><ChevronRight size={14} /></button>
              </div>
            </div>
            <div ref={gallery} className="mt-2 flex h-[212px] snap-x snap-mandatory gap-2 overflow-x-auto overflow-y-hidden overscroll-x-contain pb-1" aria-label="Galeria horizontal de OTs">
              {visible.slice(0, limit).map((order, index) => {
                const key = orderKey(order), req = plan.requisitos[key], done = allocatedDuration(plan, key);
                const missing = missingPlanningData(order);
                const targetStart = dayMonth(cellText(order, "targstartdate"));
                const targetEnd = dayMonth(cellText(order, "targcompdate"));
                return <div key={key} style={{ animationDelay: `${Math.min(index, 10) * 35}ms` }} className="pcm-activity-card relative flex h-min w-[min(180px,82vw)] max-w-[min(82vw,180px)] shrink-0 snap-start items-start gap-1.5">
                  <input className="mt-2 shrink-0" type="checkbox" aria-label={`Planejar ${order.wonum}`} checked={req.selecionada ?? false} onChange={(e) => markOrders([key], e.target.checked)} />
                  <button type="button" draggable={!busy} onDragStart={(e) => drag(e, { ot: key })} onDragEnd={() => { activeDraggedOrder.current = ""; clearDropTarget(); }}
                    onClick={() => { selectOrder(key); setEditorOpen(false); }} title={`${order.wonum} · ${cellText(order, "description")}${missing.length ? ` · Dados BMA ausentes: ${missing.join(", ")}` : ""}`}
                    className={`relative flex aspect-square h-auto w-[min(160px,78vw)] max-w-[min(78vw,160px)] flex-none flex-col overflow-hidden rounded-md border p-2 pr-6 text-left ${missing.length ? "border-rose-400/80 bg-rose-400/10" : selected === key ? "border-sky-400 bg-sky-400/10" : "border-white/10 bg-white/[.02]"}`}>
                    <span className="w-max max-w-full whitespace-nowrap text-[11px] font-semibold leading-tight text-sky-200">{order.wonum} · {activityMode(order).toUpperCase()}</span>
                    <span className="mt-1 block min-h-0 flex-1 overflow-hidden break-words text-[10px] leading-tight text-slate-300">{cellText(order, "description")}</span>
                    <span className="mt-1 block w-full shrink-0 truncate text-[9px] leading-tight text-slate-400">Início: {targetStart} · Fim: {targetEnd}</span>
                    <span className="mt-1 block w-full truncate text-[10px] font-medium text-amber-200" title={`Status da OT: ${order.status || "Não informado"}`}>Status: {order.status || "Não informado"}</span>
                    <span className="sr-only">{formatNumber(req.duracao)} horas · {req.pessoas ?? "?"} pessoa(s) · {activityCategory(order)}</span>
                    <span data-drag-ot={key} aria-label={`Arrastar ${order.wonum} para pessoa e dia`} title="Clique, segure e arraste até a célula de pessoa e dia"
                      onPointerDown={(e) => beginPointer(e, { ot: key, lote: checked.includes(key) ? checked : [key] })}
                      onPointerMove={movePointer} onPointerUp={finishPointer} onPointerCancel={cancelPointer}
                      onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }} onClick={(e) => e.stopPropagation()}
                      className="absolute right-0.5 top-0.5 touch-none select-none cursor-grab rounded p-1 text-sky-200 hover:bg-sky-400/20 active:cursor-grabbing"><GripVertical size={13} /></span>
                  </button>
                  <button type="button" aria-label={`Editar OT ${order.wonum}`} title="Preparar / editar atividade"
                    className="absolute bottom-0.5 right-0.5 rounded p-1 text-sky-200 hover:bg-sky-400/20" onClick={() => openEditor(key)}><Pencil size={12} /></button>
                </div>;
              })}
              {!visible.length && <p className="self-center px-3 text-sm text-slate-500">Nenhuma OT nesta seleção.</p>}
              {visible.length > limit && <button className="pcm-small-button my-auto shrink-0" onClick={() => setLimit(limit + 60)}>Mostrar mais atividades</button>}
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
                  <h3 className="text-sm font-semibold text-white">{blockId ? "Editar bloco selecionado" : "Preparar atividade"}</h3>
                  <div className="my-3 grid gap-3 sm:grid-cols-2">
                    {blockId ? <><label className="text-xs text-slate-400">Dia<select className={`${input} mt-1`} value={day} onChange={(e) => setDay(e.target.value)}>{days.map((d) => <option key={d} value={d}>{formatPlanningDate(d)}</option>)}</select></label>
                    <label className="text-xs text-slate-400">Horas da atividade neste dia<input className={`${input} mt-1`} type="number" min=".01" max="1000" step=".25" value={hours} onChange={(e) => setHours(e.target.value)} /></label></>
                      : <p className="sm:col-span-2 text-xs text-slate-400">O dia e o executante serão definidos ao arrastar a OT para a célula correspondente no cronograma.</p>}
                  </div>
                  <p className="mb-2 text-xs text-slate-500">A quantidade simultânea acompanha os executantes selecionados. O dia do arraste inicia o planejamento; horas restantes podem avançar para os dias seguintes da mesma semana.</p>
                  <div className="grid gap-2 sm:grid-cols-2">{plan.pessoas.filter((p) => specialtyMatches(p, requirement)).map((p) =>
                    <label key={p.id} className="flex gap-2 text-xs text-slate-300"><input type="checkbox" aria-label={`Executante ${p.nome}`} checked={members.includes(p.id)} onChange={(e) => {
                      const next = e.target.checked ? [...members, p.id] : members.filter((m) => m !== p.id);
                      setMembers(next);
                      if (!plan.blocos.some((b) => b.ot === selected)) editRequirement({ pessoas: next.length || null });
                    }} /> {p.nome} · {availableDay(plan, p.id, day) ? `${formatNumber(weeklyBalance(plan, p.id, day).remaining)} h de saldo semanal` : "Indisponível"}</label>)}</div>
                  <div className="mt-4 flex flex-wrap gap-2"><button type="button" onClick={manualBlock} className="pcm-primary-button">{blockId ? "Aplicar edição do bloco" : selectedPlacement ? "Aplicar no cronograma" : "Fechar preparação"}</button>
                    {blockId && <button className="pcm-small-button" onClick={() => { setBlockId(""); setMembers([]); setHours(""); }}>Cancelar edição</button>}
                    {blockId && <button className="pcm-small-button text-rose-300" onClick={() => {
                      edit({ ...plan, blocos: plan.blocos.filter((b) => b.id !== blockId) }); setBlockId(""); setMembers([]); setHours("");
                    }}>Remover bloco</button>}
                    <button type="button" onClick={() => postpone(selected)} className="pcm-small-button text-amber-300">Retirar OT para reencaixe</button></div>
                </div>
                <details><summary className="cursor-pointer text-xs text-sky-300">Instruções e dados originais do BMA</summary><div className="mt-3"><OrderDetails order={currentOrder} /></div></details>
              </>}
            </section></div>}
          <section id="integrated-schedule" className="pcm-panel mx-auto my-4 w-[90vw] min-w-0 overflow-visible p-4" aria-label="Grade de capacidade por integrante e dia">
            <h2 className="pcm-title"><CalendarDays size={18} /> Cronograma integrado · PM + corretiva</h2>
            <p className="my-2 text-xs text-slate-400">Arraste uma OT para a célula do executante e do dia desejados. Esse dia inicia o planejamento; eventual saldo segue pelos dias posteriores da mesma semana. Arraste uma alocação para mudar o dia ou integrante; clique para editar o bloco.</p>
            <div id="schedule-scroll" className="h-min overflow-visible">
              <table className="w-full border-separate border-spacing-2 text-left text-xs">
                <thead className="sticky top-0 z-20 bg-[#102235]"><tr><th className="sticky left-0 z-30 min-w-40 bg-[#102235] p-2 align-top">
                  <span className="mb-2 block">Executante / especialidade</span>
                  <details className="relative text-left">
                    <summary aria-label="Filtrar executantes do cronograma" className="cursor-pointer list-none rounded border border-white/15 bg-[#081729] px-2 py-2 text-xs font-normal text-sky-100 hover:border-sky-400/50">
                      {executantFilter === null ? `Todos os executantes (${plan.pessoas.length})` : `${executantFilter.length} de ${plan.pessoas.length} executantes`}
                    </summary>
                    <div className="absolute left-0 top-full z-50 mt-1 max-h-80 w-80 max-w-[80vw] overflow-y-auto rounded-lg border border-white/15 bg-[#102235] p-2 shadow-xl">
                      <label className="mb-2 flex cursor-pointer items-center gap-2 border-b border-white/10 px-2 py-2 text-xs font-semibold text-white">
                        <input type="checkbox" aria-label="Selecionar todos os executantes" checked={executantFilter === null || executantFilter.length === plan.pessoas.length}
                          onChange={(event) => setExecutantFilter(event.target.checked ? null : [])} />
                        Todos ({plan.pessoas.length})
                      </label>
                      {plan.pessoas.map((person) => {
                        const selectedPeople = executantFilter ?? plan.pessoas.map((item) => item.id);
                        const checked = selectedPeople.includes(person.id);
                        return <label key={person.id} className="flex cursor-pointer items-start gap-2 rounded px-2 py-2 text-xs text-slate-200 hover:bg-white/5">
                          <input type="checkbox" aria-label={`Selecionar executante ${person.nome}`} checked={checked} onChange={(event) => {
                            const next = event.target.checked ? [...selectedPeople, person.id] : selectedPeople.filter((id) => id !== person.id);
                            setExecutantFilter(next.length === plan.pessoas.length ? null : next);
                          }} />
                          <span className="min-w-0 flex-1"><span className="block font-medium">{person.nome} · {person.funcao_descricao}</span>
                            {weeks.map((week) => {
                              const balance = weeklyBalance(plan, person.id, week);
                              const percent = balance.capacity ? Math.round(balance.load / balance.capacity * 100) : 0;
                              return <span key={week} className="mr-2 mt-1 inline-block text-[10px] text-sky-200">{formatPlanningDate(week)}: {percent}%</span>;
                            })}
                          </span>
                        </label>;
                      })}
                    </div>
                  </details>
                </th>{days.map((d) => <th key={d} className="min-w-28 p-2">{formatPlanningDate(d)}</th>)}</tr></thead>
                <tbody>{plan.pessoas.filter((person) => executantFilter === null || executantFilter.includes(person.id)).map((person) => <tr key={person.id}>
                  <th data-person={person.id} className={`sticky left-0 z-10 rounded-lg border border-dashed bg-[#102235] p-2 align-top font-normal ${dropTarget === `${person.id}:nome` ? "border-sky-300 ring-2 ring-sky-300/40" : "border-sky-400/30"}`}
                    onDragOver={(e) => { if (!busy) { e.preventDefault(); highlightDropTarget(person.id); } }} onDrop={(e) => drop(e, undefined, person.id)}>
                    <p className="font-semibold text-white">{person.nome}</p><p className="mt-1 text-slate-500">{person.funcao_descricao}</p>
                    <p className="mt-2 text-[11px] text-sky-300">OTs: solte em uma célula de dia · blocos: solte aqui para trocar executante</p>
                    {weeks.map((week) => {
                      const balance = weeklyBalance(plan, person.id, week);
                      const percent = balance.capacity ? Math.round(balance.load / balance.capacity * 100) : 0;
                      return <p key={week} className={`mt-1 ${balance.remaining < -1e-6 ? "text-rose-300" : "text-slate-400"}`}>Semana {formatPlanningDate(week)}: {percent}% programada · {formatNumber(balance.load)}/{formatNumber(balance.capacity)} h · saldo {formatNumber(balance.remaining)} h</p>;
                    })}
                  </th>
                  {days.map((d) => {
                    const available = availableDay(plan, person.id, d), load = dayLoad(plan, person.id, d);
                    const pendingLoad = provisionalDayLoad(plan, person.id, d), displayedLoad = load + pendingLoad;
                    const overloaded = weeklyBalance(plan, person.id, d).remaining < -1e-6;
                    const dailyCapacity = available ? 8 : 0;
                    const dailyRemaining = Math.max(0, dailyCapacity - displayedLoad);
                    const percentage = dailyCapacity ? displayedLoad / dailyCapacity * 100 : 0;
                    return <td key={d} aria-label={`${person.nome} · ${formatPlanningDate(d)}`} data-person={person.id} data-day={d}
                      onDragOver={(e) => { if (!busy && available) { e.preventDefault(); highlightDropTarget(person.id, d); } }}
                      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) clearDropTarget(); }}
                      onDrop={(e) => drop(e, d, person.id)}
                      className={`rounded-lg border p-2 align-top ${dropTarget === `${person.id}:${d}`
                        ? dropTargetTone === "target" ? "border-emerald-300 bg-emerald-400/20 ring-2 ring-emerald-300/40" : dropTargetTone === "outside" ? "border-rose-300 bg-rose-400/20 ring-2 ring-rose-300/40" : "border-sky-300 bg-sky-400/20 ring-2 ring-sky-300/40"
                        : !available ? "border-white/5 bg-white/[.01] opacity-60" : overloaded ? "border-rose-400/60 bg-rose-400/10" : "border-white/10 bg-white/[.03]"}`}>
                      {dropTarget === `${person.id}:${d}` && <p className={`mb-2 font-semibold ${dropTargetTone === "target" ? "text-emerald-200" : dropTargetTone === "outside" ? "text-rose-200" : "text-sky-200"}`}>{dropTargetTone === "target" ? "Data prevista da OT" : dropTargetTone === "outside" ? "Fora da data prevista" : "Soltar para associar a este executante e dia"}</p>}
                      <div className="mb-2" title={`Referência diária: ${dailyCapacity} h. Acima de 8 h é permitido com saldo semanal. ${pendingLoad ? `${formatNumber(pendingLoad)} h são previsão de cartão pendente e não reservam capacidade até completar a preparação.` : "Cartões pendentes sem duração não entram na previsão."}${overloaded ? " Capacidade semanal excedida." : ""}`}>
                        <div className={`mb-1 flex items-center justify-between gap-1 text-[10px] leading-tight tabular-nums ${overloaded ? "text-rose-300" : displayedLoad > dailyCapacity || pendingLoad ? "text-amber-200" : "text-slate-400"}`}>
                          <span>{available ? `${formatNumber(percentage)}%` : "Indisp."}</span>
                          <span>{pendingLoad ? `${load ? `${formatNumber(load)} h + ` : ""}${formatNumber(pendingLoad)} h prev. · ${formatNumber(dailyRemaining)} h disp.` : `${formatNumber(load)} h ocup. · ${formatNumber(dailyRemaining)} h disp.`}</span>
                        </div>
                        <div role="progressbar" aria-label={`Carga do dia de ${person.nome} em ${formatPlanningDate(d)}`}
                          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100, percentage)}
                          aria-valuetext={`${available ? `${formatNumber(percentage)}%` : "Indisponível"} · ${formatNumber(load)} h alocadas · ${formatNumber(pendingLoad)} h previstas, ainda não reservadas · ${formatNumber(dailyRemaining)} h disponíveis após previsão`}
                          className="h-1 overflow-hidden rounded bg-white/10">
                          <div className="flex h-full" style={{ width: `${dailyCapacity ? Math.min(100, percentage) : displayedLoad > 0 ? 100 : 0}%` }}>
                            {load > 0 && <span className={`h-full ${overloaded ? "bg-rose-400" : load > dailyCapacity ? "bg-amber-400" : "bg-sky-400"}`}
                              style={{ width: `${displayedLoad ? Math.min(100, load / displayedLoad * 100) : 0}%` }} />}
                            {pendingLoad > 0 && <span className="h-full bg-amber-300" style={{ width: `${displayedLoad ? Math.min(100, pendingLoad / displayedLoad * 100) : 0}%` }} />}
                          </div>
                        </div>
                      </div>
                      {(plan.posicionamentos ?? []).filter((p) => p.executante === person.id && p.dia === d).map((p) => {
                        const order = plan.ordens.find((o) => orderKey(o) === p.ot);
                        const missing = order ? missingPlanningData(order) : [];
                        return <div key={p.ot} data-placement-ot={p.ot} title={missing.length ? `Dados BMA ausentes: ${missing.join(", ")}` : "Dados/horas pendentes; clique para editar."} className={`group relative mb-2 rounded border p-2 text-amber-100 ${missing.length ? "border-rose-400 bg-rose-400/10" : "border-amber-400/60 bg-amber-400/10"}`}>
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
                        const missing = order ? missingPlanningData(order) : [];
                        const complete = activityPlanningComplete(plan, b.ot);
                        const sent = order ? bmaStatus[order.wonum] : undefined;
                        const badge = sent && BMA_BADGES[sent.situacao];
                        const plannedInBma = !!sent && ["planejada", "ja_planejada"].includes(sent.situacao);
                        return <div key={b.id} className="group relative mb-2">
                          <button type="button" draggable={!busy} onDragStart={(e) => drag(e, { ot: b.ot, bloco: b.id, origem: person.id })}
                          onPointerDown={(e) => beginPointer(e, { ot: b.ot, bloco: b.id, origem: person.id })}
                          onPointerMove={movePointer} onPointerUp={finishPointer} onPointerCancel={cancelPointer}
                          data-schedule-block={b.id}
                          onDragOver={(e) => { if (!busy) { e.preventDefault(); e.stopPropagation(); setInsertionTarget(`${person.id}:${b.id}`); } }}
                          onDragLeave={() => setInsertionTarget("")}
                          onDragEnd={() => { setInsertionTarget(""); setDropTarget(""); }}
                          onDrop={(e) => drop(e, d, person.id, b.id)}
                          title={`${formatNumber(b.horas)} h neste dia · ${b.executantes.length} pessoa(s)${conflicts.has(b.id) ? " · Capacidade semanal excedida" : ""}${missing.length ? ` · Dados BMA ausentes: ${missing.join(", ")}` : ""}${complete ? " · Alocação completa" : ""}. Clique para editar.`}
                          onClick={() => { if (suppressCardClick.current) { suppressCardClick.current = false; return; } openEditor(b.ot); setBlockId(b.id); setDay(b.dia); setHours(String(b.horas)); setMembers(b.executantes); }}
                          className={`block w-full touch-none cursor-grab rounded border p-2 pr-7 text-left active:cursor-grabbing ${plannedInBma ? "pb-8" : ""} ${insertionTarget === `${person.id}:${b.id}` ? "border-t-4 border-t-sky-300 ring-2 ring-sky-300/40" : ""} ${conflicts.has(b.id) ? "border-rose-400 bg-rose-400/20 text-rose-100" : complete ? "border-emerald-400 bg-emerald-400/10 text-emerald-100" : missing.length ? "border-rose-400 bg-rose-400/10 text-rose-100" : order && activityMode(order) === "pm" ? "border-sky-400/25 bg-sky-400/10 text-sky-100" : "border-amber-400/25 bg-amber-400/10 text-amber-100"}`}>
                          <strong>{order?.wonum} - {order && activityMode(order).toUpperCase()}</strong>
                          <span className="mt-1 block">{order && cellText(order, "description")}</span>
                          {badge && <span title={`${sent.erro ?? badge[0]} · ${new Date(sent.registrado_em).toLocaleString("pt-BR")}`}
                            className={`mt-1 inline-block rounded border px-1.5 py-0.5 text-[10px] font-semibold ${badge[1]}`}>{badge[0]}</span>}
                          </button>
                          {order && plannedInBma && <button type="button" aria-label={`Abrir OT ${order.wonum} no BMA`} title="Abrir no BMA (Rastrear Ordem de Trabalho) somente para consulta"
                            className="absolute bottom-1 right-1 z-10 inline-flex items-center gap-1 rounded border border-white/15 bg-[#081729] px-1.5 py-0.5 text-[10px] text-sky-200 hover:bg-sky-400/20"
                            onClick={() => void openInBma(order.wonum)}><ExternalLink size={11} /> Abrir</button>}
                          <button type="button" aria-label={`Devolver OT ${order?.wonum ?? b.ot} à galeria`} title="Cancelar alocação e devolver à galeria"
                            className="absolute right-1 top-1 z-10 rounded p-1 text-slate-300 hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-300"
                            onClick={() => postpone(b.ot, false)}><X size={13} /></button>
                        </div>;
                      })}
                    </td>;
                  })}
                </tr>)}</tbody>
              </table>
            </div>
          </section>
        </fieldset>
        {!!suggestions.length && <details open className="pcm-panel p-4"><summary className="cursor-pointer text-sm text-amber-200">Pendências da última distribuição / sugestão ({suggestions.length})</summary><ul className="mt-3 max-h-60 space-y-1 overflow-y-auto text-xs text-slate-400">{suggestions.map((s, i) => <li key={i}>{s}</li>)}</ul></details>}
      </>}
      {handleDragging && <div className="pointer-events-none fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-sky-300 bg-[#081729] px-5 py-3 text-sm text-sky-100 shadow-xl">Arrastando OT · solte na célula do executante e dia</div>}
      {bmaMonitorId && <div role="dialog" aria-modal="true" aria-labelledby="bma-progress-title" className="fixed inset-0 z-[100] grid place-items-center bg-black/70 p-4">
        <section className="pcm-panel w-full max-w-lg space-y-5 p-5">
          <div className="flex items-start gap-3">
            {bmaMonitorError || bmaMonitor?.status === "failed" ? <AlertCircle size={21} className="mt-0.5 shrink-0 text-rose-300" />
              : bmaMonitor?.progress === 100 ? <CheckCircle2 size={21} className="mt-0.5 shrink-0 text-emerald-300" />
                : <LoaderCircle size={21} className="mt-0.5 shrink-0 animate-spin text-sky-300" />}
            <div className="min-w-0 flex-1">
              <h2 id="bma-progress-title" className="text-base font-semibold text-white">{bmaMonitor?.mode === "open_ot"
                ? bmaMonitorError || bmaMonitor.status === "failed" ? "Não foi possível abrir a OT" : `Abrir OT ${bmaMonitor.current_wonum ?? ""} no BMA`
                : bmaMonitorError || bmaMonitor?.status === "failed" ? "Envio ao BMA interrompido" : "Enviar planejamento ao BMA"}</h2>
              <p role="status" className="mt-1 text-sm text-slate-300">{bmaMonitorError || bmaMonitor?.message || "Abrindo BMA..."}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-label="Progresso da leitura no BMA" aria-valuenow={bmaMonitor?.progress ?? 0} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full rounded-full bg-sky-400 transition-[width] duration-500" style={{ width: `${bmaMonitor?.progress ?? 0}%` }} />
            </div>
            <span className="w-10 text-right text-xs tabular-nums text-slate-300">{bmaMonitor?.progress ?? 0}%</span>
          </div>
          {bmaMonitor?.mode === "planning_send" && <>
            <dl className="grid grid-cols-4 gap-2 text-center text-xs">
              <div className="rounded-lg border border-white/10 p-2"><dt className="text-slate-400">Processadas</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-white">{bmaMonitor.processadas ?? 0}/{bmaMonitor.queue_total ?? 0}</dd></div>
              <div className="rounded-lg border border-white/10 p-2"><dt className="text-slate-400">Planejadas</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-emerald-200">{bmaMonitor.planejadas ?? 0}</dd></div>
              <div className="rounded-lg border border-white/10 p-2"><dt className="text-slate-400">Planejador</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-amber-200">{bmaMonitor.pendentes ?? 0}</dd></div>
              <div className="rounded-lg border border-white/10 p-2"><dt className="text-slate-400">Com erro</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-rose-300">{bmaMonitor.com_erro ?? 0}</dd></div>
            </dl>
            {!!bmaMonitor.resultados?.some((r) => r.erro) && <ul className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-white/10 p-2 text-xs">
              {bmaMonitor.resultados.filter((r) => r.erro).map((r) => <li key={r.numero_ot} className={["planejada", "ja_planejada"].includes(r.situacao_consulta) ? "text-sky-200" : r.situacao_consulta === "pendente_planejador" ? "text-amber-200" : "text-rose-200"}>
                <strong>{r.numero_ot}</strong>: {r.erro}</li>)}
            </ul>}
          </>}
          <div className="flex flex-wrap justify-end gap-2">
            {!!bmaMonitor?.resultados?.length && <button type="button" className="pcm-small-button" onClick={downloadBmaResults}><Download size={14} /> Baixar JSON</button>}
            {bmaMonitor?.mode === "planning_send" && ["starting", "monitoring"].includes(bmaMonitor.status) &&
              <button type="button" className="pcm-small-button text-amber-200" onClick={() => void stopBmaProgress()}>Interromper</button>}
            {(bmaMonitor?.progress === 100 || bmaMonitor?.status === "failed" || bmaMonitorError || bmaMonitor?.status === "stopped") &&
              <button type="button" className="pcm-small-button" onClick={closeBmaProgress}>Fechar</button>}
          </div>
        </section>
      </div>}
    </main>
  </>;
}
