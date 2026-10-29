import { useEffect, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import type { CalendarioTurnos } from "@/services/api";
import { formatPlanningDate, parsePlanningDate } from "@/utils/laborPlanning";

type Props = {
  value: string; onChange: (value: string) => void; min?: string; max?: string;
  disabled?: boolean; className?: string; calendario?: CalendarioTurnos | null;
  equipes?: number[]; "aria-label": string;
};

const monthStart = (value: Date) => new Date(value.getFullYear(), value.getMonth(), 1);
const dateFromIso = (value: string) => {
  const [year, month, day] = value.split("-").map(Number);
  return year && month && day ? new Date(year, month - 1, day) : null;
};
const isoFromDate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;

export default function PlanningDateInput({ value, onChange, min, max, disabled, className, calendario, equipes, "aria-label": label }: Props) {
  const [draft, setDraft] = useState(() => formatPlanningDate(value));
  const [open, setOpen] = useState(false);
  const [visibleMonth, setVisibleMonth] = useState(() => monthStart(dateFromIso(value) ?? new Date()));
  const [popoverPosition, setPopoverPosition] = useState<{ left: number; width: number; top?: number; bottom?: number } | null>(null);
  const lastEmitted = useRef(value);
  const container = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (value !== lastEmitted.current) {
      setDraft(formatPlanningDate(value));
      lastEmitted.current = value;
      const selected = dateFromIso(value);
      if (selected) setVisibleMonth(monthStart(selected));
    }
  }, [value]);
  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);
  const parsed = parsePlanningDate(draft);
  const valid = !!parsed && (!min || parsed >= min) && (!max || parsed <= max);
  const firstDay = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
  const gridStart = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1 - (firstDay.getDay() + 6) % 7);
  const days = Array.from({ length: 42 }, (_, index) => new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + index));
  const teams = equipes?.length ? [...new Set(equipes)] : [1, 2, 3, 4];
  const monthLabel = new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" }).format(visibleMonth);
  function change(text: string) {
    const digits = text.replace(/\D/g, "").slice(0, 8);
    const masked = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)].filter(Boolean).join("/");
    setDraft(masked);
    const iso = parsePlanningDate(masked);
    const next = iso && (!min || iso >= min) && (!max || iso <= max) ? iso : "";
    lastEmitted.current = next;
    onChange(next);
  }
  function selectDate(day: Date) {
    const next = isoFromDate(day);
    setDraft(formatPlanningDate(next));
    lastEmitted.current = next;
    onChange(next);
    setOpen(false);
  }
  return <span ref={container} className="relative block min-w-0">
    <input type="text" aria-label={label} placeholder="dd/mm/aaaa" inputMode="numeric" maxLength={10}
      autoComplete="off" value={draft} disabled={disabled} aria-invalid={!!draft && !valid}
      title={draft && !valid ? "Informe uma data válida em dd/mm/aaaa dentro do período permitido." : "dd/mm/aaaa"}
      onChange={(event) => change(event.target.value)}
      className={`${className ?? ""} w-full pr-10 ${draft && !valid ? "border-rose-400" : ""}`} />
    <button type="button" disabled={disabled} aria-label={`Abrir calendário: ${label}`}
      aria-expanded={open}
      onClick={() => {
        if (!open) {
          const selected = dateFromIso(value);
          setVisibleMonth(monthStart(selected ?? new Date()));
          const bounds = container.current?.getBoundingClientRect();
          if (bounds) {
            const width = Math.min(352, window.innerWidth - 16);
            const left = Math.max(8, Math.min(bounds.left, window.innerWidth - width - 8));
            const openAbove = window.innerHeight - bounds.bottom < 420 && bounds.top > 420;
            setPopoverPosition({ left: left - bounds.left, width, ...(openAbove
              ? { bottom: bounds.height + 8 }
              : { top: bounds.height + 8 }) });
          }
        }
        setOpen((current) => !current);
      }}
      className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-slate-400 hover:text-sky-200 disabled:opacity-40">
      <CalendarDays size={16} />
    </button>
    {open && <div role="dialog" aria-label={`Calendário: ${label}`}
      style={popoverPosition ?? undefined}
      className="absolute z-50 rounded-lg border border-sky-400/20 bg-[#081729] p-3 shadow-2xl shadow-black/40">
      <header className="mb-3 flex items-center justify-between gap-2">
        <button type="button" aria-label="Mês anterior" onClick={() => setVisibleMonth((month) => new Date(month.getFullYear(), month.getMonth() - 1, 1))}
          className="flex h-8 w-8 items-center justify-center rounded border border-white/10 text-slate-300 hover:bg-white/5"><ChevronLeft size={16} /></button>
        <div className="text-center">
          <p className="text-sm font-semibold capitalize text-white">{monthLabel}</p>
          <p className="text-[10px] text-slate-500">{calendario?.ano === visibleMonth.getFullYear() ? `Escala · equipes ${teams.join(", ")}` : "Sem escala cadastrada para este ano"}</p>
        </div>
        <button type="button" aria-label="Próximo mês" onClick={() => setVisibleMonth((month) => new Date(month.getFullYear(), month.getMonth() + 1, 1))}
          className="flex h-8 w-8 items-center justify-center rounded border border-white/10 text-slate-300 hover:bg-white/5"><ChevronRight size={16} /></button>
      </header>
      <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-medium text-slate-500" aria-hidden="true">
        {["S", "T", "Q", "Q", "S", "S", "D"].map((day, index) => <span key={`${day}-${index}`} className="py-1">{day}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {days.map((day) => {
          const iso = isoFromDate(day), inMonth = day.getMonth() === visibleMonth.getMonth();
          const shifts = calendario?.dias[iso];
          const entries = teams.map((team) => ({ team, shift: shifts?.[String(team)] })).filter((entry) => entry.shift);
          const markings = [...new Set(entries.map(({ shift }) => shift?.marcacao).filter((mark): mark is string => !!mark))];
          const outOfRange = (!!min && iso < min) || (!!max && iso > max);
          const title = entries.map(({ team, shift }) => `Equipe ${team}: ${calendario?.legenda[shift!.turno] ?? shift!.turno}`)
            .concat(markings).join(" · ");
          return <button key={iso} type="button" disabled={disabled || outOfRange} title={title || undefined}
            aria-label={`${day.toLocaleDateString("pt-BR")}${title ? ` · ${title}` : ""}`}
            aria-pressed={iso === value}
            onClick={() => selectDate(day)}
            className={`relative flex min-h-10 min-w-0 flex-col items-center justify-center rounded border text-[11px] transition disabled:cursor-not-allowed disabled:opacity-25 ${
              iso === value ? "border-sky-300 bg-sky-400/20 text-white" : inMonth ? "border-white/5 text-slate-200 hover:border-sky-400/40 hover:bg-sky-400/10" : "border-transparent text-slate-600 hover:bg-white/5"
            }`}>
            <span>{day.getDate()}</span>
            <span className="flex h-2.5 items-center justify-center gap-0.5 text-[7px] leading-none">
              {entries.map(({ team, shift }) => <span key={team} className={shift?.turno === "F" ? "text-slate-500" : shift?.turno === "X" ? "text-amber-300" : "text-sky-300"}>{shift?.turno}</span>)}
            </span>
            {markings.length > 0 && <span className="absolute right-1 top-1 h-1 w-1 rounded-full bg-amber-300" />}
          </button>;
        })}
      </div>
      {calendario && calendario.ano === visibleMonth.getFullYear() && <div className="mt-3 border-t border-white/10 pt-2">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-slate-400">
          {Object.entries(calendario.legenda).map(([code, description]) => <span key={code}><strong className="text-slate-200">{code}</strong> {description}</span>)}
        </div>
        <p className="mt-2 text-[9px] text-amber-200/80">Ponto âmbar indica marcação operacional no calendário.</p>
      </div>}
    </div>}
  </span>;
}
