import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { CalendarDays, ChartNoAxesCombined, Clock3 } from "lucide-react";
import type { PcmData } from "@/utils/pcmDashboard";
import { daysBetween, formatNumber } from "@/utils/pcmDashboard";

const colors = ["#f5c14a", "#38bdf8", "#34d399", "#a78bfa", "#fb923c", "#f472b6"];
const tooltipStyle = { backgroundColor: "#10243b", border: "1px solid #30465f", borderRadius: 12, color: "#e2e8f0" };
const axis = { fill: "#94a3b8", fontSize: 11 };

export function PcmCharts({ data }: { data: PcmData }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="pcm-panel p-5">
        <h2 className="pcm-title"><ChartNoAxesCombined size={17} /> Capacidade por especialidade</h2>
        <p className="pcm-caption">H×H disponível da equipe salva. Não é ocupação por OT.</p>
        {data.disciplines.some((row) => row.hours > 0) ? (
          <>
            <div className="h-56" role="img" aria-label="Distribuição das horas disponíveis por especialidade">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data.disciplines} dataKey="hours" nameKey="name" innerRadius={58} outerRadius={87} paddingAngle={3}>
                    {data.disciplines.map((row, index) => <Cell key={row.name} fill={colors[index % colors.length]} stroke="transparent" />)}
                  </Pie>
                  <Tooltip contentStyle={tooltipStyle} formatter={(value) => `${formatNumber(Number(value))} H×H`} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <ul className="space-y-2 text-xs">
              {data.disciplines.map((row, index) => <li key={row.name} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: colors[index % colors.length] }} />{row.name}</span>
                <strong className="shrink-0 text-slate-200">{formatNumber(row.hours)} h</strong>
              </li>)}
            </ul>
          </>
        ) : <EmptyChart text="Defina a equipe para visualizar a capacidade por especialidade." />}
      </section>
      <section className="pcm-panel p-5">
        <h2 className="pcm-title"><ChartNoAxesCombined size={17} /> Demanda de HH por tipo de OT</h2>
        <p className="pcm-caption">Soma das estimativas coletadas de toda a carteira aberta.</p>
        {data.types.some((row) => row.hours > 0) ? (
          <div className="mt-4 h-64" role="img" aria-label="Horas estimadas por tipo de ordem de trabalho">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.types} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#ffffff0b" vertical={false} />
                <XAxis dataKey="name" tick={axis} axisLine={false} tickLine={false} />
                <YAxis tick={axis} axisLine={false} tickLine={false} width={46} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "#ffffff08" }} formatter={(value) => `${formatNumber(Number(value))} h`} />
                <Bar dataKey="hours" name="HH estimado" fill="#38bdf8" radius={[5, 5, 0, 0]} maxBarSize={34} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : <EmptyChart text="Não há estimativas de HH para exibir nesta carteira." />}
        <p className="mt-3 text-xs text-slate-500">Estimativas ausentes: {data.missingHours} OTs. Tipo S/I: PM · E: corretiva.</p>
      </section>
    </div>
  );
}

function EmptyChart({ text }: { text: string }) {
  return <div className="flex min-h-48 items-center justify-center rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-slate-500">{text}</div>;
}

