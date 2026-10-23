import { useEffect, useRef, useState } from "react";
import { FileSpreadsheet, Loader2 } from "lucide-react";
import { obterSincronizacao, sincronizarOrdensTrabalho } from "@/services/api";
import { exportNfeReport } from "@/services/pcm";

export default function NfeReportButton() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const active = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function generate() {
    if (active.current) return;
    active.current = true;
    setBusy(true); setError("");
    setMessage("Atualizando RES-TC-NF no BMA. Conclua o login/MFA no Firefox, se solicitado.");
    try {
      const { job_id: jobId } = await sincronizarOrdensTrabalho(["RES-TC-NF"]);
      while (mounted.current) {
        const run = await obterSincronizacao(jobId);
        if (!mounted.current) return;
        if (run.status === "failed") throw new Error(run.erro || run.mensagem);
        if (run.status === "completed") {
          setMessage("Gerando Planejamento NFE.xlsx...");
          await exportNfeReport(jobId);
          if (mounted.current) setMessage(`${run.ots_salvas} OTs atualizadas do BMA exportadas. Aba Report, sem os filtros da tela.`);
          return;
        }
        setMessage(`${run.mensagem} · ${run.ots_lidas} OTs lidas`);
        await new Promise((resolve) => setTimeout(resolve, 1200));
      }
    } catch (reason) {
      if (mounted.current) {
        setMessage("");
        setError(reason instanceof Error ? reason.message : "Falha ao atualizar o BMA e gerar o Excel NFE.");
      }
    } finally {
      active.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <div className="max-w-xl">
    <button type="button" disabled={busy} onClick={() => void generate()} className="pcm-primary-button"
      title="Atualiza as OTs abertas do setor RES-TC-NF no BMA e baixa o modelo Report, sem filtro de data ou tipo">
      {busy ? <Loader2 size={16} className="animate-spin" /> : <FileSpreadsheet size={16} />}
      {busy ? "Atualizando BMA · Excel NFE..." : "Atualizar BMA e gerar Excel NFE"}
    </button>
    {message && <p role="status" className="mt-2 text-xs text-sky-200">{message}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-red-300">{error}</p>}
  </div>;
}
