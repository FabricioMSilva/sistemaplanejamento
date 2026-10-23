import Head from "next/head";
import { useCallback, useEffect, useState } from "react";
import Dashboard from "@/components/Dashboard";
import Header from "@/components/Header";
import LogPanel from "@/components/LogPanel";
import PreviewPanel from "@/components/PreviewPanel";
import UploadPanel from "@/components/UploadPanel";
import {
  criarOts,
  getDashboard,
  getLogs,
  processarArquivo,
  type DashboardData,
  type LogEntry,
  type ProcessResult,
} from "@/services/api";

const ALLOWED_EXTENSIONS = [".xlsx", ".xls"];

export default function OtPage() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [dashboardData, logData] = await Promise.all([getDashboard(), getLogs()]);
      setDashboard(dashboardData);
      setLogs(logData);
    } catch {
      setDashboard({
        ultimo_arquivo: null,
        total_registros_processados: 0,
        total_pendente: 0,
        status_sistema: "offline",
      });
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function handleSelect(selected: File | null) {
    setError(null);
    setResult(null);
    if (!selected) {
      setFile(null);
      return;
    }
    const extension = selected.name.slice(selected.name.lastIndexOf(".")).toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(extension)) {
      setFile(null);
      setError("Formato inválido. Envie apenas arquivos .xlsx ou .xls.");
      return;
    }
    setFile(selected);
    setLogs((current) => [
      {
        data_hora: new Date().toLocaleString("pt-BR"),
        nivel: "info",
        mensagem: `Arquivo selecionado: ${selected.name}`,
      },
      ...current,
    ]);
  }

  async function handleProcess() {
    if (!file) {
      setError("Selecione um arquivo antes de processar.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const processed = await processarArquivo(file);
      setResult(processed);
      await refresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Falha ao processar o arquivo.";
      setResult(null);
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCriarOts(indices: number[]) {
    if (!result) {
      setError("Processe um arquivo antes de criar OTs.");
      return;
    }
    if (indices.length === 0) {
      setError("Selecione ao menos uma linha para criar OT.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await criarOts(result.id, indices);
      setLogs((current) => [
        {
          data_hora: new Date().toLocaleString("pt-BR"),
          nivel: "info",
          mensagem: created.mensagem,
          quantidade_processada: created.quantidade,
        },
        ...current,
      ]);
      await refresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Falha ao criar as OTs selecionadas.";
      setError(message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <Head>
        <title>RoboMario | Criar OT</title>
      </Head>
      <main className="mx-auto flex min-h-screen max-w-7xl flex-col gap-5 px-4 py-6">
        <Header status={dashboard?.status_sistema || "offline"} />
        <Dashboard data={dashboard} />
        <UploadPanel file={file} loading={loading} onSelect={handleSelect} onProcess={handleProcess} />
        <div className="grid gap-5">
          <LogPanel logs={logs} />
          <PreviewPanel result={result} error={error} creating={creating} onCriarOts={handleCriarOts} />
        </div>
      </main>
    </>
  );
}