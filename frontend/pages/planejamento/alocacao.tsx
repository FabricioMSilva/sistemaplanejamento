import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from "react";
import { AlertCircle, ArrowLeft, ArrowRight, CheckCircle2, Cloud, Clock3, Database, Download, ExternalLink, GripVertical, Import, LoaderCircle, RefreshCw, Save, Send, Sparkles, CalendarDays, Undo2, UserPlus, Pencil, UsersRound, X, SlidersHorizontal, ChevronLeft, ChevronRight } from "lucide-react";
import {
  addOrdersToPlan, applyBmaPlanningImport, downloadPersonSchedule, downloadSchedule, getBmaPageMonitor, getBmaSendStatus, getSchedulePdf, getWorkPlan, importPlanningFromBma, openOrderInBma, orderKey, refreshPlanOrders, saveWorkPlan, sendPlanningToBmaReader, stopBmaPageMonitor,
  refreshPlanSpecialties, suggestWorkPlan,
  type Allocation, type BmaPageMonitor, type BmaSendStatus, type BmaPlanningResult, type PlanChange, type Requirement, type WorkPlan,
} from "@/services/pcm";
import { listarOrdensTrabalho, obterSincronizacao, sincronizarOrdensTrabalho } from "@/services/api";
import LaborPlanningModal from "@/components/LaborPlanningModal";
import PlanningWorkflowSteps from "@/components/PlanningWorkflowSteps";
import { cellText, hasExistingPlanningInfo, isCorrectiveAvailable, normalize } from "@/utils/orderFilters";
import { daysBetween, formatNumber, localDate } from "@/utils/pcmDashboard";
import { formatPlanningDate } from "@/utils/laborPlanning";
import { activityMode, activityCategory, activityDateConstraintError, activityDateStatus, activityDateWarning, activityPlanningComplete, addLaborHelper, allocatedDuration, availableDay, conflictingBlocks, dayLoad, isGalleryBmaStatus, laborHelperCandidates, provisionalDayLoad, distributeBatch, pendingActivity, prepareDraggedOrder, returnOrderToPortfolio, weeklyBalance, weekStart, resequenceWeek } from "@/utils/workPlanning";
import OrderDetails from "@/components/OrderDetails";
import { matchesOrderSpecialty, missingPlanningData, orderSpecialties, plannedLabor, preparationRequirements, underAllocatedPreparationOrders } from "@/utils/plannedLabor";

const input = "w-full rounded-lg border border-white/15 bg-[#081729] p-2 text-sm text-white";
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
const dayMonthRange = (startValue: string, endValue: string) => {
  const start = localDate(startValue), end = localDate(endValue);
  const includeYear = !!start && !!end && start.slice(0, 4) !== end.slice(0, 4);
  const format = (day: string | null) => {
    if (!day) return "—";
    return includeYear ? `${day.slice(8, 10)}/${day.slice(5, 7)}/${day.slice(0, 4)}`
      : `${day.slice(8, 10)}/${day.slice(5, 7)}`;
  };
  return { start: format(start), end: format(end) };
};

