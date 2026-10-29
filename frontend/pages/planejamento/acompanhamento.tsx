import Head from "next/head";
import Link from "next/link";
import { useEffect, useState } from "react";
import { CalendarDays, RefreshCw, Trash2 } from "lucide-react";
import { deleteWorkPlan, listWorkPlans, type PlanSummary } from "@/services/pcm";
import { formatPlanningDate } from "@/utils/laborPlanning";
import { normalize } from "@/utils/orderFilters";

export default function FollowUpPage() {
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [deleting, setDeleting] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError("");
    listWorkPlans().then((rows) => { if (!cancelled) setPlans(rows); })
      .catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "Falha ao carregar planos."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [attempt]);
  const visible = plans.filter((p) => (!status || p.status === status)
    && normalize(`${p.planejador} ${p.setores.join(" ")} ${formatPlanningDate(p.inicio)} ${formatPlanningDate(p.fim)}`).includes(normalize(search)));
  async function removePlan(plan: PlanSummary) {
    const statusLabel = plan.status === "confirmado" ? "confirmado" : "rascunho";
    if (!window.confirm(`Excluir o planejamento ${formatPlanningDate(plan.inicio)} a ${formatPlanningDate(plan.fim)} (${statusLabel}) e todas as revisões e PDFs? Esta ação não pode ser desfeita.`)) return;
    setDeleting(plan.id); setError(""); setMessage("");
    try {
      await deleteWorkPlan(plan.id);
      setPlans((current) => current.filter((item) => item.id !== plan.id));
      setMessage(`Planejamento ${formatPlanningDate(plan.inicio)} a ${formatPlanningDate(plan.fim)} excluído, incluindo revisões e PDFs locais.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao excluir o planejamento.");
    } finally { setDeleting(""); }
  }
  return <>
    <Head><title>Acompanhar planejamentos | Centro PCM</title></Head>
    <main className="pcm-workspace mx-auto min-h-screen max-w-[1600px] space-y-5 p-4 lg:p-8">
      <header className="pcm-panel flex flex-wrap items-center justify-between gap-4 p-6">
        <div><Link href="/planejamento" className="text-xs text-sky-300">← Coleta e novo planejamento</Link>
          <h1 className="mt-3 flex items-center gap-3 text-2xl font-semibold text-white"><CalendarDays /> Acompanhar planejamentos</h1>
          <p className="mt-2 text-sm text-slate-400">Prepare na sexta-feira, acompanhe a semana de execução e registre cada reprogramação com seu cronograma.</p></div>
        <button className="pcm-small-button" disabled={loading} onClick={() => setAttempt(attempt + 1)}><RefreshCw size={15} /> Atualizar lista</button>
      </header>
      <p className="rounded-lg border border-amber-400/20 bg-amber-400/5 p-4 text-xs text-amber-100">Confirmações e PDFs são locais ao projeto. BMA e SharePoint aguardam configuração. O identificador do planejador é declarado, não uma aprovação autenticada.</p>
      <div className="flex flex-wrap gap-3">
        <input className="min-w-64 flex-1 rounded-lg border border-white/15 bg-[#081729] p-3 text-sm text-white" aria-label="Buscar planejamentos" placeholder="Setor, planejador ou data dd/mm/aaaa" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="rounded-lg border border-white/15 bg-[#081729] p-3 text-sm text-white" aria-label="Status do planejamento" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Todos os status</option><option value="rascunho">Rascunhos</option><option value="confirmado">Confirmados localmente</option></select>
      </div>
      {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
      {message && <p role="status" className="text-sm text-emerald-300">{message}</p>}
      {loading ? <p role="status" className="text-slate-400">Carregando...</p> : <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {!visible.length && <p className="text-sm text-slate-400">Nenhum planejamento encontrado. Na carteira, defina a equipe e clique em Planejar PM ou Planejar Corretiva.</p>}
        {visible.map((p) => <article key={p.id} className="pcm-panel space-y-3 p-5">
          <div className="flex items-center justify-between"><span className="pcm-badge text-sky-200">{p.status === "confirmado" ? "Confirmado localmente" : "Rascunho"}</span><span className="text-xs text-slate-500">r{p.revisao}</span></div>
          <h2 className="text-lg font-semibold text-white">{formatPlanningDate(p.inicio)} – {formatPlanningDate(p.fim)}</h2>
          <p className="text-sm text-slate-300">{p.setores.join(" · ")}</p>
          <p className="text-xs text-slate-400">Planejador: {p.planejador}<br />Última revisão: {new Date(p.atualizado_em).toLocaleString("pt-BR")}</p>
          <p className="text-xs text-slate-500">{p.motivo}</p>
          <div className="flex flex-wrap gap-2">
            <Link href={{ pathname: "/planejamento/alocacao", query: { plano: p.id } }} className="pcm-primary-button inline-flex">Abrir cronograma e reprogramar →</Link>
            <button type="button" aria-label={`Excluir planejamento ${p.inicio} a ${p.fim}`} title="Excluir planejamento e todas as revisões locais"
              disabled={!!deleting} onClick={() => void removePlan(p)} className="pcm-small-button border-rose-400/40 text-rose-300 hover:bg-rose-400/10 disabled:opacity-50">
              <Trash2 size={15} /> {deleting === p.id ? "Excluindo..." : "Excluir"}
            </button>
          </div>
        </article>)}
      </section>}
    </main>
  </>;
}
