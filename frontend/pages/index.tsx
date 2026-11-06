import Head from "next/head";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, ListChecks, LoaderCircle, Plus, RefreshCw } from "lucide-react";
import AssetImage from "@/components/ui/AssetImage";
import { APP_BRAND, BRAND_ASSETS } from "@/config/brand-assets";
import { listWorkPlans, type PlanSummary } from "@/services/pcm";
import { formatPlanningDate } from "@/utils/laborPlanning";

export default function HomePage() {
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [plansLoading, setPlansLoading] = useState(true);
  const [plansError, setPlansError] = useState("");
  const [reloadPlans, setReloadPlans] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setPlansLoading(true);
    setPlansError("");
    listWorkPlans().then((items) => {
      if (!cancelled) setPlans(items);
    }).catch((reason: unknown) => {
      if (!cancelled) setPlansError(reason instanceof Error ? reason.message : "Falha ao carregar planejamentos.");
    }).finally(() => {
      if (!cancelled) setPlansLoading(false);
    });
    return () => { cancelled = true; };
  }, [reloadPlans]);

  return (
    <>
      <Head>
        <title>{`Início | ${APP_BRAND.name}`}</title>
        <meta name="description" content={`${APP_BRAND.name} · ${APP_BRAND.subtitle}`} />
      </Head>
      <main className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-6xl flex-col px-5 py-10 sm:px-8 lg:py-16">
        <section className="mb-10 flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="max-w-3xl">
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-primary">{APP_BRAND.subtitle} · {APP_BRAND.context}</p>
            <h1 className="text-3xl font-semibold leading-tight tracking-tight text-foreground sm:text-4xl">Planejamentos de manutenção</h1>
            <p className="mt-3 max-w-xl text-base leading-7 text-muted-foreground">
              Consulte os rascunhos e cronogramas salvos para continuar o trabalho.
            </p>
          </div>
          <AssetImage asset={BRAND_ASSETS.planningLogo} height={245} priority className="max-w-full" />
        </section>
        <section aria-labelledby="programmed-plans-heading">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 id="programmed-plans-heading" className="text-xl font-semibold text-foreground">Já programado</h2>
              <p className="mt-1 text-sm text-muted-foreground">Rascunhos e cronogramas salvos para continuar.</p>
            </div>
            <div className="flex items-center gap-3">
              <Link href="/planejamento/acompanhamento" className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline">
                <ListChecks size={16} aria-hidden="true" /> Ver todos <ArrowRight size={15} aria-hidden="true" />
              </Link>
              <button type="button" className="rounded-lg border border-border p-2 text-muted-foreground hover:text-foreground disabled:opacity-50"
                aria-label="Atualizar planejamentos" title="Atualizar planejamentos" disabled={plansLoading}
                onClick={() => setReloadPlans((current) => current + 1)}>
                {plansLoading ? <LoaderCircle size={17} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={17} aria-hidden="true" />}
              </button>
            </div>
          </div>

          {plansError && <p role="alert" className="mb-3 flex flex-wrap items-center gap-3 text-sm text-destructive">
            {plansError}
            <button type="button" className="underline" onClick={() => setReloadPlans((current) => current + 1)}>Tentar novamente</button>
          </p>}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Link href="/planejamento" className="group flex min-h-44 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-primary/50 bg-primary/5 p-6 text-center transition hover:border-primary hover:bg-primary/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground"><Plus size={24} aria-hidden="true" /></span>
              <span className="text-base font-semibold text-foreground">Criar planejamento</span>
              <span className="text-sm text-muted-foreground">Iniciar uma nova programação de manutenção</span>
            </Link>

            {plansLoading && <div role="status" className="flex min-h-44 items-center justify-center gap-3 rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
              <LoaderCircle size={19} className="animate-spin text-primary" aria-hidden="true" /> Carregando planejamentos...
            </div>}
            {!plansLoading && plans.slice(0, 5).map((plan) => (
              <Link key={plan.id} href={{ pathname: "/planejamento", query: { etapa: "3", plano: plan.id } }}
                className="flex min-h-44 flex-col justify-between rounded-xl border border-border bg-card p-5 shadow-card transition hover:border-primary/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <div className="flex items-start justify-between gap-3">
                  <span className="text-xs font-semibold uppercase text-muted-foreground">{plan.status === "confirmado" ? "Confirmado" : "Rascunho"}</span>
                  <span className="text-xs text-muted-foreground">r{plan.revisao}</span>
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-card-foreground">{formatPlanningDate(plan.inicio)} – {formatPlanningDate(plan.fim)}</h3>
                  <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{plan.setores.join(" · ")}</p>
                </div>
                <span className="inline-flex items-center gap-2 text-sm font-semibold text-primary">Abrir cronograma <ArrowRight size={15} aria-hidden="true" /></span>
              </Link>
            ))}
            {!plansLoading && !plansError && plans.length === 0 && <p className="flex min-h-44 items-center rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">Nenhum planejamento salvo ainda.</p>}
          </div>
        </section>

        <footer className="mt-auto border-t border-border pt-4 text-xs text-muted-foreground">
          {APP_BRAND.name} · {APP_BRAND.subtitle}
        </footer>
      </main>
    </>
  );
}
