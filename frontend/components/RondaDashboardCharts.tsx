import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { ChartNoAxesCombined } from "lucide-react";
import { useThemeColors } from "@/lib/useThemeColors";
import type { RondaDashboard } from "@/services/pcm";

type ChartData = RondaDashboard["graficos"];

export default function RondaDashboardCharts({ data }: { data: ChartData }) {
  const colors = useThemeColors();
  const palette = [colors["chart-1"], colors["chart-3"], colors["chart-2"], colors["chart-4"]];
  const tooltipStyle = {
    backgroundColor: colors["surface-elevated"], border: `1px solid ${colors.border}`,
    borderRadius: 8, color: colors.foreground,
  };
  const axis = { fill: colors["muted-foreground"], fontSize: 11 };

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <section className="pcm-panel min-w-0 p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="pcm-title"><ChartNoAxesCombined size={17} /> Rondas concluídas por dia</h2>
            <p className="pcm-caption">Últimos 30 dias · meta: análises 3, equipamentos 3, medidores 2 nos turnos A/C.</p>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground">{data.inicio.slice(5)}–{data.fim.slice(5)}</span>
        </div>
        <div className="mt-4 h-72" role="img" aria-label="Gráfico de linhas das rondas concluídas por modalidade nos últimos 30 dias">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.diario} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}>
              <CartesianGrid stroke={colors.border} vertical={false} />
              <XAxis dataKey="label" tick={axis} axisLine={false} tickLine={false} interval={4} />
              <YAxis allowDecimals={false} domain={[0, "auto"]} tick={axis} axisLine={false} tickLine={false} width={34} />
              <Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [value, name]} labelFormatter={(_label, payload) => payload?.[0]?.payload?.date ?? ""} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {data.modalidades.map((modality, index) => <Line
                key={modality.key} type="monotone" dataKey={modality.key} name={modality.label}
                stroke={palette[index % palette.length]} strokeWidth={2.5} dot={false} activeDot={{ r: 4 }}
                isAnimationActive={false}
              />)}
              {data.modalidades.map((modality, index) => <Line
                key={`${modality.key}-meta`} type="linear" dataKey={`${modality.key}_meta`}
                name={`Meta ${modality.label}`} stroke={palette[index % palette.length]}
                strokeWidth={1} strokeDasharray="5 5" dot={false} activeDot={false}
                isAnimationActive={false}
              />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">Sólida = concluídas; tracejada = meta diária. Dias sem registros aparecem como zero.</p>
      </section>

      <section className="pcm-panel min-w-0 p-4 sm:p-5">
        <div>
          <h2 className="pcm-title"><ChartNoAxesCombined size={17} /> Rondas ausentes por equipe</h2>
          <p className="pcm-caption">Ocorrências nos últimos 30 dias, agrupadas pelo dia da semana e turno previsto.</p>
        </div>
        <div className="mt-4 h-72" role="img" aria-label="Gráfico de rondas ausentes por equipe e dia da semana">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.faltas_por_dia_semana} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}>
              <CartesianGrid stroke={colors.border} vertical={false} />
              <XAxis dataKey="weekday" tick={axis} axisLine={false} tickLine={false} />
              <YAxis allowDecimals={false} domain={[0, "auto"]} tick={axis} axisLine={false} tickLine={false} width={34} />
              <Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [`${value} ronda(s)`, name]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {data.equipes.map((team, index) => <Line
                key={team} type="monotone" dataKey={`equipe_${team}`} name={`Equipe ${team}`}
                stroke={palette[index % palette.length]} strokeWidth={2.5} dot={{ r: 3 }} activeDot={{ r: 5 }}
                isAnimationActive={false}
              />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
        {data.faltas_detalhadas.length > 0 && <div className="mt-3 border-t border-border pt-3">
          <p className="text-xs font-semibold text-foreground">Últimas faltas registradas</p>
          <ul className="mt-2 grid gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
            {data.faltas_detalhadas.slice(-6).reverse().map((entry, index) => <li key={`${entry.date}-${entry.team}-${entry.modalidade}-${index}`}>
              {entry.date.slice(5)} · {entry.weekday} · Equipe {entry.team} · {entry.modalidade} ({entry.turno})
            </li>)}
          </ul>
        </div>}
        {!data.faltas_detalhadas.length && <p className="mt-2 text-xs text-muted-foreground">Nenhuma ronda ausente no calendário sincronizado.</p>}
      </section>
    </div>
  );
}