export function PcmTemporal({ data, inicio, fim }: { data: PcmData; inicio: string; fim: string }) {
  const [view, setView] = useState<"calendar" | "gantt">("calendar");
  const [offset, setOffset] = useState(0);
  const total = data.daily.length;
  const safeOffset = Math.min(offset, Math.max(0, Math.floor((total - 1) / 28) * 28));
  const days = data.daily.slice(safeOffset, safeOffset + 28);
  const first = days[0]?.date;
  const last = days[days.length - 1]?.date;
  const gantt = data.gantt.filter((row) => first && last && row.start <= last && row.end >= first);
  const leading = first ? (new Date(`${first}T00:00:00Z`).getUTCDay() + 6) % 7 : 0;
  return (
    <section className="pcm-panel overflow-hidden" id="pcm-temporal">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-5">
        <div>
          <h2 className="pcm-title"><CalendarDays size={17} /> Horizonte de planejamento</h2>
          <p className="pcm-caption">Capacidade diária e OTs com início programado no BMA.</p>
        </div>
        <div className="flex rounded-lg border border-white/10 bg-black/10 p-1" role="group" aria-label="Visualização temporal">
          {([{ key: "calendar", label: "Calendário" }, { key: "gantt", label: "Timeline / Gantt" }] as const).map((item) =>
            <button key={item.key} type="button" aria-pressed={view === item.key} onClick={() => setView(item.key)}
              className={`rounded-md px-3 py-2 text-xs font-medium ${view === item.key ? "bg-sky-400/15 text-sky-300" : "text-slate-400 hover:text-white"}`}>{item.label}</button>)}
        </div>
      </div>
      {!total ? <div className="p-5"><EmptyChart text="Salve o período e a mão de obra para abrir a visão temporal." /></div> : (
        <div className="p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-slate-400">{first?.split("-").reverse().join("/")} — {last?.split("-").reverse().join("/")} · {total} dias no período</p>
            <div className="flex gap-2">
              <button type="button" className="pcm-small-button" disabled={!safeOffset} onClick={() => setOffset(safeOffset - 28)}>Anterior</button>
              <button type="button" className="pcm-small-button" disabled={safeOffset + 28 >= total} onClick={() => setOffset(safeOffset + 28)}>Próximos 28 dias</button>
            </div>
          </div>
          {view === "calendar" ? (
            <>
              <div className="mb-2 grid grid-cols-7 gap-1 text-center text-[10px] uppercase tracking-wider text-slate-500">
                {["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"].map((day) => <span key={day}>{day}</span>)}
              </div>
              <div className="grid grid-cols-7 gap-1.5">
                {Array.from({ length: leading }, (_, index) => <div key={`empty-${index}`} />)}
                {days.map((day) => {
                  const overload = day.capacity !== null && day.demand > day.capacity;
                  return <div key={day.date}
                    title={`${day.date}: capacidade ${formatNumber(day.capacity)} h; demanda no início ${formatNumber(day.demand)} h; ${day.orders} OTs`}
                    className={`min-h-20 rounded-lg border p-2 sm:min-h-24 ${overload ? "border-rose-400/30 bg-rose-400/10" : day.capacity ? "border-sky-400/20 bg-sky-400/5" : "border-white/5 bg-white/[0.02]"}`}>
                    <span className="text-xs font-semibold text-slate-200">{day.date.slice(8)}</span>
                    <p className="mt-2 text-[10px] text-slate-400 sm:text-xs"><span className="hidden sm:inline">Cap. </span>{formatNumber(day.capacity)} h</p>
                    <p className={`text-[10px] sm:text-xs ${overload ? "text-rose-300" : "text-sky-300"}`}>{day.orders} <span className="hidden sm:inline">OTs</span></p>
                  </div>;
                })}
              </div>
            </>
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-[640px]">
                <div className="mb-3 flex justify-between pl-36 text-xs text-slate-500"><span>{first}</span><span>{last}</span></div>
                {gantt.slice(0, 12).map(({ order, start, end }) => {
                  const clippedStart = start < first ? first : start;
                  const clippedEnd = end > last ? last : end;
                  const left = daysBetween(first, clippedStart).length - 1;
                  const width = daysBetween(clippedStart, clippedEnd).length;
                  return <div key={`${order.siteid}-${order.wonum}`} className="mb-3 flex items-center gap-3 text-xs">
                    <span className="w-32 shrink-0 truncate text-slate-300" title={order.dados.description?.toString()}>{order.wonum}</span>
                    <div className="relative h-7 flex-1 rounded bg-white/[0.03]">
                      <div title={`${order.wonum}: ${start} a ${end}`} className="absolute top-1 h-5 min-w-1 rounded bg-sky-400/50"
                        style={{ left: `${left / days.length * 100}%`, width: `${width / days.length * 100}%` }} />
                    </div>
                  </div>;
                })}
                {!gantt.length && <EmptyChart text="Nenhuma OT com início e fim programados válidos neste intervalo. Datas-alvo não são tratadas como programação confirmada." />}
                {gantt.length > 12 && <p className="text-xs text-slate-400">Exibindo 12 de {gantt.length} OTs neste intervalo. Consulte a carteira para os detalhes.</p>}
              </div>
            </div>
          )}
          <div className="mt-6 h-52" role="img" aria-label="Carga de trabalho diária e capacidade">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={days} margin={{ left: 0, right: 5 }}>
                <CartesianGrid stroke="#ffffff0a" vertical={false} />
                <XAxis dataKey="label" tick={axis} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={axis} axisLine={false} tickLine={false} width={40} />
                <Tooltip contentStyle={tooltipStyle} formatter={(value) => `${formatNumber(Number(value))} h`} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="capacity" name="Capacidade base" fill="#38bdf8" radius={[3, 3, 0, 0]} />
                <Bar dataKey="demand" name="HH de OTs com início no dia" fill="#f5c14a" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 flex items-start gap-2 rounded-lg bg-white/[0.03] p-3 text-xs leading-relaxed text-slate-400">
            <Clock3 size={15} className="mt-0.5 shrink-0" />
            <p>Heatmap: vermelho = HH de OTs iniciadas no dia acima da capacidade base; não é alocação intradia.
              O HH da OT é contabilizado integralmente no início programado. Ajustes gerais ({formatNumber(data.adjustments)} h) entram no total da equipe, mas não são distribuídos entre dias. Horizonte salvo: {inicio} a {fim}.</p>
          </div>
        </div>
      )}
    </section>
  );
}