export default function AllocationPage({ planId }: { planId?: string } = {}) {
  const router = useRouter();
  const id = planId ?? (typeof router.query.plano === "string" ? router.query.plano : "");
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
  const [bmaMonitorId, setBmaMonitorId] = useState("");
  const [bmaMonitor, setBmaMonitor] = useState<BmaPageMonitor | null>(null);
  const [bmaMonitorError, setBmaMonitorError] = useState("");
  const [bmaStatus, setBmaStatus] = useState<Record<string, BmaSendStatus>>({});
  const [dirty, setDirty] = useState(false);
  const [specialtiesRefreshed, setSpecialtiesRefreshed] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [blockId, setBlockId] = useState("");
  const [day, setDay] = useState("");
  const [hours, setHours] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [executantFilter, setExecutantFilter] = useState<string[] | null>(null);
  const [orderFilterDialogOpen, setOrderFilterDialogOpen] = useState(false);
  const [executantFilterDialogOpen, setExecutantFilterDialogOpen] = useState(false);
  const [draftSearch, setDraftSearch] = useState("");
  const [draftSpecialtyFilter, setDraftSpecialtyFilter] = useState("");
  const [draftCategoryFilter, setDraftCategoryFilter] = useState("");
  const [draftExecutantFilter, setDraftExecutantFilter] = useState<string[] | null>(null);
  const [crewChoice, setCrewChoice] = useState<{ key: string; person: string; day: string; exactDay: boolean } | null>(null);
  const [crewChoiceSelection, setCrewChoiceSelection] = useState<string[]>([]);
  const [crewChoiceError, setCrewChoiceError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [workflowStep, setWorkflowStep] = useState(3);
  const [pdfReady, setPdfReady] = useState(false);
  const [pdfDialogOpen, setPdfDialogOpen] = useState(false);
  const [selectedPdfPerson, setSelectedPdfPerson] = useState("");
  const [ordersDialogOpen, setOrdersDialogOpen] = useState(false);
  const [databaseOrders, setDatabaseOrders] = useState<WorkPlan["ordens"]>([]);
  const [databaseOrderSearch, setDatabaseOrderSearch] = useState("");
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersError, setOrdersError] = useState("");
  const [selectedDatabaseOrders, setSelectedDatabaseOrders] = useState<string[]>([]);
  const [refreshingOrders, setRefreshingOrders] = useState(false);
  const [bmaSendFinished, setBmaSendFinished] = useState(false);
  const [laborHelperSelections, setLaborHelperSelections] = useState<Record<string, string>>({});
  const [laborOvertimeHours, setLaborOvertimeHours] = useState<Record<string, string>>({});
  const [laborHelperModalOt, setLaborHelperModalOt] = useState("");
  const [preflightPending, setPreflightPending] = useState(false);
  const [outlookRecipients, setOutlookRecipients] = useState("");
  const [draftBusy, setDraftBusy] = useState(false);
  const [dropTarget, setDropTarget] = useState("");
  const [dropTargetTone, setDropTargetTone] = useState<"target" | "window" | "outside" | "late" | null>(null);
  const [draggedOrderKey, setDraggedOrderKey] = useState("");
  const [insertionTarget, setInsertionTarget] = useState("");
  const gallery = useRef<HTMLDivElement>(null);
  const handleDrag = useRef<{ payload: DragPayload; x: number; y: number; startX: number; startY: number; moved: boolean } | null>(null);
  const activeDraggedOrder = useRef("");
  const suppressCardClick = useRef(false);
  const [handleDragging, setHandleDragging] = useState(false);
  function closeLaborHelperModal() {
    setLaborHelperModalOt("");
    if (preflightPending) {
      setPreflightPending(false);
      setMessage("Envio cancelado. Nenhuma sessão do BMA foi iniciada.");
    }
  }
  function highlightDropTarget(person: string, targetDay?: string) {
    setDropTarget(`${person}:${targetDay ?? "nome"}`);
    const order = plan?.ordens.find((item) => orderKey(item) === activeDraggedOrder.current);
    setDropTargetTone(targetDay && order ? activityDateStatus(order, targetDay) : null);
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
    if (!ordersDialogOpen || !plan) return;
    let cancelled = false;
    setOrdersLoading(true); setOrdersError(""); setSelectedDatabaseOrders([]);
    listarOrdensTrabalho(plan.setores, ["WSCH", "PREPARED", "WFSCH"])
      .then((orders) => { if (!cancelled) setDatabaseOrders(orders); })
      .catch((reason: unknown) => {
        if (!cancelled) setOrdersError(reason instanceof Error ? reason.message : "Falha ao carregar as OTs do banco.");
      })
      .finally(() => { if (!cancelled) setOrdersLoading(false); });
    return () => { cancelled = true; };
  }, [ordersDialogOpen, plan?.id, plan?.revisao]);

  useEffect(() => {
    if (!laborHelperModalOt) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = document.getElementById("labor-helper-dialog");
    dialog?.querySelector<HTMLElement>("button:not(:disabled), select:not(:disabled)")?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key === "Escape") { closeLaborHelperModal(); return; }
      if (event.key !== "Tab") return;
      const elements = Array.from(dialog?.querySelectorAll<HTMLElement>(
        "button:not(:disabled), input:not(:disabled), select:not(:disabled)",
      ) ?? []);
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener("keydown", trap);
    return () => { document.removeEventListener("keydown", trap); previous?.focus(); };
  }, [laborHelperModalOt, preflightPending]);

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
        if (state.mode === "planning_send" && ["completed", "failed", "stopped"].includes(state.status)) setBmaSendFinished(true);
        if (state.mode === "planning_import" && ["completed", "failed", "stopped"].includes(state.status)) setBusy(false);
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
  const personOccupancy = useMemo(() => new Map((plan?.pessoas ?? []).map((person) => {
    const capacity = person.dias.filter((day) => day >= plan!.inicio && day <= plan!.fim
      && availableDay(plan!, person.id, day)).length * 8
      + (plan!.horas_extras ?? []).filter((extra) => extra.executante === person.id)
        .reduce((sum, extra) => sum + extra.horas, 0);
    const occupied = plan!.blocos.filter((block) => block.executantes.includes(person.id))
      .reduce((sum, block) => sum + block.horas, 0);
    return [person.id, { capacity, occupied, percentage: capacity ? Math.round(occupied / capacity * 100) : 0 }] as const;
  })), [plan]);
  const pendingBySpecialty = useMemo(() => {
    const counts = new Map<string, number>();
    const pending = new Set<string>();
    if (!plan) return { counts, total: 0 };
    for (const order of plan.ordens) {
      const key = orderKey(order);
      if (!pendingActivity(plan, key) || plan.requisitos[key]?.na_nuvem
        || plan.posicionamentos?.some((placement) => placement.ot === key)) continue;
      pending.add(key);
      const codes = [...new Set(orderSpecialties(order, plan.requisitos[key]).map((specialty) => specialty.code))];
      for (const code of codes.length ? codes : ["indefinida"])
        counts.set(code, (counts.get(code) ?? 0) + 1);
    }
    return { counts, total: pending.size };
  }, [plan]);
  const activeOrderFilterCount = Number(!!search.trim()) + Number(!!categoryFilter) + Number(!!specialtyFilter);
  const activeExecutantFilterCount = Number(executantFilter !== null && executantFilter.length < (plan?.pessoas.length ?? 0));
  const visible = plan?.ordens.filter((o) => activityMode(o) === view
    && isGalleryBmaStatus(o.status)
    && (view !== "pm" || !hasExistingPlanningInfo(o) || o.planejamento_bma_importado || o.planejamento_adicionado)
    && (view !== "corretiva" || isCorrectiveAvailable(o))
    && pendingActivity(plan, orderKey(o))
    && !plan.requisitos[orderKey(o)]?.na_nuvem
    && !plan.posicionamentos?.some((p) => p.ot === orderKey(o))
    && matchesOrderSpecialty(o, plan.requisitos[orderKey(o)], specialtyFilter)
    && (!categoryFilter || activityCategory(o) === categoryFilter)
    && normalize(`${o.wonum} ${cellText(o, "description")} ${cellText(o, "location")}`).includes(normalize(search))) ?? [];
  const checked = visible.filter((o) => plan?.requisitos[orderKey(o)].selecionada).map(orderKey);
  const highlightedOrder = plan?.ordens.find((order) => orderKey(order) === draggedOrderKey);
  const displayedStatus = plan ? dirty ? (busy ? "salvando" : "alterações pendentes") : plan.status : "";
  const firstPlannedPm = plan ? [...plan.blocos]
    .sort((left, right) => left.dia.localeCompare(right.dia) || left.inicio - right.inicio || left.ot.localeCompare(right.ot))
    .map((block) => plan.ordens.find((order) => orderKey(order) === block.ot))
    .find((order) => order && activityMode(order) === "pm") : undefined;
  const hasPlannedPm = Boolean(firstPlannedPm);
  const hasAnyAllocation = Boolean(plan?.blocos.length);
  const pdfPeople = useMemo(() => plan?.pessoas.filter((person) =>
    plan.blocos.some((block) => block.executantes.includes(person.id))) ?? [], [plan?.pessoas, plan?.blocos]);
  const availableDatabaseOrders = useMemo(() => {
    if (!plan) return [];
    const currentOrders = new Set(plan.ordens.map(orderKey));
    return databaseOrders.filter((order) => {
      const key = orderKey(order);
      const status = order.status.trim().toUpperCase();
      const workType = cellText(order, "worktype").trim().toUpperCase();
      const title = cellText(order, "description").trim();
      const isPreventivePm = ["I", "S"].includes(workType) && /^PM/i.test(title);
      const deferredHere = Boolean(plan.requisitos[key]?.na_nuvem);
      return isPreventivePm && (status === "WSCH" || status === "PREPARED" || status === "WFSCH")
        && (!currentOrders.has(key) || deferredHere)
        && (status !== "WFSCH" || deferredHere)
        && normalize(`${order.wonum} ${title} ${workType} ${status}`).includes(normalize(databaseOrderSearch));
    });
  }, [databaseOrderSearch, databaseOrders, plan]);

  function clearFilters() {
    setSearch(""); setSpecialtyFilter(""); setCategoryFilter(""); setExecutantFilter(null); setLimit(60);
    setDraftSearch(""); setDraftSpecialtyFilter(""); setDraftCategoryFilter(""); setDraftExecutantFilter(null);
  }
  function openOrderFilters() {
    setDraftSearch(search); setDraftSpecialtyFilter(specialtyFilter); setDraftCategoryFilter(categoryFilter);
    setOrderFilterDialogOpen(true);
  }
  function applyOrderFilters() {
    setSearch(draftSearch); setSpecialtyFilter(draftSpecialtyFilter); setCategoryFilter(draftCategoryFilter);
    setLimit(60); setOrderFilterDialogOpen(false);
  }
  function openExecutantFilters() {
    setDraftExecutantFilter(executantFilter === null ? null : [...executantFilter]);
    setExecutantFilterDialogOpen(true);
  }
  function applyExecutantFilters() {
    setExecutantFilter(draftExecutantFilter); setExecutantFilterDialogOpen(false);
  }

  function edit(next: WorkPlan) {
    setPlan(next); setDirty(true); setPdfReady(false); setWorkflowStep(3); setMessage(""); setError("");
  }
  function markOrders(keys: string[], checked: boolean) {
    if (!plan) return;
    const requirements = { ...plan.requisitos };
    for (const key of keys) requirements[key] = { ...requirements[key], selecionada: checked };
    edit({ ...plan, requisitos: requirements });
  }
  async function sendOrderToCloud(key: string) {
    if (!plan || busy) return;
    const requirement = plan.requisitos[key];
    const order = plan.ordens.find((item) => orderKey(item) === key);
    if (!requirement || !order) return;
    const deferredPlan = { ...plan, requisitos: {
      ...plan.requisitos,
      [key]: { ...requirement, na_nuvem: true, selecionada: false },
    } };
    setBusy(true); setError(""); setMessage("");
    try {
      const saved = await saveWorkPlan(plan.id, change(deferredPlan));
      setPlan(saved); setDirty(false); setSpecialtiesRefreshed(false);
      if (selected === key) { setSelected(""); setEditorOpen(false); }
      setDatabaseOrderSearch(order.wonum);
      setOrdersDialogOpen(true);
      setMessage(`OT ${order.wonum} salva na nuvem e pronta para seleção em outro planejamento.`);
    } catch (failure) { setError(describeError(failure)); }
    finally { setBusy(false); }
  }
  function assignBatch(person: string, keys = checked, fromDay = plan?.inicio, exactDay = false, crewSelection?: string[]) {
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
    const multiPersonKey = keys.find((key) => (prepared.requisitos[key]?.pessoas ?? 0) > 1);
    if (!crewSelection && multiPersonKey) {
      if (keys.length > 1) {
        setError("Para escolher a equipe de uma atividade com várias pessoas, arraste uma OT por vez.");
        return;
      }
      setCrewChoice({ key: multiPersonKey, person, day: fromDay ?? plan.inicio, exactDay });
      setCrewChoiceSelection([person]);
      setCrewChoiceError("");
      return;
    }
    const result = distributeBatch(prepared, keys, person, fromDay, exactDay, crewSelection);
    const dateWarnings = [...new Set(result.blocos.filter((block) => keys.includes(block.ot)).map((block) => {
      const order = plan.ordens.find((item) => orderKey(item) === block.ot);
      return order && activityDateWarning(order, block.dia);
    }).filter((warning): warning is string => !!warning))];
    result.mensagens.push(...dateWarnings);
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
      if (exactDay) setMessage("OT posicionada no dia escolhido. Revise duração e equipe; a especialidade é apenas informativa.");
      else setError(result.mensagens.join(" "));
    } else {
      setMessage(added ? "OT(s) planejada(s) com os dados disponíveis do BMA e padrões locais quando ausentes. Clique no bloco para revisar horas, equipe ou a informação de especialidade." : "As OTs escolhidas já estão totalmente alocadas; nenhum bloco foi duplicado.");
      if (added) requestAnimationFrame(() => {
        const grid = document.getElementById("integrated-schedule");
        const cell = Array.from(grid?.querySelectorAll<HTMLElement>("td[data-person]") ?? []).find((element) =>
          element.dataset.person === person && result.blocos.some((b) =>
            keys.includes(b.ot) && b.executantes.includes(person) && b.dia === element.dataset.day));
        cell?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
      });
    }
    if (dateWarnings.length) setError(dateWarnings.join(" "));
  }
  function crewChoiceAvailable(personId: string): boolean {
    if (!plan || !crewChoice) return false;
    if (crewChoice.exactDay) return availableDay(plan, personId, crewChoice.day);
    const person = plan.pessoas.find((item) => item.id === personId);
    const order = plan.ordens.find((item) => orderKey(item) === crewChoice.key);
    return !!person && !!order && person.dias.some((day) => day >= crewChoice.day && day >= plan.inicio
      && day <= plan.fim && weekStart(day) === weekStart(crewChoice.day)
      && !activityDateConstraintError(order, day) && availableDay(plan, personId, day));
  }
  function confirmCrewChoice() {
    if (!plan || !crewChoice) return;
    const required = plan.requisitos[crewChoice.key]?.pessoas ?? 0;
    if (crewChoiceSelection.length !== required) {
      setCrewChoiceError(`Selecione exatamente ${required} executantes.`);
      return;
    }
    if (!crewChoiceSelection.includes(crewChoice.person)) {
      setCrewChoiceError("A equipe deve incluir o executante da célula onde a OT foi solta.");
      return;
    }
    if (crewChoiceSelection.some((personId) => !crewChoiceAvailable(personId))) {
      setCrewChoiceError("Todos os selecionados precisam ter disponibilidade no dia ou na semana da atividade.");
      return;
    }
    const choice = crewChoice;
    const crew = [...crewChoiceSelection];
    setCrewChoice(null); setCrewChoiceSelection([]); setCrewChoiceError("");
    assignBatch(choice.person, [choice.key], choice.day, choice.exactDay, crew);
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
    const candidates = plan.pessoas;
    const preferred = placement ? [placement.executante] : [];
    setMembers([...preferred, ...candidates.map((p) => p.id).filter((p) => !preferred.includes(p))]
      .slice(0, req.pessoas ?? preferred.length));
    setEditorOpen(true);
    requestAnimationFrame(() => document.getElementById("activity-editor")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  function change(source: WorkPlan | null = plan, updateSpecialties = specialtiesRefreshed): PlanChange {
    if (!source) throw new Error("Planejamento não carregado.");
    return { revisao: source.revisao, requisitos: source.requisitos, blocos: source.blocos,
      indisponibilidades: source.indisponibilidades, motivo: "Atualização do planejamento", confirmar: false,
      atualizar_especialidades: updateSpecialties, posicionamentos: source.posicionamentos ?? [],
      horas_extras: source.horas_extras ?? [] };
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
  async function addSelectedDatabaseOrders() {
    if (!plan || !selectedDatabaseOrders.length) return;
    const selectedCount = selectedDatabaseOrders.length;
    setBusy(true); setError(""); setOrdersError("");
    try {
      const updated = await addOrdersToPlan(plan.id, plan.revisao, selectedDatabaseOrders);
      setPlan(updated); setDirty(false); setSpecialtiesRefreshed(false);
      setSelected(""); setOrdersDialogOpen(false);
      setMessage(`${selectedCount} OT(s) adicionada(s) da carteira do banco. Revise os cards e salve as próximas alterações.`);
    } catch (failure) {
      setOrdersError(describeError(failure));
    } finally { setBusy(false); }
  }
  async function refreshOrdersFromBma() {
    if (!plan || busy || dirty) return;
    setBusy(true); setRefreshingOrders(true); setError("");
    try {
      const { job_id } = await sincronizarOrdensTrabalho(plan.setores);
      let run = await obterSincronizacao(job_id);
      while (["queued", "running", "saving"].includes(run.status)) {
        setMessage(run.mensagem);
        await new Promise((resolve) => setTimeout(resolve, 1200));
        run = await obterSincronizacao(job_id);
      }
      if (run.status !== "completed") throw new Error(run.erro || run.mensagem || "Falha ao atualizar OTs no BMA.");
      const refreshed = await refreshPlanOrders(plan.id, plan.revisao);
      setPlan(refreshed.plano); setDirty(false); setSpecialtiesRefreshed(false);
      setMessage(`Consulta BMA concluída: ${run.ots_salvas} OT(s) no banco; ${refreshed.atualizadas} OT(s) atualizadas neste cronograma.`);
    } catch (failure) { setError(describeError(failure)); }
    finally { setBusy(false); setRefreshingOrders(false); }
  }
  async function suggest() {
    if (!plan) return;
    setBusy(true); setError("");
    try {
      const refreshed = await refreshPlanSpecialties(plan.id, change(plan));
      const source = refreshed.plano;
      setSpecialtiesRefreshed(true);
      const pendingPm = source.ordens.filter((order) => activityMode(order) === "pm"
      && !hasExistingPlanningInfo(order)
      && pendingActivity(source, orderKey(order))
      && !source.posicionamentos?.some((placement) => placement.ot === orderKey(order)));
      const explicitlySelected = pendingPm.filter((order) => source.requisitos[orderKey(order)].selecionada);
    const keys = (explicitlySelected.length ? explicitlySelected : pendingPm).map(orderKey);
      if (!keys.length) { setPlan(source); setError("Não há PMs pendentes para sugerir neste planejamento."); return; }
      const result = await suggestWorkPlan(plan.id, "pm", change(source, true), keys);
      const next = { ...source, blocos: result.blocos };
      edit({ ...next, posicionamentos: source.posicionamentos?.filter((p) => pendingActivity(next, p.ot)) }); setSuggestions(result.mensagens);
      const added = result.blocos.length - source.blocos.length;
      setMessage(added
        ? `Sugestão automática: ${added} bloco(s) distribuído(s) em ${keys.length} PM(s), respeitando disponibilidade, janela de execução e equilíbrio de carga. Especialidade é apenas informativa. Revise e salve; alocações existentes foram preservadas.`
        : "Nenhum bloco foi criado. Consulte as pendências abaixo; duração, quantidade e janela foram atualizadas para este planejamento.");
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
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
      setDraggedOrderKey(moving.payload.lote?.[0] ?? moving.payload.ot);
    }
  }
  function cancelPointer() {
    handleDrag.current = null; activeDraggedOrder.current = ""; setDraggedOrderKey(""); setHandleDragging(false); clearDropTarget(); setInsertionTarget("");
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
    setDraggedOrderKey(activeDraggedOrder.current);
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
      const lateWarnings = [...new Set(blocks.filter((item) => item.ot === payload.ot).map((item) => {
        const order = plan.ordens.find((candidate) => orderKey(candidate) === item.ot);
        return order && activityDateWarning(order, item.dia);
      }).filter((warning): warning is string => !!warning))];
      setMessage(lateWarnings.length
        ? `Sequência reprogramada. ${lateWarnings.join(" ")}`
        : "Sequência reprogramada na mesma semana. Duração e equipe preservadas; confira os novos dias e salve a revisão.");
      if (lateWarnings.length) setError("Atenção: a sequência ficará após o prazo do BMA e será indicada como atraso.");
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
    if (members.some((member) => ![day, ...related.map((b) => b.dia)].every((scheduledDay) => availableDay(plan, member, scheduledDay)))) {
      setError("A equipe precisa estar disponível em todos os dias da OT."); return;
    }
    const order = plan.ordens.find((item) => orderKey(item) === selected);
    const dateWarning = order ? activityDateWarning(order, day) : null;
    const next = { ...plan, blocos: [...plan.blocos.filter((b) => b.id !== blockId)
      .map((item) => item.ot === selected ? { ...item, executantes: members } : item), block],
      requisitos: { ...plan.requisitos, [selected]: nextRequirement } };
    edit({ ...next, posicionamentos: pendingActivity(next, selected) ? plan.posicionamentos : plan.posicionamentos?.filter((p) => p.ot !== selected) });
    setBlockId(""); setMembers([]); setHours("");
    setEditorOpen(false);
      setMessage("Atividade incluída no dia. Salve as alterações para registrar este rascunho.");
    const finalPlan = { ...next, posicionamentos: pendingActivity(next, selected) ? plan.posicionamentos : plan.posicionamentos?.filter((p) => p.ot !== selected) };
    setPlan(finalPlan);
    if (dateWarning) { setError(dateWarning); setMessage("Atividade alocada após o prazo do BMA; revise o atraso antes de enviar."); }
  }
  function postpone(key: string, confirmRemoval = true) {
    if (!plan) return;
    if (confirmRemoval && !window.confirm("Retirar todos os blocos desta OT? Ela voltará à carteira não alocada; registre o motivo na preparação e na revisão.")) return;
    edit({ ...plan, blocos: plan.blocos.filter((b) => b.ot !== key), posicionamentos: plan.posicionamentos?.filter((p) => p.ot !== key) });
    if (!confirmRemoval) setMessage(`${plan.ordens.find((order) => orderKey(order) === key)?.wonum ?? key} voltou à galeria de atividades.`);
  }
  function createPdf() {
    if (!plan) return;
    setSelectedPdfPerson(pdfPeople[0]?.id ?? "");
    setPdfDialogOpen(true);
  }
  async function downloadPdf(executante?: string) {
    if (!plan) return;
    setBusy(true); setError("");
    try {
      let saved = plan;
      if (dirty) {
        saved = await saveWorkPlan(plan.id, change(plan));
        setPlan(saved); setDirty(false);
      }
      if (executante) {
        const personName = saved.pessoas.find((person) => person.id === executante)?.nome ?? "Integrante";
        await downloadPersonSchedule(saved.id, saved.revisao, executante, personName);
      } else await downloadSchedule(saved.id, saved.revisao, saved.inicio, saved.fim);
      clearFilters();
      setPdfReady(true);
      setWorkflowStep(4);
      setPdfDialogOpen(false);
      setMessage(executante
        ? `PDF individual de ${pdfPeople.find((person) => person.id === executante)?.nome ?? "executante"} baixado.`
        : "PDF geral da revisão baixado, com todas as atividades programadas.");
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }
  async function startPlanningSend(sourcePlan: WorkPlan) {
    setWorkflowStep(5);
    setBmaSendFinished(false);
    setBusy(true); setError(""); setBmaMonitorError("");
    try {
      let saved = sourcePlan;
      if (dirty) {
        saved = await saveWorkPlan(sourcePlan.id, change(sourcePlan));
        setPlan(saved); setDirty(false);
      }
      const { monitor_id, total } = await sendPlanningToBmaReader(saved.id);
      setBmaMonitor({ monitor_id, status: "starting", mode: "planning_send", message: "Abrindo BMA...",
        fields: [], stage: "starting", progress: 0, queue_total: total, current_order_index: 0,
        current_wonum: null, completed_wonums: [], failed_wonum: null, opened_wonum: null,
        processadas: 0, planejadas: 0, pendentes: 0, com_erro: 0, resultados: [] });
      setBmaMonitorId(monitor_id);
    } catch (failure) { setError(describeError(failure)); } finally { setBusy(false); }
  }
  async function sendPlanningToBma() {
    if (!plan || !firstPlannedPm) return;
    if (!window.confirm("Antes de enviar, vou conferir as quantidades de executantes coletadas na Preparação. O envio só começa depois dessa revisão.")) return;
    const understaffed = underAllocatedPreparationOrders(plan);
    if (understaffed.length) {
      setPreflightPending(true);
      setLaborHelperModalOt(understaffed[0].order.wonum);
      setMessage(`${understaffed.length} OT(s) precisam de mais executantes segundo a Preparação coletada. Complete a equipe para iniciar o envio.`);
      return;
    }
    await startPlanningSend(plan);
  }
  async function saveBmaLaborHelper(result: BmaPlanningResult, personId: string) {
    const order = plan?.ordens.find((item) => item.wonum === result.numero_ot);
    if (!order) { setBmaMonitorError("A OT não está mais na carteira deste planejamento."); return; }
    await saveLaborHelper(order, personId, result.requisitos_mao_de_obra ?? preparationRequirements(order));
  }
  async function saveLaborHelper(
    order: WorkPlan["ordens"][number], personId: string, requirements: ReturnType<typeof preparationRequirements>,
  ) {
    if (!plan) return;
    const key = orderKey(order);
    const candidate = laborHelperCandidates(plan, key, requirements)
      .find((item) => item.person.id === personId);
    if (!candidate) { setBmaMonitorError("O executante não está mais disponível para todas as datas da OT."); return; }
    const overtimeHours = Number(laborOvertimeHours[order.wonum] ?? candidate.overtimeMinimum);
    setBusy(true); setBmaMonitorError("");
    try {
      const next = addLaborHelper(plan, key, personId, overtimeHours, requirements);
      const saved = await saveWorkPlan(plan.id, change(next));
      setPlan(saved); setDirty(false); setSpecialtiesRefreshed(false);
      setLaborHelperSelections((current) => { const updated = { ...current }; delete updated[order.wonum]; return updated; });
      setLaborOvertimeHours((current) => { const updated = { ...current }; delete updated[order.wonum]; return updated; });
      if (preflightPending) {
        const remaining = underAllocatedPreparationOrders(saved);
        if (remaining.length) {
          setLaborHelperModalOt(remaining[0].order.wonum);
          setMessage(`${order.wonum}: executante adicionado. Ainda faltam pessoas em ${remaining.length} OT(s).`);
        } else {
          setLaborHelperModalOt("");
          setPreflightPending(false);
          setMessage("Equipe completa conforme a Preparação. Iniciando o envio ao BMA.");
          await startPlanningSend(saved);
        }
      } else {
        setLaborHelperModalOt("");
        setMessage(`${order.wonum}: equipe ampliada e salva. A OT será revalidada ao fim da fila.`);
      }
    } catch (failure) { setBmaMonitorError(describeError(failure)); } finally { setBusy(false); }
  }
  async function returnBmaOrderToPortfolio(result: BmaPlanningResult) {
    if (!plan) return;
    const order = plan.ordens.find((item) => item.wonum === result.numero_ot);
    if (!order) { setBmaMonitorError("A OT não está mais na carteira deste planejamento."); return; }
    setBusy(true); setBmaMonitorError("");
    try {
      const saved = await saveWorkPlan(plan.id, change(returnOrderToPortfolio(plan, orderKey(order))));
      setPlan(saved); setDirty(false); setSpecialtiesRefreshed(false);
      setMessage(`${result.numero_ot} voltou à carteira. Nenhuma alteração foi enviada ao BMA.`);
    } catch (failure) { setBmaMonitorError(describeError(failure)); } finally { setBusy(false); }
  }
  async function retryPendingBmaOrders() {
    if (!plan || busy || bmaMonitor?.status !== "completed") return;
    setBusy(true); setBmaMonitorError(""); setBmaSendFinished(false);
    try {
      let saved = plan;
      if (dirty) {
        saved = await saveWorkPlan(plan.id, change(plan));
        setPlan(saved); setDirty(false);
      }
      const understaffed = underAllocatedPreparationOrders(saved);
      if (understaffed.length) {
        setPreflightPending(true);
        setLaborHelperModalOt(understaffed[0].order.wonum);
        setMessage(`${understaffed.length} OT(s) ainda precisam de executantes antes da revalidação.`);
        return;
      }
      await startPlanningSend(saved);
    } catch (failure) { setBmaMonitorError(describeError(failure)); } finally { setBusy(false); }
  }
  async function importScheduleFromBma() {
    if (!plan || plan.status !== "rascunho" || dirty || busy || bmaMonitorId) return;
    if (!window.confirm(`Ler as OTs programadas no BMA entre ${formatPlanningDate(plan.inicio)} e ${formatPlanningDate(plan.fim)} e importar no cronograma local? Esta operação não grava alterações no BMA.`)) return;
    setBusy(true); setError(""); setMessage(""); setBmaMonitorError("");
    try {
      const { monitor_id, total } = await importPlanningFromBma(plan.id);
      setBmaMonitor({ monitor_id, status: "starting", mode: "planning_import", inspection_only: true,
        message: `Lendo a programação do BMA para ${total} OT(s). Nenhuma alteração será gravada no BMA.`,
        fields: [], queue_total: total, processadas: 0, selected_wonums: [] });
      setBmaMonitorId(monitor_id);
    } catch (failure) {
      setBusy(false); setError(describeError(failure));
    }
  }
  async function applyBmaScheduleImport() {
    if (!plan || !bmaMonitorId || bmaMonitor?.mode !== "planning_import" || bmaMonitor.status !== "completed"
      || bmaMonitor.import_applied || busy) return;
    const readCount = bmaMonitor.processadas ?? bmaMonitor.resultados?.length ?? 0;
    if (!window.confirm(`Colocar no cronograma local as atribuições das ${readCount} OT(s) lidas, respeitando executantes e datas? Nenhuma alteração será gravada no BMA.`)) return;
    setBusy(true); setBmaMonitorError(""); setError("");
    try {
      const applied = await applyBmaPlanningImport(plan.id, bmaMonitorId);
      setBmaMonitor(applied);
      const refreshed = await getWorkPlan(id);
      setPlan(refreshed); setDirty(false); setSelected("");
      setMessage(applied.message);
    } catch (failure) {
      setBmaMonitorError(describeError(failure));
    } finally { setBusy(false); }
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

  function encodeBase64(bytes: Uint8Array): string {
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    }
    return btoa(binary);
  }

  async function createOutlookDraft() {
    if (!plan || !pdfReady || draftBusy) return;
    const recipients = outlookRecipients.split(/[;,\s]+/).map((value) => value.trim()).filter(Boolean);
    if (!recipients.length || recipients.some((value) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))) {
      setError("Revise os destinatários. Informe endereços válidos separados por vírgula ou ponto e vírgula.");
      return;
    }
    setDraftBusy(true);
    setError("");
    setMessage("");
    try {
      let saved = plan;
      if (dirty) {
        saved = await saveWorkPlan(plan.id, change(plan));
        setPlan(saved);
        setDirty(false);
      }
      const pdf = await getSchedulePdf(saved.id, saved.revisao);
      const attachment = encodeBase64(new Uint8Array(await pdf.arrayBuffer())).match(/.{1,76}/g)?.join("\r\n") ?? "";
      const body = encodeBase64(new TextEncoder().encode(
        `Olá,\r\n\r\nSegue em anexo o cronograma de manutenção de ${formatPlanningDate(saved.inicio)} a ${formatPlanningDate(saved.fim)}.\r\n\r\nAtenciosamente,\r\n${saved.planejador}`,
      )).match(/.{1,76}/g)?.join("\r\n") ?? "";
      const fileName = `cronograma-${saved.id}-r${saved.revisao}.pdf`;
      const boundary = `pcm-${saved.id.replace(/[^a-zA-Z0-9]/g, "")}`;
      const subject = `Cronograma de manutencao ${formatPlanningDate(saved.inicio)} a ${formatPlanningDate(saved.fim)}`;
      const eml = [
        `To: ${recipients.join(", ")}`,
        `Subject: ${subject}`,
        "MIME-Version: 1.0",
        `Content-Type: multipart/mixed; boundary="${boundary}"`,
        "",
        `--${boundary}`,
        "Content-Type: text/plain; charset=UTF-8",
        "Content-Transfer-Encoding: base64",
        "",
        body,
        `--${boundary}`,
        `Content-Type: application/pdf; name="${fileName}"`,
        "Content-Transfer-Encoding: base64",
        `Content-Disposition: attachment; filename="${fileName}"`,
        "",
        attachment,
        `--${boundary}--`,
        "",
      ].join("\r\n");
      const url = URL.createObjectURL(new Blob([eml], { type: "message/rfc822" }));
      const link = Object.assign(document.createElement("a"), { href: url, download: `planejamento-${saved.id}-r${saved.revisao}.eml` });
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 5000);
      setMessage("Rascunho do Outlook preparado com o PDF anexado. Abra o arquivo .eml baixado para revisar e enviar.");
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setDraftBusy(false);
    }
  }

  const laborHelperModalResult = bmaMonitor?.resultados?.find((result) => result.numero_ot === laborHelperModalOt);
  const laborHelperModalOrder = plan?.ordens.find((order) => order.wonum === laborHelperModalOt);
  const laborHelperModalKey = laborHelperModalOrder ? orderKey(laborHelperModalOrder) : "";
  const laborHelperModalRequirements = laborHelperModalResult?.requisitos_mao_de_obra
    ?? (laborHelperModalOrder ? preparationRequirements(laborHelperModalOrder) : []);
  const laborHelperModalCandidates = plan && laborHelperModalKey
    ? laborHelperCandidates(plan, laborHelperModalKey, laborHelperModalRequirements)
    : [];
  const laborHelperModalSelectedId = laborHelperSelections[laborHelperModalOt] ?? laborHelperModalCandidates[0]?.person.id ?? "";
  const laborHelperModalCandidate = laborHelperModalCandidates.find((item) => item.person.id === laborHelperModalSelectedId);
  const laborHelperModalOvertimeText = laborOvertimeHours[laborHelperModalOt];
  const laborHelperModalOvertime = laborHelperModalOvertimeText === undefined
    ? laborHelperModalCandidate?.overtimeMinimum ?? 0 : Number(laborHelperModalOvertimeText);
  const laborHelperModalDates = plan?.blocos.filter((block) => block.ot === laborHelperModalKey)
    .map((block) => block.dia).filter((value, index, dates) => dates.indexOf(value) === index).sort() ?? [];

  return <>
    <Head><title>Bancada de planejamento | Planning & Scheduling Michelin</title></Head>
    <main className="pcm-workspace mx-auto min-h-screen w-full max-w-none space-y-5 p-4 lg:p-7">
      <PlanningWorkflowSteps active={workflowStep} />
      <header className="pcm-panel flex flex-wrap items-center justify-between gap-4 p-5">
        <div>
          <Link href="/planejamento/acompanhamento" className="mb-3 inline-flex items-center gap-2 text-xs text-sky-300"><ArrowLeft size={14} /> Acompanhamento</Link>
          <h1 className="text-2xl font-semibold text-white">Bancada de Planejamento PCM</h1>
          {plan && <><p className="mt-2 text-sm text-slate-400">{formatPlanningDate(plan.inicio)} a {formatPlanningDate(plan.fim)} · {plan.planejador} · <span className={displayedStatus === "confirmado" ? "font-semibold text-emerald-300" : "text-amber-200"}>{displayedStatus}</span> · revisão {plan.revisao}</p>
            <Link href={{ pathname: "/planejamento", query: { etapa: "2", setor: plan.setores } }} className="mt-2 inline-flex text-xs text-sky-300">Voltar ao Centro de Planejamento</Link></>}
        </div>
        {plan && workflowStep >= 3 && <div className="flex shrink-0 flex-wrap gap-2">
          <button type="button" className="pcm-small-button min-h-9" disabled={busy || dirty}
            title={dirty ? "Salve as alterações locais antes de atualizar o BMA." : "Atualiza o banco BMA e os dados das OTs deste plano."}
            onClick={() => void refreshOrdersFromBma()}>
            {refreshingOrders ? <RefreshCw size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            {refreshingOrders ? "Atualizando OTs..." : "Atualizar OTs no BMA"}
          </button>
          <button type="button" className="pcm-small-button min-h-9" disabled={busy || plan.status !== "rascunho"}
            onClick={() => setOrdersDialogOpen(true)}>
            <Database size={15} /> OTs do banco
          </button>
          <button type="button" className="pcm-small-button min-h-9"
            aria-label="Salvar planejamento" title={dirty ? "Salvar alterações deste planejamento." : "Não há alterações para salvar."}
            disabled={busy || !dirty} onClick={() => void save()}>
            <Save size={15} /> Salvar planejamento
          </button>
        </div>}
      </header>
      {ordersDialogOpen && plan && <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-3 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="database-orders-title">
        <section className="pcm-panel flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden p-4 sm:p-5">
          <header className="flex items-start justify-between gap-4 border-b border-white/10 pb-3">
            <div>
              <h2 id="database-orders-title" className="pcm-title"><Database size={17} /> Atividades disponíveis no banco</h2>
              <p className="mt-1 text-xs text-slate-400">{availableDatabaseOrders.length} PM(s) elegíveis · {selectedDatabaseOrders.length} selecionada(s)</p>
            </div>
            <button type="button" className="pcm-small-button min-h-8 px-2" aria-label="Fechar atividades do banco"
              disabled={busy} onClick={() => setOrdersDialogOpen(false)}><X size={15} /></button>
          </header>
          <label className="mt-3 block text-xs font-medium text-[#000000]">Filtrar por Nº OT, título, tipo ou status
            <input className="mt-1 block h-10 w-full rounded-md border border-[#000000] bg-[#ffffff] px-3 text-sm text-[#000000] placeholder:text-[#666666] focus:outline-none focus:ring-2 focus:ring-[#000000]/20"
              aria-label="Filtrar OTs por número, título, tipo ou status" placeholder="Ex.: RES123 · PM3 · PREPARED"
              value={databaseOrderSearch} onChange={(event) => setDatabaseOrderSearch(event.target.value)} />
          </label>
          <p className="mt-1 text-[11px] text-slate-700">Somente tipo I ou S com título iniciado por PM · status WSCH/PREPARED; WFSCH apenas para OTs na nuvem deste plano.</p>
          {ordersError && <p role="alert" className="mt-3 text-sm text-rose-300">{ordersError}</p>}
          {ordersLoading ? <p role="status" className="flex items-center gap-2 py-10 text-sm text-slate-300"><LoaderCircle size={16} className="animate-spin" /> Carregando OTs do banco...</p>
            : <div className="mt-3 min-h-0 flex-1 overflow-auto rounded border border-[#000000] bg-[#ffffff]">
              <table className="min-w-[1050px] w-full border-collapse bg-[#ffffff] text-left text-xs text-[#000000]">
                <thead className="sticky top-0 z-10 !bg-[#ffffff] !text-[#000000]">
                  <tr>
                    <th className="w-9 border-b border-[#000000] p-2"><input type="checkbox" aria-label="Selecionar todas as OTs disponíveis"
                      checked={availableDatabaseOrders.length > 0 && selectedDatabaseOrders.length === availableDatabaseOrders.length}
                      disabled={!availableDatabaseOrders.length || busy}
                      onChange={(event) => setSelectedDatabaseOrders(event.target.checked ? availableDatabaseOrders.map(orderKey) : [])} /></th>
                    <th className="border-b border-[#000000] p-2">Nº OT</th><th className="min-w-64 border-b border-[#000000] p-2">Título</th><th className="border-b border-[#000000] p-2">Tipo</th>
                    <th className="border-b border-[#000000] p-2">Não iniciar antes de</th><th className="border-b border-[#000000] p-2">Terminar antes de</th>
                    <th className="border-b border-[#000000] p-2">Status</th><th className="border-b border-[#000000] p-2">Pessoas</th><th className="border-b border-[#000000] p-2">Duração</th>
                  </tr>
                </thead>
                <tbody>
                  {availableDatabaseOrders.map((order) => {
                    const key = orderKey(order);
                    const laborRows = plannedLabor(order);
                    const peopleCount = laborRows.reduce((total, row) => total + (Number(row.quantity.replace(",", ".")) || 0), 0);
                    const databaseDuration = Number(cellText(order, "estdur").replace(",", "."));
                    const duration = databaseDuration > 0 ? databaseDuration : Number(plan.requisitos[key]?.duracao) || 0;
                    const durationLabel = Number.isFinite(duration) && duration > 0
                      ? `${Math.floor(duration)}:${String(Math.round((duration % 1) * 60)).padStart(2, "0")} h`
                      : "Não informado";
                    const type = activityCategory(order);
                    const typeLabel = ({ pm1: "PM1", pm2: "PM2", pm3: "PM3", corretiva: "Corretiva" } as Record<string, string>)[type]
                      ?? (cellText(order, "worktype") || "Não informado");
                    const formatConstraint = (key: string) => {
                      const value = cellText(order, key);
                      const parsed = localDate(value);
                      return parsed ? formatPlanningDate(parsed) : value || "Não informado";
                    };
                    const requiredPeople = peopleCount || plan.requisitos[key]?.pessoas || 0;
                    return <tr key={key} className="border-b border-[#000000] align-top text-[#000000] hover:bg-[#f5f5f5]">
                      <td className="p-2"><input type="checkbox" aria-label={`Selecionar OT ${order.wonum}`} checked={selectedDatabaseOrders.includes(key)} disabled={busy}
                        onChange={(event) => setSelectedDatabaseOrders((current) => event.target.checked
                          ? [...current, key] : current.filter((item) => item !== key))} /></td>
                      <td className="whitespace-nowrap p-2 font-semibold text-[#000000]">{order.wonum}</td>
                      <td className="max-w-sm p-2 text-[#000000]">{cellText(order, "description") || "Sem título"}</td>
                      <td className="whitespace-nowrap p-2">{typeLabel}</td>
                      <td className="whitespace-nowrap p-2">{formatConstraint("sneconstraint")}</td>
                      <td className="whitespace-nowrap p-2">{formatConstraint("fnlconstraint")}</td>
                      <td className="whitespace-nowrap p-2">{order.status}{plan.requisitos[key]?.na_nuvem ? " · nuvem" : ""}</td>
                      <td className="whitespace-nowrap p-2">{requiredPeople || "Não informado"}</td>
                      <td className="whitespace-nowrap p-2">{durationLabel}</td>
                    </tr>;
                  })}
                  {!availableDatabaseOrders.length && <tr><td colSpan={9} className="border-b border-[#000000] p-8 text-center text-[#000000]">Nenhuma PM elegível corresponde a esta busca.</td></tr>}
                </tbody>
              </table>
            </div>}
          <footer className="mt-3 flex flex-wrap justify-end gap-2 border-t border-white/10 pt-3">
            <button type="button" className="pcm-small-button" disabled={busy} onClick={() => setOrdersDialogOpen(false)}>Cancelar</button>
            <button type="button" className="pcm-primary-button" disabled={busy || !selectedDatabaseOrders.length || plan.status !== "rascunho"}
              onClick={() => void addSelectedDatabaseOrders()}>
              {busy ? <LoaderCircle size={15} className="animate-spin" /> : <CheckCircle2 size={15} />}
              Adicionar selecionadas ao cronograma
            </button>
          </footer>
        </section>
      </div>}
      {crewChoice && plan && <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="crew-choice-title"
        onKeyDown={(event) => { if (event.key === "Escape") { setCrewChoice(null); setCrewChoiceSelection([]); setCrewChoiceError(""); } }}>
        <section className="pcm-panel flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden p-4 sm:p-5">
          <header className="flex items-start justify-between gap-4 border-b border-white/10 pb-3">
            <div>
              <h2 id="crew-choice-title" className="pcm-title"><UsersRound size={17} /> Escolher equipe da atividade</h2>
              <p className="mt-1 text-sm font-semibold text-sky-200">
                {plan.ordens.find((order) => orderKey(order) === crewChoice.key)?.wonum} · {cellText(plan.ordens.find((order) => orderKey(order) === crewChoice.key)!, "description")}
              </p>
              <p className="mt-1 text-xs text-slate-400">Selecione exatamente {plan.requisitos[crewChoice.key]?.pessoas} executantes · destino inicial: {plan.pessoas.find((person) => person.id === crewChoice.person)?.nome} · {formatPlanningDate(crewChoice.day)}</p>
            </div>
            <button type="button" className="pcm-small-button min-h-8 px-2" aria-label="Cancelar escolha da equipe"
              onClick={() => { setCrewChoice(null); setCrewChoiceSelection([]); setCrewChoiceError(""); }}><X size={15} /></button>
          </header>
          {crewChoiceError && <p role="alert" className="mt-3 text-sm text-rose-300">{crewChoiceError}</p>}
          <div className="min-h-0 flex-1 overflow-y-auto py-3">
            <div className="grid gap-2 sm:grid-cols-2">
              {plan.pessoas.map((person) => {
                const selectedPerson = crewChoiceSelection.includes(person.id);
                const available = crewChoiceAvailable(person.id);
                const required = plan.requisitos[crewChoice.key]?.pessoas ?? 0;
                return <label key={person.id} className={`flex gap-2 rounded-lg border p-3 text-sm ${selectedPerson ? "border-sky-400 bg-sky-400/10" : "border-white/10 bg-black/10"} ${!available && !selectedPerson ? "cursor-not-allowed opacity-45" : "cursor-pointer hover:border-sky-400/50"}`}>
                  <input type="checkbox" aria-label={`Selecionar ${person.nome}`} checked={selectedPerson}
                    disabled={person.id === crewChoice.person || !available && !selectedPerson}
                    onChange={(event) => {
                        if (event.target.checked && crewChoiceSelection.length >= required) {
                          setCrewChoiceError(`Esta OT exige exatamente ${required} executantes.`);
                          return;
                        }
                        setCrewChoiceError("");
                        setCrewChoiceSelection(event.target.checked
                          ? [...crewChoiceSelection, person.id]
                          : crewChoiceSelection.filter((id) => id !== person.id));
                    }} />
                  <span className="min-w-0 flex-1"><span className="block font-semibold text-white">{person.nome}{person.id === crewChoice.person ? " · destino" : ""}</span>
                    <span className="mt-0.5 block text-xs text-slate-400">{person.funcao_descricao} · {person.orgid}/{person.matricula}</span>
                    <span className={`mt-1 block text-[10px] ${available ? "text-emerald-300" : "text-rose-300"}`}>
                      {available ? crewChoice.exactDay ? `Disponível em ${formatPlanningDate(crewChoice.day)}` : "Disponível na semana da atividade" : "Indisponível para esta atividade"}
                    </span>
                  </span>
                </label>;
              })}
            </div>
          </div>
          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 pt-3">
            <span className="text-xs text-slate-400">{crewChoiceSelection.length} / {plan.requisitos[crewChoice.key]?.pessoas} selecionados</span>
            <div className="flex gap-2">
              <button type="button" className="pcm-small-button" onClick={() => { setCrewChoice(null); setCrewChoiceSelection([]); setCrewChoiceError(""); }}>Cancelar</button>
              <button type="button" className="pcm-primary-button"
                disabled={crewChoiceSelection.length !== (plan.requisitos[crewChoice.key]?.pessoas ?? 0)
                  || !crewChoiceSelection.includes(crewChoice.person)
                  || crewChoiceSelection.some((personId) => !crewChoiceAvailable(personId))}
                onClick={confirmCrewChoice}><CheckCircle2 size={15} /> Adicionar atividade</button>
            </div>
          </footer>
        </section>
      </div>}
      {pdfDialogOpen && plan && <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="pdf-export-title">
        <section className="pcm-panel w-full max-w-xl space-y-4 p-5">
          <div className="flex items-start justify-between gap-4">
            <div><h2 id="pdf-export-title" className="pcm-title"><Download size={17} /> Exportar cronograma</h2>
              <p className="mt-1 text-xs text-slate-400">PDF geral com todo o cronograma ou individual por integrante.</p></div>
            <button type="button" className="pcm-small-button min-h-8 px-2" aria-label="Fechar exportação de PDF"
              disabled={busy} onClick={() => setPdfDialogOpen(false)}><X size={15} /></button>
          </div>
          <button type="button" className="pcm-primary-button w-full justify-center" disabled={busy || !hasAnyAllocation}
            onClick={() => void downloadPdf()}>
            {busy ? <LoaderCircle size={15} className="animate-spin" /> : <Download size={15} />}
            Baixar PDF geral
          </button>
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-0 flex-1 text-xs text-slate-300">PDF individual
              <select className={`${input} mt-1`} aria-label="Selecionar integrante para PDF individual"
                value={selectedPdfPerson} disabled={busy || !pdfPeople.length}
                onChange={(event) => setSelectedPdfPerson(event.target.value)}>
                {pdfPeople.map((person) => <option key={person.id} value={person.id}>{person.nome} · {person.funcao_descricao}</option>)}
              </select>
            </label>
            <button type="button" className="pcm-small-button min-h-10" disabled={busy || !selectedPdfPerson}
              onClick={() => void downloadPdf(selectedPdfPerson)}>
              {busy ? <LoaderCircle size={15} className="animate-spin" /> : <Download size={15} />}
              Baixar individual
            </button>
          </div>
        </section>
      </div>}
      {orderFilterDialogOpen && plan && <div className="fixed inset-0 z-[105] flex items-center justify-center bg-black/70 p-3 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="order-filters-title"
        onKeyDown={(event) => { if (event.key === "Escape") setOrderFilterDialogOpen(false); }}>
        <section className="pcm-panel flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden p-4 sm:p-5">
          <header className="flex items-start justify-between gap-4 border-b border-white/10 pb-3">
            <div><h2 id="order-filters-title" className="pcm-title"><SlidersHorizontal size={17} /> Filtros de OTs</h2>
              <p className="mt-1 text-xs text-slate-400">{pendingBySpecialty.total} OT(s) ainda pendentes no período</p></div>
            <button type="button" className="pcm-small-button min-h-8 px-2" aria-label="Fechar filtros"
              onClick={() => setOrderFilterDialogOpen(false)}><X size={15} /></button>
          </header>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto py-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs text-slate-300 sm:col-span-2">Buscar atividade
                <input className={`${input} mt-1`} aria-label="Buscar atividade" placeholder="OT, descrição ou local" value={draftSearch}
                  onChange={(event) => setDraftSearch(event.target.value)} />
              </label>
              <label className="text-xs text-slate-300">Tipo de OT
                <select className={`${input} mt-1`} aria-label="Filtrar tipo de OT" value={draftCategoryFilter}
                  onChange={(event) => setDraftCategoryFilter(event.target.value)}>
                  <option value="">Todos os tipos</option><option value="pm1">PM1</option><option value="pm2">PM2</option>
                  <option value="pm3">PM3</option><option value="outras-pm">Outras PM</option><option value="corretiva">Corretiva</option>
                </select>
              </label>
              <label className="text-xs text-slate-300">Especialidade
                <select className={`${input} mt-1`} aria-label="Filtrar por especialidade" value={draftSpecialtyFilter}
                  onChange={(event) => setDraftSpecialtyFilter(event.target.value)}>
                  <option value="">Todas as especialidades</option><option value="indefinida">Especialidade não definida</option>
                  <option value="qualquer">Qualquer especialidade (Todos)</option>
                  {specialtyOptions.map(([key, label]) => <option key={key} value={key}>{label} · {pendingBySpecialty.counts.get(key) ?? 0} OTs</option>)}
                </select>
              </label>
            </div>
            <section aria-labelledby="filter-specialty-counts-title">
              <h3 id="filter-specialty-counts-title" className="border-b border-white/10 pb-2 text-sm font-semibold text-white">OTs pendentes por especialidade</h3>
              <div className="mt-2 space-y-2">
                {[["indefinida", "Sem especialidade"], ...specialtyOptions].map(([key, label]) => {
                  const count = pendingBySpecialty.counts.get(key) ?? 0;
                  const percentage = pendingBySpecialty.total ? Math.round(count / pendingBySpecialty.total * 100) : 0;
                  return <div key={key} className="grid grid-cols-[minmax(0,1fr)_2fr_auto] items-center gap-3 text-xs">
                    <span className="truncate text-slate-300">{label}</span>
                    <span className="h-1.5 overflow-hidden rounded bg-white/10"><span className="block h-full bg-amber-300"
                      style={{ width: `${percentage}%` }} /></span>
                    <span className="w-20 text-right tabular-nums text-slate-400">{count} OTs · {percentage}%</span>
                  </div>;
                })}
              </div>
            </section>
          </div>
          <footer className="flex flex-wrap justify-between gap-2 border-t border-white/10 pt-3">
            <button type="button" className="pcm-small-button" onClick={() => {
              setDraftSearch(""); setDraftSpecialtyFilter(""); setDraftCategoryFilter("");
            }}>Limpar OTs</button>
            <div className="flex gap-2">
              <button type="button" className="pcm-small-button" onClick={() => setOrderFilterDialogOpen(false)}>Cancelar</button>
              <button type="button" className="pcm-primary-button" onClick={applyOrderFilters}><CheckCircle2 size={15} /> OK</button>
            </div>
          </footer>
        </section>
      </div>}
      {executantFilterDialogOpen && plan && <div className="fixed inset-0 z-[105] flex items-center justify-center bg-black/70 p-3 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="executant-filters-title"
        onKeyDown={(event) => { if (event.key === "Escape") setExecutantFilterDialogOpen(false); }}>
        <section className="pcm-panel flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden p-4 sm:p-5">
          <header className="flex items-start justify-between gap-4 border-b border-white/10 pb-3">
            <div><h2 id="executant-filters-title" className="pcm-title"><UsersRound size={17} /> Filtros de executantes</h2>
              <p className="mt-1 text-xs text-slate-400">Capacidade ocupada no horizonte do planejamento</p></div>
            <button type="button" className="pcm-small-button min-h-8 px-2" aria-label="Fechar filtros de executantes"
              onClick={() => setExecutantFilterDialogOpen(false)}><X size={15} /></button>
          </header>
          <label className="mt-3 flex cursor-pointer items-center gap-2 border-b border-white/10 pb-3 text-xs font-semibold text-white">
            <input type="checkbox" aria-label="Selecionar todos os executantes no filtro"
              checked={draftExecutantFilter === null || draftExecutantFilter.length === plan.pessoas.length}
              onChange={(event) => setDraftExecutantFilter(event.target.checked ? null : [])} /> Todos ({plan.pessoas.length})
          </label>
          <div className="min-h-0 flex-1 overflow-y-auto py-3">
            <div className="grid gap-2 sm:grid-cols-2">
              {plan.pessoas.map((person) => {
                const selectedPeople = draftExecutantFilter ?? plan.pessoas.map((item) => item.id);
                const checked = selectedPeople.includes(person.id);
                const occupancy = personOccupancy.get(person.id) ?? { capacity: 0, occupied: 0, percentage: 0 };
                return <label key={person.id} className="flex cursor-pointer gap-2 rounded border border-white/10 bg-black/10 p-2 text-xs text-slate-200 hover:bg-white/[.04]">
                  <input type="checkbox" aria-label={`Filtrar executante ${person.nome}`} checked={checked} className="mt-0.5 accent-sky-400"
                    onChange={(event) => {
                      const next = event.target.checked ? [...selectedPeople, person.id] : selectedPeople.filter((id) => id !== person.id);
                      setDraftExecutantFilter(next.length === plan.pessoas.length ? null : next);
                    }} />
                  <span className="min-w-0 flex-1">
                    <span className="flex justify-between gap-2"><span className="truncate font-medium">{person.nome} · {person.funcao_descricao}</span>
                      <span className={occupancy.percentage > 100 ? "shrink-0 text-rose-300" : "shrink-0 text-slate-400"}>{occupancy.percentage}%</span></span>
                    <span className="mt-1 block h-1.5 overflow-hidden rounded bg-white/10">
                      <span className={`block h-full ${occupancy.percentage > 100 ? "bg-rose-400" : "bg-sky-400"}`}
                        style={{ width: `${Math.min(100, occupancy.percentage)}%` }} />
                    </span>
                    <span className="mt-1 block text-[10px] text-slate-500">{formatNumber(occupancy.occupied)} / {formatNumber(occupancy.capacity)} h</span>
                  </span>
                </label>;
              })}
            </div>
          </div>
          <footer className="flex flex-wrap justify-between gap-2 border-t border-white/10 pt-3">
            <button type="button" className="pcm-small-button" onClick={() => setDraftExecutantFilter(null)}>Todos</button>
            <div className="flex gap-2">
              <button type="button" className="pcm-small-button" onClick={() => setExecutantFilterDialogOpen(false)}>Cancelar</button>
              <button type="button" className="pcm-primary-button" onClick={applyExecutantFilters}><CheckCircle2 size={15} /> OK</button>
            </div>
          </footer>
        </section>
      </div>}
      {error && <p role="alert" className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-4 text-sm text-rose-200">{error}</p>}
      {message && <p role="status" className="rounded-lg border border-sky-400/30 bg-sky-400/10 p-4 text-sm text-sky-200">{message}</p>}
      {busy && <p role="status" className="flex items-center gap-2 text-sm text-sky-200"><LoaderCircle size={16} className="animate-spin" /> Processando. Aguarde antes de iniciar outra ação.</p>}
      {!plan ? <p role={busy ? "status" : undefined} className="flex items-center gap-2 text-slate-400">{busy && <LoaderCircle size={17} className="animate-spin" />}{busy ? "Carregando planejamento..." : "Abra um planejamento pela carteira ou pelo acompanhamento."}</p> : <>
        <div className={workflowStep === 3 ? "contents" : "hidden"}>
        {!!conflicts.size && <p role="alert" className="rounded-lg border border-rose-400/40 bg-rose-400/10 p-4 text-sm text-rose-200">{conflicts.size} alocação(ões) com capacidade semanal excedida. {plan.status === "rascunho" ? "Prévia pode ser salva como rascunho; confirmação bloqueada." : "Plano já confirmado: ajuste a capacidade semanal antes de salvar a revisão."} Redistribua para outro integrante com saldo ou retire atividades.</p>}
        <fieldset disabled={busy} className="min-w-0 space-y-5 disabled:opacity-60">
          <section className="pcm-allocation-dock sticky top-0 z-40 mx-auto w-[90vw] rounded-xl border border-white/10 p-2 backdrop-blur-xl" aria-label="Controles e galeria de atividades">
            <div className="flex flex-wrap items-center gap-2">
              <nav className="flex min-w-0 flex-nowrap gap-1 overflow-x-auto" aria-label="Fluxo de alocação">
                {([ ["pm", "1 · Planejar PM", "PM"], ["corretiva", "2 · Encaixar corretiva", "Corretiva"] ] as const).map(([key, label, compact]) =>
                  <button key={key} className={view === key ? "pcm-primary-button min-h-8 shrink-0 px-2 py-1 text-[11px] sm:px-2.5 sm:text-xs" : "pcm-small-button min-h-8 shrink-0 px-2 py-1 text-[11px] sm:px-2.5 sm:text-xs"} disabled={busy || key === "corretiva" && !hasPlannedPm} title={key === "corretiva" && !hasPlannedPm ? "Planeje ao menos uma PM para liberar corretivas." : undefined} aria-pressed={view === key} onClick={() => { setView(key); setLimit(60); }}><span className="sm:hidden">{compact}</span><span className="hidden sm:inline">{label}</span></button>) }
                <button type="button" aria-label="Gerar PDF" title={busy ? "Aguarde a operação atual terminar." : !hasAnyAllocation ? "Programe ao menos uma atividade para criar o PDF." : dirty ? "O rascunho será salvo antes de abrir as opções de PDF." : "Escolher PDF geral ou individual."}
                  className="pcm-small-button min-h-8 shrink-0 px-2 py-1 text-[11px] sm:px-2.5 sm:text-xs" disabled={busy || !hasAnyAllocation} onClick={createPdf}>
                  <Download size={14} /><span>Gerar PDF</span>
                </button>
              </nav>
              <button className="pcm-small-button ml-auto min-h-8 shrink-0 px-2 py-1" aria-label="Sugerir planejamento automático de PMs" title="Distribuir PMs pendentes por disponibilidade e carga equilibrada; especialidade é apenas informativa." disabled={busy} onClick={() => void suggest()}><Sparkles size={14} /><span className="hidden sm:inline">Sugerir PMs</span></button>
              <button type="button" className="pcm-small-button min-h-8 shrink-0 px-2 py-1" aria-label="Importar planejamento do BMA" title={dirty ? "Salve as alterações locais antes de importar." : "Lê atribuições planejadas no BMA e monta os blocos locais; não grava no BMA."}
                disabled={busy || dirty || plan.status !== "rascunho"} onClick={() => void importScheduleFromBma()}>
                <Import size={14} /><span className="hidden sm:inline">Importar do BMA</span>
              </button>
              <button type="button" className="pcm-small-button min-h-8 shrink-0 px-2 py-1" aria-label="Filtrar OTs" aria-haspopup="dialog"
                aria-expanded={orderFilterDialogOpen} onClick={openOrderFilters}>
                <SlidersHorizontal size={14} /><span>Filtro OTs{activeOrderFilterCount ? ` · ${activeOrderFilterCount}` : ""}</span>
              </button>
              <button type="button" className="pcm-small-button min-h-8 shrink-0 px-2 py-1" aria-label="Filtrar executantes" aria-haspopup="dialog"
                aria-expanded={executantFilterDialogOpen} onClick={openExecutantFilters}>
                <UsersRound size={14} /><span>Executantes{activeExecutantFilterCount ? ` · ${executantFilter?.length ?? 0}` : ""}</span>
              </button>
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
            <div ref={gallery} className="mt-2 flex h-[230px] snap-x snap-mandatory gap-2 overflow-x-auto overflow-y-hidden overscroll-x-contain pb-1" aria-label="Galeria horizontal de OTs">
              {visible.slice(0, limit).map((order, index) => {
                const key = orderKey(order), req = plan.requisitos[key], done = allocatedDuration(plan, key);
                const missing = missingPlanningData(order);
                const periodRange = dayMonthRange(cellText(order, "sneconstraint"), cellText(order, "fnlconstraint"));
                const targetRange = dayMonthRange(cellText(order, "targstartdate"), cellText(order, "targcompdate"));
                const preparation = plannedLabor(order);
                const preparationPeople = preparation.reduce((sum, row) => sum + (Number(row.quantity.replace(",", ".")) || 0), 0);
                const peopleCount = preparationPeople || req.pessoas || 0;
                const executionHours = cellText(order, "estdur") || (req.duracao ? String(req.duracao) : "");
                const status = order.status.trim().toUpperCase();
                const location = [cellText(order, "location"), cellText(order, "assetnum")].filter(Boolean).join(" · ");
                const sent = bmaStatus[order.wonum];
                const badge = (sent && BMA_BADGES[sent.situacao])
                  || (order.planejamento_bma_importado ? BMA_BADGES.ja_planejada : undefined);
                const detailedTitle = [order.wonum, activityMode(order).toUpperCase(), cellText(order, "description"), location,
                  `Período ${periodRange.start} a ${periodRange.end}`, `Data-alvo ${targetRange.start} a ${targetRange.end}`,
                  `Status ${order.status}`, `Duração ${executionHours || "não informada"} h`, `Pessoas ${peopleCount || "não informadas"}`,
                  ...preparation.map((row) => `${row.craft}: ${row.quantity} pessoa(s), ${row.hours} h`),
                ].filter(Boolean).join(" · ");
                return <div key={key} style={{ animationDelay: `${Math.min(index, 10) * 35}ms` }} className="pcm-activity-card relative flex h-min w-[clamp(76px,15vw,200px)] max-w-[86vw] shrink-0 snap-start items-start">
                  <span aria-hidden="true" className="absolute inset-y-0 left-0 z-[2] w-1.5 rounded-l-lg bg-[#ffdd00]" />
                  <button type="button" draggable={!busy} onDragStart={(e) => drag(e, { ot: key })} onDragEnd={() => { activeDraggedOrder.current = ""; setDraggedOrderKey(""); clearDropTarget(); }}
                    onClick={() => { selectOrder(key); setEditorOpen(false); }} title={`${detailedTitle}${missing.length ? ` · Dados BMA ausentes: ${missing.join(", ")}` : ""}`}
                    className={`pcm-card-main relative flex h-[218px] w-full min-w-0 flex-none flex-col overflow-hidden rounded-lg border p-2.5 pl-3 pr-7 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${missing.length ? "border-rose-400/80 bg-rose-50" : selected === key ? "border-sky-500 bg-sky-50" : "border-slate-200 bg-[#f8fafc]"}`}>
                    <span className="pcm-card-heading flex min-w-0 items-center justify-between gap-2 pl-9">
                      <span className="pcm-card-wonum truncate text-xs font-extrabold text-[#063b79]">{order.wonum}</span>
                      <span className="pcm-card-type shrink-0 rounded bg-[#e5edf6] px-1.5 py-0.5 text-[9px] font-bold text-[#174ea6]">{activityMode(order).toUpperCase()}</span>
                    </span>
                    <span className="pcm-card-description mt-2 block max-h-9 overflow-hidden break-words text-[10px] font-bold uppercase leading-tight text-slate-900">{cellText(order, "description")}</span>
                    {!!location && <span className="pcm-card-location mt-1 block w-full truncate text-[9px] text-slate-500">{location}</span>}
                    <div className="pcm-card-period-panel mt-2 grid grid-cols-[1.35fr_.8fr_.8fr] gap-1.5 rounded-md bg-[#eaf0f6] p-2">
                      <span className="min-w-0"><span className="block text-[9px] text-slate-500">Período</span>
                        <span className="block truncate text-[9px] font-bold text-slate-800">{periodRange.start} → {periodRange.end}</span></span>
                      <span className="min-w-0"><span className="flex items-center gap-1 text-[9px] text-slate-500"><Clock3 size={10} /> Duração</span>
                        <span className="block truncate text-[10px] font-bold text-slate-800">{executionHours ? `${executionHours} h` : "—"}</span></span>
                      <span className="min-w-0"><span className="flex items-center gap-1 text-[9px] text-slate-500"><UsersRound size={10} /> Pessoas</span>
                        <span className="block truncate text-[10px] font-bold text-slate-800">{peopleCount || "—"}</span></span>
                    </div>
                    <span className="pcm-card-target mt-1 flex w-full items-center justify-between gap-2 text-[9px] text-slate-500">
                      <span>Data-alvo</span><span className="truncate font-semibold text-slate-700">{targetRange.start} → {targetRange.end}</span>
                    </span>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className={`max-w-[65%] truncate rounded px-2 py-1 text-[10px] font-bold ${status === "WFSCH" ? "bg-[#ffdf70] text-[#493500]" : "bg-[#e6edf5] text-slate-700"}`}
                        title={`Status da OT no BMA: ${order.status || "Não informado"}`}>{order.status || "Não informado"}</span>
                      <span className="shrink-0 text-[9px] font-semibold text-slate-600">Equipe {peopleCount || "?"}</span>
                    </div>
                    {badge && <span className={`pcm-card-bma-badge mt-1 w-max max-w-full truncate rounded px-1.5 py-0.5 text-[9px] font-bold ${badge[1]}`}>{badge[0]}</span>}
                    {!!preparation.length && <ul className="pcm-card-preparation mt-1 max-h-8 w-full space-y-0.5 overflow-hidden text-[9px] leading-tight text-slate-600"
                      aria-label={`Requisitos por especialidade da OT ${order.wonum}`}>
                      {preparation.slice(0, 2).map((row, rowIndex) => <li key={`${row.craft}-${rowIndex}`} className="truncate">
                        {row.craft || "Especialidade"}: {row.quantity || "?"} pessoa(s) · {row.hours || "—"} h
                      </li>)}
                      {preparation.length > 2 && <li className="text-slate-500">+{preparation.length - 2} especialidade(s)</li>}
                    </ul>}
                    {!preparation.length && <span className="pcm-card-preparation mt-1 block w-full truncate text-[9px] text-amber-700">Preparação não coletada</span>}
                    <span data-drag-ot={key} aria-label={`Arrastar ${order.wonum} para pessoa e dia`} title="Clique, segure e arraste até a célula de pessoa e dia"
                      onPointerDown={(e) => beginPointer(e, { ot: key, lote: checked.includes(key) ? checked : [key] })}
                      onPointerMove={movePointer} onPointerUp={finishPointer} onPointerCancel={cancelPointer}
                      onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }} onClick={(e) => e.stopPropagation()}
                      className="pcm-card-drag absolute right-1 top-1 touch-none select-none cursor-grab rounded p-1 text-slate-500 hover:bg-slate-200 active:cursor-grabbing"><GripVertical size={14} /></span>
                  </button>
                  <button type="button" aria-label={`Editar OT ${order.wonum}`} title="Preparar / editar atividade"
                    className="pcm-card-edit absolute bottom-1 right-1 rounded p-1 text-[#174ea6] hover:text-[#063b79]" onClick={() => openEditor(key)}><Pencil size={13} /></button>
                  <button type="button" aria-label={`Enviar OT ${order.wonum} para a nuvem`} title="Adiar para outro planejamento; a OT permanece no banco de dados"
                    className="pcm-card-cloud absolute left-2 top-2 z-10 grid size-8 place-items-center rounded-md border border-[#d6e2ef] bg-[#e8f0f8] text-[#174ea6] shadow-sm transition hover:border-[#174ea6]/40 hover:bg-[#dbe9f8]"
                    disabled={busy} onClick={() => void sendOrderToCloud(key)}><Cloud size={20} strokeWidth={2.1} /></button>
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
                <label className="block text-xs text-slate-400">Especialidade (informação)
                  <select className={`${input} mt-1`} value={requirement.todas_especialidades ? "todos" : requirement.funcao ? JSON.stringify([requirement.orgid, requirement.funcao]) : ""} onChange={(e) => {
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
                  <div className="grid gap-2 sm:grid-cols-2">{plan.pessoas.map((p) =>
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
            {highlightedOrder && <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-300" aria-label={`Legenda de datas para OT ${highlightedOrder.wonum}`}>
              <span className="font-medium text-white">OT {highlightedOrder.wonum}</span>
              <span className="inline-flex items-center gap-1.5"><i className="h-3 w-3 rounded-sm border border-emerald-300 bg-emerald-400/20" /> Data-alvo</span>
              <span className="inline-flex items-center gap-1.5"><i className="h-3 w-3 rounded-sm border border-sky-300 bg-sky-400/15" /> Dentro da janela</span>
              <span className="inline-flex items-center gap-1.5"><i className="h-3 w-3 rounded-sm border border-rose-300 bg-rose-400/15" /> Fora da janela</span>
              <span className="inline-flex items-center gap-1.5"><i className="h-3 w-3 rounded-sm border-2 border-purple-400 bg-rose-400/15" /> Atraso permitido</span>
              <span className="inline-flex items-center gap-1.5"><i className="h-3 w-3 rounded-sm border border-white/20 bg-white/10" /> Indisponível</span>
            </div>}
            <div id="schedule-scroll" className="h-min overflow-visible">
              <table className="w-full border-separate border-spacing-2 text-left text-xs">
                <thead className="sticky top-0 z-20 bg-[#102235]"><tr><th className="sticky left-0 z-30 min-w-40 bg-[#102235] p-2 align-top">
                  <span className="mb-2 block">Executante / especialidade</span>
                  <span className="inline-flex rounded border border-white/10 bg-[#081729] px-2 py-1 text-[10px] font-normal text-slate-400">
                    {executantFilter === null ? `${plan.pessoas.length} integrantes` : `${executantFilter.length}/${plan.pessoas.length} visíveis`}
                  </span>
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
                    const dateStatus = highlightedOrder ? activityDateStatus(highlightedOrder, d) : null;
                    const pendingLoad = provisionalDayLoad(plan, person.id, d), displayedLoad = load + pendingLoad;
                    const overloaded = weeklyBalance(plan, person.id, d).remaining < -1e-6;
                    const dailyCapacity = available ? 8 : 0;
                    const dailyRemaining = Math.max(0, dailyCapacity - displayedLoad);
                    const percentage = dailyCapacity ? displayedLoad / dailyCapacity * 100 : 0;
                    return <td key={d} aria-label={`${person.nome} · ${formatPlanningDate(d)}`} data-person={person.id} data-day={d}
                      onDragOver={(e) => { if (!busy && available) { e.preventDefault(); highlightDropTarget(person.id, d); } }}
                      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) clearDropTarget(); }}
                      onDrop={(e) => drop(e, d, person.id)}
                      title={`${!available ? "Indisponível para este executante" : dateStatus === "target" ? "Data-alvo desta OT" : dateStatus === "window" ? "Dentro da janela de execução desta OT" : dateStatus === "late" ? "Prazo BMA ultrapassado; é possível programar com aviso de atraso" : dateStatus === "outside" ? "Antes da data permitida pela OT" : "Dia disponível"}`}
                      className={`rounded-lg border p-2 align-top ${dropTarget === `${person.id}:${d}`
                        ? dropTargetTone === "target" ? "border-emerald-300 bg-emerald-400/20 ring-2 ring-emerald-300/40" : dropTargetTone === "late" ? "border-purple-300 bg-rose-400/20 ring-2 ring-purple-300/50" : dropTargetTone === "outside" ? "border-rose-300 bg-rose-400/20 ring-2 ring-rose-300/40" : "border-sky-300 bg-sky-400/20 ring-2 ring-sky-300/40"
                        : !available ? "border-white/10 bg-white/[.02] opacity-60" : dateStatus === "late" ? "border-purple-400/60 bg-rose-400/15" : dateStatus === "outside" ? "border-rose-400/40 bg-rose-400/10" : dateStatus === "target" ? "border-emerald-400/50 bg-emerald-400/10" : dateStatus === "window" ? "border-sky-400/30 bg-sky-400/[.06]" : overloaded ? "border-rose-400/60 bg-rose-400/10" : "border-white/10 bg-white/[.03]"}`}>
                      {dropTarget === `${person.id}:${d}` && <p className={`mb-2 font-semibold ${dropTargetTone === "target" ? "text-emerald-200" : dropTargetTone === "late" || dropTargetTone === "outside" ? "text-rose-200" : "text-sky-200"}`}>{dropTargetTone === "target" ? "Data-alvo da OT" : dropTargetTone === "outside" ? "Antes da data permitida" : dropTargetTone === "late" ? "Prazo ultrapassado · atraso permitido" : dropTargetTone === "window" ? "Dentro da janela da OT" : "Soltar para associar a este executante e dia"}</p>}
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
                        const late = order ? activityDateStatus(order, b.dia) === "late" : false;
                        const sent = order ? bmaStatus[order.wonum] : undefined;
                        const plannedInBma = !!order?.planejamento_bma_importado
                          || (!!sent && ["planejada", "ja_planejada"].includes(sent.situacao));
                        const badge = (sent && BMA_BADGES[sent.situacao])
                          || (order?.planejamento_bma_importado ? BMA_BADGES.ja_planejada : undefined);
                        return <div key={b.id} className="group relative mb-2">
                          <button type="button" draggable={!busy} onDragStart={(e) => drag(e, { ot: b.ot, bloco: b.id, origem: person.id })}
                          onPointerDown={(e) => beginPointer(e, { ot: b.ot, bloco: b.id, origem: person.id })}
                          onPointerMove={movePointer} onPointerUp={finishPointer} onPointerCancel={cancelPointer}
                          data-schedule-block={b.id}
                          onDragOver={(e) => { if (!busy) { e.preventDefault(); e.stopPropagation(); setInsertionTarget(`${person.id}:${b.id}`); } }}
                          onDragLeave={() => setInsertionTarget("")}
                          onDragEnd={() => { activeDraggedOrder.current = ""; setDraggedOrderKey(""); setInsertionTarget(""); clearDropTarget(); }}
                          onDrop={(e) => drop(e, d, person.id, b.id)}
                          title={`${formatNumber(b.horas)} h neste dia · ${b.executantes.length} pessoa(s)${conflicts.has(b.id) ? " · Capacidade semanal excedida" : ""}${missing.length ? ` · Dados BMA ausentes: ${missing.join(", ")}` : ""}${complete ? " · Alocação completa" : ""}. Clique para editar.`}
                          onClick={() => { if (suppressCardClick.current) { suppressCardClick.current = false; return; } openEditor(b.ot); setBlockId(b.id); setDay(b.dia); setHours(String(b.horas)); setMembers(b.executantes); }}
                          className={`block w-full touch-none cursor-grab rounded border p-2 pr-7 text-left active:cursor-grabbing ${plannedInBma ? "pb-8" : ""} ${insertionTarget === `${person.id}:${b.id}` ? "border-t-4 border-t-sky-300 ring-2 ring-sky-300/40" : ""} ${conflicts.has(b.id) ? "border-rose-400 bg-rose-400/20 text-rose-100" : complete ? "border-emerald-400 bg-emerald-400/10 text-emerald-100" : missing.length ? "border-rose-400 bg-rose-400/10 text-rose-100" : order && activityMode(order) === "pm" ? "border-sky-400/25 bg-sky-400/10 text-sky-100" : "border-amber-400/25 bg-amber-400/10 text-amber-100"} ${late ? "border-2 border-purple-400 bg-rose-400/15 text-rose-100 ring-1 ring-purple-400/40" : ""}`}>
                          <strong>{order?.wonum} - {order && activityMode(order).toUpperCase()}</strong>
                          <span className="mt-1 block">{order && cellText(order, "description")}</span>
                          {badge && <span title={sent ? `${sent.erro ?? badge[0]} · ${new Date(sent.registrado_em).toLocaleString("pt-BR")}` : badge[0]}
                            className={`mt-1 inline-block rounded border px-1.5 py-0.5 text-[10px] font-semibold ${badge[1]}`}>{badge[0]}</span>}
                          {order?.status?.trim() && <span title={`Status da OT no BMA: ${order.status}`}
                            className="mt-1 inline-block max-w-full rounded border border-white/15 bg-black/10 px-1.5 py-0.5 text-[10px] font-medium text-slate-200">Status: {order.status}</span>}
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
        </div>
        {workflowStep === 4 && <section className="pcm-panel mx-auto max-w-3xl space-y-4 p-6" aria-labelledby="pdf-step-title">
          <div className="flex items-start gap-3"><CheckCircle2 className="mt-1 text-emerald-300" /><div><h2 id="pdf-step-title" className="text-xl font-semibold text-white">Cronograma em PDF</h2><p className="mt-1 text-sm text-slate-300">{pdfReady ? `PDF da revisão ${plan.revisao} foi gerado e baixado.` : "Gere o PDF do cronograma antes de continuar."}</p></div></div>
          <div className="flex flex-wrap gap-3">
            <button type="button" className="pcm-small-button" onClick={() => setWorkflowStep(3)}><ArrowLeft size={15} /> Voltar à distribuição</button>
            <button type="button" className="pcm-small-button" disabled={busy || !hasAnyAllocation} onClick={createPdf}><Download size={15} /> Gerar PDF novamente</button>
            <button type="button" className="pcm-primary-button" disabled={!pdfReady || busy} onClick={() => setWorkflowStep(5)}><ArrowRight size={16} /> Continuar para envio ao BMA</button>
          </div>
        </section>}
        {workflowStep === 5 && <section className="pcm-panel mx-auto max-w-3xl space-y-4 p-6" aria-labelledby="bma-step-title">
          <div className="flex items-start gap-3"><Send className="mt-1 text-sky-300" /><div><h2 id="bma-step-title" className="text-xl font-semibold text-white">Enviar planejamento ao BMA</h2><p className="mt-1 text-sm text-slate-300">O envio é executado no BMA e pode levar alguns minutos. Acompanhe o progresso para evitar repetir a operação.</p></div></div>
          {bmaSendFinished && <p role="status" className="text-sm text-emerald-200">A operação do BMA terminou. Revise os resultados antes de avançar.</p>}
          <div className="flex flex-wrap gap-3">
            <button type="button" className="pcm-small-button" disabled={busy} onClick={() => setWorkflowStep(4)}><ArrowLeft size={15} /> Voltar ao PDF</button>
            <button type="button" className="pcm-primary-button" disabled={busy || !hasPlannedPm} onClick={() => void sendPlanningToBma()}><Send size={15} /> Enviar ao BMA</button>
            <button type="button" className="pcm-small-button" disabled={!bmaSendFinished} onClick={() => setWorkflowStep(6)}><ArrowRight size={15} /> Continuar para e-mail</button>
          </div>
        </section>}
        {workflowStep === 6 && <section className="pcm-panel mx-auto max-w-3xl space-y-4 p-6" aria-labelledby="email-step-title">
          <div className="flex items-start gap-3"><Send className="mt-1 text-sky-300" /><div><h2 id="email-step-title" className="text-xl font-semibold text-white">Rascunho de e-mail para a equipe</h2><p className="mt-1 text-sm text-slate-300">Informe os destinatários. O arquivo .eml abrirá no Outlook com o cronograma PDF anexado para revisão manual.</p></div></div>
          <label className="block text-sm text-slate-300">Destinatários
            <input className={`${input} mt-2`} type="text" inputMode="email" autoComplete="email" placeholder="nome@empresa.com; equipe@empresa.com" value={outlookRecipients} onChange={(event) => setOutlookRecipients(event.target.value)} />
          </label>
          <p className="text-xs text-slate-500">Os endereços não são salvos no sistema. O assunto e a mensagem poderão ser editados no Outlook.</p>
          <div className="flex flex-wrap gap-3">
            <button type="button" className="pcm-small-button" disabled={draftBusy} onClick={() => setWorkflowStep(5)}><ArrowLeft size={15} /> Voltar ao BMA</button>
            <button type="button" className="pcm-primary-button" disabled={draftBusy || !pdfReady} onClick={() => void createOutlookDraft()}>
              {draftBusy ? <LoaderCircle size={15} className="animate-spin" /> : <Download size={15} />}
              {draftBusy ? "Preparando rascunho..." : "Baixar rascunho do Outlook"}
            </button>
            <Link href="/" className="pcm-small-button"><ArrowRight size={15} /> Finalizar e voltar ao início</Link>
          </div>
        </section>}
      </>}
      {handleDragging && <div className="pointer-events-none fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-sky-300 bg-[#081729] px-5 py-3 text-sm text-sky-100 shadow-xl">Arrastando OT · solte na célula do executante e dia</div>}
      {bmaMonitorId && <div role="dialog" aria-modal="true" aria-labelledby="bma-progress-title" className="fixed inset-0 z-[100] grid place-items-center bg-black/70 p-4">
        <section className={`pcm-panel max-h-[90vh] w-full ${bmaMonitor?.mode === "planning_import" ? "max-w-6xl" : "max-w-lg"} space-y-5 overflow-y-auto p-5`}>
          <div className="flex items-start gap-3">
            {bmaMonitorError || bmaMonitor?.status === "failed" ? <AlertCircle size={21} className="mt-0.5 shrink-0 text-rose-300" />
              : bmaMonitor?.progress === 100 ? <CheckCircle2 size={21} className="mt-0.5 shrink-0 text-emerald-300" />
                : <LoaderCircle size={21} className="mt-0.5 shrink-0 animate-spin text-sky-300" />}
            <div className="min-w-0 flex-1">
              <h2 id="bma-progress-title" className="text-base font-semibold text-white">{bmaMonitor?.mode === "planning_import"
                ? bmaMonitorError || bmaMonitor?.status === "failed" ? "Importação do BMA interrompida" : "Importar planejamento do BMA"
                : bmaMonitor?.mode === "open_ot"
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
            {!!bmaMonitor.resultados?.some((result) => result.situacao_consulta === "pendente_planejador" && result.requisitos_mao_de_obra?.length) &&
              <div className="space-y-3">
                {bmaMonitor.resultados.filter((result) => result.situacao_consulta === "pendente_planejador" && result.requisitos_mao_de_obra?.length)
                  .map((result) => {
                    const order = plan?.ordens.find((item) => item.wonum === result.numero_ot);
                    const key = order ? orderKey(order) : "";
                    const blocks = plan?.blocos.filter((block) => block.ot === key) ?? [];
                    const assignedCount = Math.max(0, ...blocks.map((block) => block.executantes.length));
                    const requiredCount = result.requisitos_mao_de_obra?.reduce(
                      (sum, row) => sum + Math.max(0, Number(row.quantidade) || 0), 0,
                    ) || plan?.requisitos[key]?.pessoas || 0;
                    const needsHelper = assignedCount < requiredCount;
                    return <article key={result.numero_ot} className="space-y-3 rounded-lg border border-amber-300/25 bg-amber-300/5 p-3">
                      <div>
                        <h3 className="text-sm font-semibold text-amber-100">Falta de mão de obra · OT {result.numero_ot}</h3>
                        <p className="mt-1 text-xs text-slate-300">{result.erro}</p>
                      </div>
                      <ul className="space-y-1 text-xs text-slate-300">
                        {result.requisitos_mao_de_obra?.map((row, index) => <li key={`${row.especialidade}-${row.orgid}-${index}`}>
                          {row.quantidade} × especialidade {row.especialidade || "não informada"}{row.orgid ? ` · ${row.orgid}` : ""}
                          {row.horas_normais ? ` · ${row.horas_normais} h` : ""}
                        </li>)}
                      </ul>
                      <button type="button" className="pcm-primary-button" disabled={busy || !order || !needsHelper}
                        onClick={() => setLaborHelperModalOt(result.numero_ot)}>
                        <UserPlus size={14} /> Adicionar executante
                      </button>
                      {!needsHelper && <p className="text-xs text-emerald-200">Equipe ampliada; aguardando revalidação da OT.</p>}
                      <button type="button" className="pcm-small-button" disabled={busy || !order}
                        onClick={() => void returnBmaOrderToPortfolio(result)}><Undo2 size={14} /> Voltar à carteira</button>
                    </article>;
                  })}
              </div>}
          </>}
          {bmaMonitor?.mode === "planning_import" && <>
            <dl className="grid grid-cols-2 gap-2 text-center text-xs">
              <div className="rounded-lg border border-white/10 p-2"><dt className="text-slate-400">Lidas</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-white">{bmaMonitor.processadas ?? 0}/{bmaMonitor.queue_total ?? 0}</dd></div>
              <div className="rounded-lg border border-white/10 p-2"><dt className="text-slate-400">No cronograma</dt><dd className="mt-1 text-lg font-semibold tabular-nums text-emerald-200">{bmaMonitor.importadas?.length ?? 0}</dd></div>
            </dl>
            {!!bmaMonitor.resultados?.length && <div className="max-h-[45vh] overflow-auto rounded border border-white/10">
              <table className="min-w-[900px] w-full text-left text-xs">
                <thead className="sticky top-0 bg-[#101b29] text-slate-400">
                  <tr><th className="p-2">OT</th><th className="p-2">Execução</th><th className="p-2">Início planejado</th><th className="p-2">Fim planejado</th><th className="p-2">Duração</th><th className="p-2">Executantes</th><th className="p-2">Leitura</th></tr>
                </thead>
                <tbody>{bmaMonitor.resultados.map((result) => <tr key={result.numero_ot} className="border-t border-white/10 align-top text-slate-200">
                  <td className="p-2"><span className="font-medium text-white">{result.numero_ot}</span><span className="mt-1 block max-w-56 text-slate-400">{result.descricao || "Sem descrição"}</span></td>
                  <td className="p-2">{result.status?.trim().toUpperCase() === "INPRG" ? "Em execução" : result.status || "Não informado"}</td>
                  <td className="whitespace-nowrap p-2">{result.inicio_planejado || "—"}</td>
                  <td className="whitespace-nowrap p-2">{result.termino_planejado || "—"}</td>
                  <td className="whitespace-nowrap p-2">{result.duracao_planejada ? `${result.duracao_planejada} h` : "—"}</td>
                  <td className="max-w-56 p-2">{result.executor || "Sem executante atribuído"}</td>
                  <td className="p-2">{result.erro || "OK"}</td>
                </tr>)}</tbody>
              </table>
            </div>}
            {!!bmaMonitor.avisos_importacao?.length && <ul className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-amber-400/20 p-2 text-xs text-amber-200">
              {bmaMonitor.avisos_importacao.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>}
          </>}
          <div className="flex flex-wrap justify-end gap-2">
            {!!bmaMonitor?.resultados?.length && <button type="button" className="pcm-small-button" onClick={downloadBmaResults}><Download size={14} /> Baixar JSON</button>}
            {bmaMonitor?.mode === "planning_import" && bmaMonitor.status === "completed" && !bmaMonitor.import_applied
              && !!bmaMonitor.resultados?.length && <button type="button" className="pcm-primary-button" disabled={busy} onClick={() => void applyBmaScheduleImport()}>
                {busy ? <LoaderCircle size={14} className="animate-spin" /> : <CalendarDays size={14} />} Colocar no cronograma
              </button>}
            {bmaMonitor?.mode === "planning_send" && bmaMonitor.status === "completed" && (bmaMonitor.pendentes ?? 0) > 0 &&
              <button type="button" className="pcm-primary-button" disabled={busy} onClick={() => void retryPendingBmaOrders()}>
                {busy ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />} Revalidar pendências
              </button>}
            {bmaMonitor?.mode === "planning_send" && ["starting", "monitoring"].includes(bmaMonitor.status) &&
              <button type="button" className="pcm-small-button text-amber-200" onClick={() => void stopBmaProgress()}>Interromper</button>}
            {(bmaMonitor?.progress === 100 || bmaMonitor?.status === "failed" || bmaMonitorError || bmaMonitor?.status === "stopped") &&
              <button type="button" className="pcm-small-button" onClick={closeBmaProgress}>Fechar</button>}
          </div>
        </section>
      </div>}
      {laborHelperModalOt && laborHelperModalOrder && <div className="fixed inset-0 z-[110] grid place-items-center overflow-y-auto bg-black/80 p-4"
        onMouseDown={(event) => { if (event.target === event.currentTarget) closeLaborHelperModal(); }}>
        <section id="labor-helper-dialog" role="dialog" aria-modal="true" aria-labelledby="labor-helper-title"
          className="pcm-panel my-auto max-h-[90vh] w-full max-w-lg space-y-4 overflow-y-auto p-5">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <h2 id="labor-helper-title" className="text-base font-semibold text-white">{preflightPending ? "Completar equipe antes do envio" : "Adicionar executante"} · OT {laborHelperModalOt}</h2>
              <p className="mt-1 text-sm text-slate-300">Selecione alguém disponível nas datas desta atividade. A especialidade não será usada como filtro. O BMA ainda não foi aberto.</p>
            </div>
            <button type="button" className="pcm-small-button" aria-label="Fechar seleção de executante"
              onClick={closeLaborHelperModal}><X size={16} /></button>
          </div>
          <p className="text-xs text-slate-400">Datas da OT: {laborHelperModalDates.map(dayMonth).join(", ") || "não programada"}</p>
          {!!laborHelperModalRequirements.length && <ul className="space-y-1 rounded-lg border border-border p-3 text-xs text-muted-foreground">
            {laborHelperModalRequirements.map((row, index) => <li key={`${row.especialidade}-${row.orgid}-${index}`}>
              {row.quantidade} × {row.especialidade || "especialidade"}{row.horas_normais ? ` · ${row.horas_normais} h` : ""}
            </li>)}
          </ul>}
          {laborHelperModalCandidates.length && laborHelperModalCandidate ? <div className="space-y-3">
            <label className="block text-sm text-slate-200">Executante disponível
              <select className={`${input} mt-1`} value={laborHelperModalSelectedId} onChange={(event) => {
                setLaborHelperSelections((current) => ({ ...current, [laborHelperModalOt]: event.target.value }));
                setLaborOvertimeHours((current) => { const next = { ...current }; delete next[laborHelperModalOt]; return next; });
              }}>
                {laborHelperModalCandidates.map((item) => <option key={item.person.id} value={item.person.id}>
                  {item.person.nome} · {item.person.matricula} · {item.person.funcao_descricao}
                  {item.overtimeMinimum > 0 ? ` · mínimo ${formatNumber(item.overtimeMinimum)} h extra` : " · sem extra semanal"}
                </option>)}
              </select>
            </label>
            <label className="block text-sm text-slate-200">Hora extra semanal autorizada (h)
              <input className={`${input} mt-1`} type="number" min={laborHelperModalCandidate.overtimeMinimum}
                max={laborHelperModalCandidate.hours} step="0.5"
                value={laborHelperModalOvertimeText ?? laborHelperModalCandidate.overtimeMinimum}
                onChange={(event) => setLaborOvertimeHours((current) => ({ ...current, [laborHelperModalOt]: event.target.value }))} />
            </label>
            <p className="text-xs text-slate-400">A equipe e a disponibilidade são conferidas novamente ao salvar. Hora extra só é necessária para cobrir excesso da capacidade semanal.</p>
          </div> : <p className="rounded border border-amber-300/25 bg-amber-300/5 p-3 text-sm text-amber-100">
            Não há executante da equipe livre em todas as datas desta OT, mesmo considerando outras especialidades.
          </p>}
          <div className="flex justify-end gap-2">
            <button type="button" className="pcm-small-button" onClick={closeLaborHelperModal}>Cancelar</button>
            <button type="button" className="pcm-primary-button" disabled={busy || !laborHelperModalCandidate
              || !Number.isFinite(laborHelperModalOvertime)
              || laborHelperModalOvertime < laborHelperModalCandidate.overtimeMinimum
              || laborHelperModalOvertime > laborHelperModalCandidate.hours}
              onClick={() => laborHelperModalResult
                ? void saveBmaLaborHelper(laborHelperModalResult, laborHelperModalSelectedId)
                : void saveLaborHelper(laborHelperModalOrder, laborHelperModalSelectedId, laborHelperModalRequirements)}>
              {busy ? <LoaderCircle size={14} className="animate-spin" /> : <UserPlus size={14} />}
              {preflightPending ? "Adicionar e continuar" : "Adicionar executante"}
            </button>
          </div>
        </section>
      </div>}
    </main>
  </>;
}
