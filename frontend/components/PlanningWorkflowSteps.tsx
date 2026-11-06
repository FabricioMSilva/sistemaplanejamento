const STEPS = [
  "Coleta de OTs",
  "Horizonte e equipe",
  "Distribuição da carga",
  "Gerar PDF",
  "Enviar ao BMA",
  "E-mail da equipe",
];

export default function PlanningWorkflowSteps({ active }: { active: number }) {
  return <nav aria-label="Etapas do planejamento" className="mb-5 overflow-x-auto">
    <ol className="flex min-w-[690px] items-center">
      {STEPS.map((label, index) => {
        const step = index + 1;
        const complete = step < active;
        return <li key={label} className="flex flex-1 items-center last:flex-none">
          <div className="flex items-center gap-2">
            <span aria-current={step === active ? "step" : undefined}
              className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border text-xs font-semibold ${step === active ? "border-sky-300 bg-sky-300 text-slate-950" : complete ? "border-emerald-400 bg-emerald-400/15 text-emerald-200" : "border-white/15 bg-white/5 text-slate-500"}`}>
              {String(step).padStart(2, "0")}
            </span>
            <span className={`max-w-24 text-[11px] leading-tight sm:max-w-none sm:text-xs ${step === active ? "font-semibold text-white" : complete ? "text-emerald-200" : "text-slate-500"}`}>{label}</span>
          </div>
          {step < STEPS.length && <span aria-hidden="true" className={`mx-2 h-px flex-1 ${complete ? "bg-emerald-400/50" : "bg-white/10"}`} />}
        </li>;
      })}
    </ol>
  </nav>;
}