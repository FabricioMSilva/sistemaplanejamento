import { formatNumber } from "@/utils/pcmDashboard";

export type ParetoItem = { label: string; value: number; availableHours: number | null };

type Props = {
  title: string;
  items: ParetoItem[];
  highlight?: string[];
};

function niceMax(value: number): number {
  if (value <= 5) return 5;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}

function HorizontalBar({ value, maximum, color }: { value: number; maximum: number; color: string }) {
  return (
    <div className="relative h-3 flex-1 rounded-sm bg-slate-100/5">
      <div className="h-full rounded-sm" style={{ width: `${value / maximum * 100}%`, backgroundColor: color }} />
    </div>
  );
}

export default function ParetoChart({ title, items, highlight = [] }: Props) {
  const data = [...items].filter((item) => item.value > 0).sort((a, b) => b.value - a.value);
  const totalPlanned = data.reduce((sum, item) => sum + item.value, 0);
  const capacitiesReady = data.every((item) => item.availableHours !== null);
  const totalAvailable = capacitiesReady
    ? data.reduce((sum, item) => sum + (item.availableHours ?? 0), 0)
    : null;
  const maximum = niceMax(Math.max(...data.flatMap((item) => [item.value, item.availableHours ?? 0])));
  const ticks = Array.from({ length: 5 }, (_, index) => maximum * index / 4);

  if (!data.length) {
    return (
      <section className="rounded-lg border border-white/10 bg-navy-900/70 p-4" aria-label={title}>
        <h2 className="text-base font-semibold text-white">{title}</h2>
        <p className="mt-4 text-sm text-slate-400">Sem dados para exibir.</p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-white/10 bg-navy-900/70 p-4" aria-label={title}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-white">{title}</h2>
        <span className="text-xs text-slate-400">{formatNumber(totalPlanned)} h planejadas</span>
      </div>

      <div className="mt-4 space-y-3" role="img" aria-label={`${title}: ${data.map((item) => `${item.label}, ${formatNumber(item.value)} horas planejadas, ${item.availableHours === null ? "capacidade indisponível" : `${formatNumber(item.availableHours)} horas disponíveis`}`).join("; ")}`}>
        {data.map((item) => {
          const active = highlight.length === 0 || highlight.includes(item.label);
          return (
            <div key={item.label} className="grid grid-cols-[minmax(6.5rem,10rem)_minmax(0,1fr)] items-center gap-x-4 gap-y-1.5 text-xs sm:grid-cols-[minmax(8rem,13rem)_minmax(0,1fr)]">
              <span className={`row-span-2 truncate text-right ${active ? "text-slate-200" : "text-slate-500"}`} title={item.label}>{item.label}</span>
              <div className="flex min-w-0 items-center gap-2">
                <HorizontalBar value={item.value} maximum={maximum} color="#fbbf24" />
                <span className="w-12 shrink-0 text-slate-300">{formatNumber(item.value)}</span>
              </div>
              <div className="flex min-w-0 items-center gap-2">
                <HorizontalBar value={item.availableHours ?? 0} maximum={maximum} color="#16a34a" />
                <span className="w-12 shrink-0 text-slate-300">{formatNumber(item.availableHours)}</span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 grid grid-cols-[minmax(6.5rem,10rem)_minmax(0,1fr)] gap-x-4 text-[10px] text-slate-500 sm:grid-cols-[minmax(8rem,13rem)_minmax(0,1fr)]">
        <span />
        <div className="flex justify-between pr-12">{ticks.map((tick, index) => <span key={tick} className={index % 2 === 1 ? "hidden sm:inline" : ""}>{formatNumber(tick)}</span>)}</div>
      </div>
      <p className="mt-1 text-right text-[10px] text-slate-500">Horas-Homem (h)</p>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-slate-400">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-chart-2" />HH planejado</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-chart-3" />HH disponível</span>
      </div>

      <div className="mt-4 overflow-x-auto rounded-md border border-white/10">
        <table className="w-full min-w-[560px] border-collapse text-[11px]">
          <caption className="border-b border-white/10 px-3 py-2 text-left font-semibold text-white">Tabela de dados</caption>
          <thead className="bg-white/5 text-slate-300">
            <tr>
              <th scope="col" className="px-3 py-1.5 text-left">Especialidade</th>
              <th scope="col" className="px-3 py-1.5 text-right">HH planejado (h)</th>
              <th scope="col" className="px-3 py-1.5 text-right">HH disponível (h)</th>
              <th scope="col" className="px-3 py-1.5 text-right">Diferença (h)</th>
              <th scope="col" className="px-3 py-1.5 text-right">Cobertura</th>
            </tr>
          </thead>
          <tbody>
            {data.map((item) => <tr key={item.label} className="border-t border-white/5 text-slate-300">
              <th scope="row" className="px-3 py-1 text-left font-normal">{item.label}</th>
              <td className="px-3 py-1 text-right">{formatNumber(item.value)}</td>
              <td className="px-3 py-1 text-right">{formatNumber(item.availableHours)}</td>
              <td className="px-3 py-1 text-right">{item.availableHours === null ? "—" : formatNumber(item.availableHours - item.value)}</td>
              <td className="px-3 py-1 text-right">{item.availableHours === null ? "—" : `${formatNumber(item.availableHours / item.value * 100)}%`}</td>
            </tr>)}
          </tbody>
          <tfoot className="border-t border-white/10 bg-white/5 font-semibold text-white">
            <tr>
              <th scope="row" className="px-3 py-1.5 text-left">Total</th>
              <td className="px-3 py-1.5 text-right">{formatNumber(totalPlanned)}</td>
              <td className="px-3 py-1.5 text-right">{formatNumber(totalAvailable)}</td>
              <td className="px-3 py-1.5 text-right">{totalAvailable === null ? "—" : formatNumber(totalAvailable - totalPlanned)}</td>
              <td className="px-3 py-1.5 text-right">{totalAvailable === null ? "—" : `${formatNumber(totalAvailable / totalPlanned * 100)}%`}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}
