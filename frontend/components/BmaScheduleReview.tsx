import { useEffect, useState } from "react";
import { Monitor, Square, X } from "lucide-react";
import {
  getBmaPageMonitor, startBmaPageMonitor, stopBmaPageMonitor,
  type BmaPageMonitor, type WorkPlan,
} from "@/services/pcm";
import { plannedBmaOrders } from "@/utils/plannedLabor";
import { formatPlanningDate } from "@/utils/laborPlanning";

type Props = {
  plan: WorkPlan;
  onClose: () => void;
};

export default function BmaScheduleReview({ plan, onClose }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [monitorId, setMonitorId] = useState("");
  const [monitor, setMonitor] = useState<BmaPageMonitor | null>(null);
  const [monitorError, setMonitorError] = useState("");
  const [launching, setLaunching] = useState(false);
  const orders = plannedBmaOrders(plan);
  const selectedOrders = orders.filter((row) => selected.includes(row.key));
  useEffect(() => {
    if (!monitorId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const state = await getBmaPageMonitor(monitorId);
        if (cancelled) return;
        setMonitor(state);
        if (["starting", "monitoring", "stopping"].includes(state.status))
          timer = setTimeout(poll, 1000);
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "Falha ao consultar o monitor.";
          if (message.includes("Monitor BMA não encontrado")) {
            setMonitor(null);
            setMonitorId("");
            setMonitorError("A sessão do monitor foi encerrada pelo backend. Inicie o monitor novamente.");
          } else setMonitorError(message);
        }
      }
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [monitorId]);

  async function startMonitor() {
    if (!selectedOrders.length || launching) return;
    const invalidOrder = selectedOrders.find((row) => !row.planning.assignments.length
      || row.planning.assignments.some((assignment) => !assignment.laborcode || assignment.horas <= 0));
    if (invalidOrder) {
      setMonitorError(`A OT ${invalidOrder.order.wonum} está sem matrícula ou horas válidas no planejamento.`);
      return;
    }
    setLaunching(true);
    setMonitorError("");
    try {
      const { monitor_id } = await startBmaPageMonitor(selectedOrders.map((row) => ({
        siteid: row.order.siteid,
        wonum: row.order.wonum,
        ...row.planning,
      })));
      setMonitorId(monitor_id);
      setMonitor({ monitor_id, status: "starting", message: "Iniciando Firefox...", fields: [] });
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : "Não foi possível iniciar o monitor.");
    } finally {
      setLaunching(false);
    }
  }

  async function stopMonitor() {
    if (!monitorId) return;
    try { setMonitor(await stopBmaPageMonitor(monitorId)); }
    catch (error) { setMonitorError(error instanceof Error ? error.message : "Não foi possível parar o monitor."); }
  }

  function closeReview() {
    if (monitorId) void stopMonitor();
    onClose();
  }

  return <div role="dialog" aria-modal="true" aria-labelledby="bma-review-title"
    className="fixed inset-0 z-[110] overflow-y-auto bg-black/75 p-3 sm:p-8"
    onKeyDown={(event) => { if (event.key === "Escape") closeReview(); }}>
    <section className="pcm-panel mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 id="bma-review-title" className="pcm-title">Revisar OTs para o BMA</h2>
          <p className="mt-1 text-xs text-slate-400">Revisão {plan.revisao} · {orders.length} OTs com alocação no cronograma.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" aria-label="Fechar revisão BMA" className="pcm-small-button" onClick={closeReview}><X size={16} /></button>
        </div>
      </header>
      {monitorError && <p role="alert" className="text-sm text-rose-300">{monitorError}</p>}
      {monitor && <section aria-label="Monitor da página do BMA" className="space-y-3 rounded border border-sky-300/20 bg-sky-300/5 p-3">
        <div className="flex items-center justify-between gap-3">
          <div><h3 className="text-sm font-semibold text-sky-100">Monitor da página do BMA · {monitor.status}</h3>
            <p role="status" className="mt-1 text-xs text-slate-300">{monitor.message}</p>
            <p className="mt-1 text-[11px] text-slate-500">Tempo decorrido: {monitor.elapsed_seconds ?? 0} s</p></div>
            {monitor.page_title && <p className="mt-2 text-xs font-medium text-white">Página: {monitor.page_title}</p>}
            {monitor.page_url && <p className="mt-1 break-all font-mono text-[10px] text-slate-500">{monitor.page_url}</p>}
          {["starting", "monitoring", "stopping"].includes(monitor.status) && <button type="button" className="pcm-small-button" onClick={() => void stopMonitor()}>
            <Square size={13} /> Parar monitor
          </button>}
        </div>
        {!!monitor.fields.length && <div className="max-h-48 overflow-auto rounded border border-white/10">
          <table className="w-full text-left text-xs"><thead className="sticky top-0 bg-[#102235] text-slate-300">
            <tr><th className="p-2">Controle</th><th className="p-2">Rótulo</th><th className="p-2">ID</th><th className="p-2">Frame</th><th className="p-2">Estado</th></tr>
          </thead><tbody>{monitor.fields.map((field, index) => <tr key={`${field.id}-${field.name}-${index}`} className="border-t border-white/5">
            <td className="p-2">{field.tag}{field.type ? ` · ${field.type}` : ""}</td><td className="p-2">{field.label}</td>
            <td className="p-2 font-mono text-slate-400">{field.id || field.name || "sem identificador"}</td>
            <td className="p-2 font-mono text-slate-500">{field.frame ?? "principal"}</td>
            <td className="p-2">{field.disabled ? "desabilitado" : "habilitado"}</td>
          </tr>)}</tbody></table>
        </div>}
      </section>}
      <p role="status" className="rounded border border-amber-300/30 bg-amber-300/10 p-3 text-sm text-amber-100">
        Selecione uma OT por vez. O monitor pesquisa somente a OT selecionada; nenhum dado será salvo no Maximo.
      </p>
      {!orders.length ? <p className="py-8 text-center text-sm text-slate-400">Nenhuma OT alocada no cronograma.</p> :
        <div className="max-h-[55vh] overflow-auto rounded border border-white/10">
          <table className="w-full min-w-[760px] border-collapse text-left text-xs">
            <thead className="sticky top-0 bg-[#102235] text-slate-300">
              <tr><th className="p-3">Selecionar</th>
                <th className="p-3">OT</th><th className="p-3">Descrição</th><th className="p-3">Datas e executantes</th></tr>
            </thead>
            <tbody>
              {orders.map((row) => <tr key={row.key} className="border-t border-white/10 align-top">
                <td className="p-3"><input type="radio" name="bma-work-order"
                  aria-label={`Selecionar OT ${row.order.wonum}`}
                  checked={selected.includes(row.key)}
                  onChange={() => setSelected([row.key])} /></td>
                <th scope="row" className="p-3 font-semibold text-sky-200">{row.order.wonum}</th>
                <td className="p-3 text-slate-300">{row.description || "Sem descrição"}</td>
                <td className="space-y-2 p-3">
                  {row.allocations.map((allocation, index) => <div key={`${allocation.dia}-${index}`} className="border-b border-white/5 pb-2 last:border-0 last:pb-0">
                    <p className="font-medium text-white">{formatPlanningDate(allocation.dia) || allocation.dia} · {allocation.horas} h</p>
                    <p className="mt-1 text-slate-400">{allocation.executantes.join(", ") || "Sem executante informado"}</p>
                  </div>)}
                </td>
              </tr>)}
            </tbody>
          </table>
        </div>}
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4">
        <p className="text-xs text-slate-400">{selectedOrders.length
          ? `OT ${selectedOrders[0].order.wonum} selecionada. O rastreio pesquisará somente esta OT.`
          : "Selecione uma OT; sem seleção o botão fica desabilitado."}</p>
        <div className="flex gap-2">
          <button type="button" className="pcm-small-button" onClick={closeReview}>Fechar</button>
          <button type="button" className="pcm-primary-button" disabled={!selectedOrders.length || launching}
            onClick={() => void startMonitor()}>
            <Monitor size={14} /> {launching ? "Iniciando monitor BMA..." : "Enviar Planejamento BMA"}
          </button>
        </div>
      </footer>
    </section>
  </div>;
}