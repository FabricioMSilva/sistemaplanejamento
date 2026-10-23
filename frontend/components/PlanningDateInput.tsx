import { useEffect, useRef, useState } from "react";
import { CalendarDays } from "lucide-react";
import { formatPlanningDate, parsePlanningDate } from "@/utils/laborPlanning";

type Props = {
  value: string; onChange: (value: string) => void; min?: string; max?: string;
  disabled?: boolean; className?: string; "aria-label": string;
};

export default function PlanningDateInput({ value, onChange, min, max, disabled, className, "aria-label": label }: Props) {
  const [draft, setDraft] = useState(() => formatPlanningDate(value));
  const lastEmitted = useRef(value);
  const picker = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (value !== lastEmitted.current) {
      setDraft(formatPlanningDate(value));
      lastEmitted.current = value;
    }
  }, [value]);
  const parsed = parsePlanningDate(draft);
  const valid = !!parsed && (!min || parsed >= min) && (!max || parsed <= max);
  function change(text: string) {
    const digits = text.replace(/\D/g, "").slice(0, 8);
    const masked = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)].filter(Boolean).join("/");
    setDraft(masked);
    const iso = parsePlanningDate(masked);
    const next = iso && (!min || iso >= min) && (!max || iso <= max) ? iso : "";
    lastEmitted.current = next;
    onChange(next);
  }
  return <span className="relative block min-w-0">
    <input type="text" aria-label={label} placeholder="dd/mm/aaaa" inputMode="numeric" maxLength={10}
      autoComplete="off" value={draft} disabled={disabled} aria-invalid={!!draft && !valid}
      title={draft && !valid ? "Informe uma data válida em dd/mm/aaaa dentro do período permitido." : "dd/mm/aaaa"}
      onChange={(event) => change(event.target.value)}
      className={`${className ?? ""} w-full pr-10 ${draft && !valid ? "border-rose-400" : ""}`} />
    <input ref={picker} type="date" tabIndex={-1} aria-hidden="true"
      className="pointer-events-none absolute bottom-0 right-0 h-px w-px opacity-0"
      value={value} min={min} max={max} disabled={disabled}
      onChange={(event) => { setDraft(formatPlanningDate(event.target.value)); lastEmitted.current = event.target.value; onChange(event.target.value); }} />
    <button type="button" disabled={disabled} aria-label={`Abrir calendário: ${label}`}
      onClick={() => { if (picker.current?.showPicker) picker.current.showPicker(); else picker.current?.focus(); }}
      className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-slate-400 hover:text-sky-200 disabled:opacity-40">
      <CalendarDays size={16} />
    </button>
  </span>;
}
