export type ParetoItem = { label: string; value: number };

type Props = {
  title: string;
  items: ParetoItem[];
  highlight?: string[];
};

const WIDTH = 460;
const HEIGHT = 300;
const MARGIN = { top: 16, right: 40, bottom: 44, left: 44 };

function niceMax(value: number): number {
  if (value <= 5) return 5;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}

export default function ParetoChart({ title, items, highlight = [] }: Props) {
  const data = [...items].filter((item) => item.value > 0).sort((a, b) => b.value - a.value);
  const total = data.reduce((sum, item) => sum + item.value, 0);

  if (total === 0) {
    return (
      <section className="rounded-lg border border-white/10 bg-navy-900/70 p-4" aria-label={title}>
        <h2 className="text-base font-semibold text-white">{title}</h2>
        <p className="mt-4 text-sm text-slate-400">Sem dados para exibir.</p>
      </section>
    );
  }

  const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const yMax = niceMax(data[0].value);
  const slot = plotWidth / data.length;
  const barWidth = Math.min(slot * 0.7, 48);
  const yCount = (value: number) => MARGIN.top + plotHeight - (value / yMax) * plotHeight;
  const yPercent = (percent: number) => MARGIN.top + plotHeight - (percent / 100) * plotHeight;

  let accumulated = 0;
  const points = data.map((item, index) => {
    accumulated += item.value;
    const percent = (accumulated / total) * 100;
    return { ...item, percent, x: MARGIN.left + slot * index + slot / 2 };
  });
  const line = points.map((point) => `${point.x},${yPercent(point.percent)}`).join(" ");
  const countTicks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => Math.round(yMax * fraction));

  return (
    <section className="rounded-lg border border-white/10 bg-navy-900/70 p-4" aria-label={title}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-white">{title}</h2>
        <span className="text-xs text-slate-400">{total} OTs</span>
      </div>

      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="mt-3 w-full" role="img" aria-label={`${title}: ${data.map((item) => `${item.label} ${item.value}`).join(", ")}`}>
        {countTicks.map((tick) => (
          <g key={tick}>
            <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={yCount(tick)} y2={yCount(tick)} stroke="rgba(255,255,255,0.08)" />
            <text x={MARGIN.left - 6} y={yCount(tick) + 3} textAnchor="end" fontSize="10" fill="#94a3b8">{tick}</text>
          </g>
        ))}
        {[0, 50, 80, 100].map((percent) => (
          <text key={percent} x={WIDTH - MARGIN.right + 6} y={yPercent(percent) + 3} fontSize="10" fill="#94a3b8">{percent}%</text>
        ))}
        <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={yPercent(80)} y2={yPercent(80)} stroke="rgba(251,191,36,0.4)" strokeDasharray="4 4" />

        {points.map((point) => {
          const height = (point.value / yMax) * plotHeight;
          const active = highlight.length === 0 || highlight.includes(point.label);
          return (
            <g key={point.label}>
              <title>{`${point.label}: ${point.value} OTs (${point.percent.toFixed(1)}% acumulado)`}</title>
              <rect
                x={point.x - barWidth / 2}
                y={yCount(point.value)}
                width={barWidth}
                height={height}
                rx="2"
                fill={active ? "#fbbf24" : "#475569"}
              />
              <text x={point.x} y={yCount(point.value) - 4} textAnchor="middle" fontSize="10" fill="#e2e8f0">{point.value}</text>
              <text x={point.x} y={HEIGHT - MARGIN.bottom + 16} textAnchor="middle" fontSize="11" fill="#e2e8f0">{point.label}</text>
            </g>
          );
        })}

        <polyline points={line} fill="none" stroke="#38bdf8" strokeWidth="2" />
        {points.map((point) => (
          <circle key={point.label} cx={point.x} cy={yPercent(point.percent)} r="3" fill="#38bdf8" />
        ))}
      </svg>

      <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-slate-400">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-amber-400" />Quantidade</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-sky-400" />% acumulado</span>
      </div>
    </section>
  );
}
