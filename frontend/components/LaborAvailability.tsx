import { useState } from "react";
import { daysBetween } from "@/utils/pcmDashboard";
import { diasUteis } from "@/utils/laborPlanning";
import PlanningDateInput from "@/components/PlanningDateInput";

type Props = {
  inicio: string; fim: string; matricula: string; disponiveis: string[];
  onChange: (days: string[]) => void; onCopy: () => void; canCopy: boolean;
};

export default function LaborAvailability({ inicio, fim, matricula, disponiveis, onChange, onCopy, canCopy }: Props) {
  const days = daysBetween(inicio, fim);
  const selected = new Set(disponiveis.filter((day) => day >= inicio && day <= fim));
  const [from, setFrom] = useState(inicio);
  const [to, setTo] = useState(fim);
  const weekdays = diasUteis(inicio, fim);
  const mode = !selected.size ? "none" : selected.size === days.length ? "all"
    : selected.size === weekdays.length && weekdays.every((day) => selected.has(day)) ? "weekdays" : "custom";
  return <div className="min-w-56">
    <select aria-label={`Disponibilidade de ${matricula}`} value={mode}
      onChange={(event) => {
        const value = event.target.value;
        onChange(value === "none" ? [] : value === "all" ? days : value === "weekdays" ? weekdays : [...selected]);
      }} className="w-full rounded border border-white/20 bg-navy-950 p-2 text-sm">
      <option value="weekdays">Segunda a sexta · 8 h/dia</option>
      <option value="all">Todos os dias · 8 h/dia</option>
      <option value="custom" disabled>Dias personalizados · 8 h/dia</option>
      <option value="none">Nenhum dia disponível</option>
    </select>
    <p className="my-2 text-xs font-medium text-sky-200" aria-live="polite">{selected.size} dias × 8 h = {selected.size * 8} HH</p>
    <p className="my-2 text-xs text-slate-400">Dias marcados estão disponíveis. Clique para incluir ou retirar, inclusive fins de semana.</p>
      <div className="flex max-h-56 max-w-sm flex-wrap gap-1 overflow-y-auto">
        {days.map((day) => <button key={day} type="button" aria-pressed={selected.has(day)}
          aria-label={`Disponível ${matricula} em ${day}`}
          onClick={() => {
            const next = new Set(selected);
            if (next.has(day)) next.delete(day); else next.add(day);
            onChange([...next].sort());
          }}
          className={`rounded border px-2 py-1 text-xs ${selected.has(day) ? "border-emerald-400 bg-emerald-400/20 text-emerald-200" : "border-white/15 text-slate-400"}`}>
          {new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", timeZone: "UTC" }).format(new Date(`${day}T00:00:00Z`))}
        </button>)}
      </div>
      <div className="my-2 flex flex-wrap items-end gap-2 text-xs">
        <label className="w-36">De<PlanningDateInput aria-label={`Disponibilidade inicial de ${matricula}`} min={inicio} max={fim} value={from} onChange={setFrom} className="rounded bg-navy-950 p-2" /></label>
        <label className="w-36">Até<PlanningDateInput aria-label={`Disponibilidade final de ${matricula}`} min={inicio} max={fim} value={to} onChange={setTo} className="rounded bg-navy-950 p-2" /></label>
        <button type="button" disabled={from < inicio || to > fim || !from || !to || from > to}
          onClick={() => onChange([...new Set([...selected, ...daysBetween(from, to)])].sort())}
          className="pcm-small-button">Marcar intervalo</button>
        <button type="button" disabled={from < inicio || to > fim || !from || !to || from > to}
          onClick={() => onChange([...selected].filter((day) => day < from || day > to).sort())}
          className="pcm-small-button">Retirar intervalo</button>
      </div>
    {canCopy && <button type="button" onClick={onCopy} className="mt-2 text-xs text-sky-300 underline">Copiar dias disponíveis aos executantes selecionados</button>}
  </div>;
}
