import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState, type FocusEvent, type KeyboardEvent } from "react";
import { LoaderCircle } from "lucide-react";
import planningOptions from "@/data/planejamento-opcoes.json";
import {
  obterSincronizacao,
  obterUltimaSincronizacao,
  sincronizarOrdensTrabalho,
  type SyncRun,
} from "@/services/api";

const SYNC_POLL_INTERVAL_MS = 1200;
const syncStatusLabels: Record<SyncRun["status"], string> = {
  queued: "Na fila",
  running: "Em andamento",
  saving: "Gravando no SQL",
  completed: "Concluída",
  failed: "Falhou",
};

function isSyncActive(status: SyncRun["status"]): boolean {
  return status === "queued" || status === "running" || status === "saving";
}

function synchronizationProgress(run: SyncRun | null): number {
  if (!run) return 0;
  if (run.status === "completed") return 100;
  if (run.status === "saving") return 96;
  if (run.status === "queued") return 3;

  const stage = run.etapa.toLowerCase();
  if (stage.includes("autentic") || stage.includes("navegador") || stage.includes("quickrep")) return 12;
  if (stage.includes("concluido")) return 92;
  if (stage.includes("filha")) return 88;
  if (stage.includes("mao_de_obra")) return 92;
  if (stage.includes("oslc")) {
    return Math.min(86, 24 + run.pagina_atual * 8);
  }
  return 8;
}

async function watchSynchronization(
  jobId: string,
  onUpdate: (run: SyncRun) => void,
  isCancelled: () => boolean,
): Promise<SyncRun | null> {
  while (!isCancelled()) {
    const run = await obterSincronizacao(jobId);
    onUpdate(run);
    if (!isSyncActive(run.status)) return run;
    await new Promise((resolve) => setTimeout(resolve, SYNC_POLL_INTERVAL_MS));
  }
  return null;
}

export default function PlanejamentoPage() {
  const router = useRouter();
  const [sectors, setSectors] = useState<string[]>([]);
  const [sectorQuery, setSectorQuery] = useState("");
  const [sectorMenuOpen, setSectorMenuOpen] = useState(false);
  const [activeSectorIndex, setActiveSectorIndex] = useState(0);
  const [syncRun, setSyncRun] = useState<SyncRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const syncedSectors = syncRun?.status === "completed" ? syncRun.setores : [];
  const canContinue =
    !loading &&
    sectors.length > 0 &&
    sectors.length === syncedSectors.length &&
    sectors.every((sector) => syncedSectors.includes(sector));

  const availableSectors = planningOptions.setoresManutencao.filter((option) =>
    !sectors.includes(option) && option.toLowerCase().includes(sectorQuery.trim().toLowerCase()),
  );

  function addSector(code: string) {
    setSectors((current) => current.includes(code) ? current : [...current, code]);
    setSectorQuery("");
    setActiveSectorIndex(0);
    setSectorMenuOpen(true);
  }

  function handleSectorKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSectorMenuOpen(true);
      setActiveSectorIndex((current) => Math.min(current + 1, Math.max(availableSectors.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveSectorIndex((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter" && sectorMenuOpen && availableSectors[activeSectorIndex]) {
      event.preventDefault();
      addSector(availableSectors[activeSectorIndex]);
    } else if (event.key === "Escape") {
      setSectorMenuOpen(false);
    }
  }

  function handleSectorBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setSectorMenuOpen(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function restoreLatestSync() {
      try {
        const latest = await obterUltimaSincronizacao();
        if (!latest || cancelled) return;

        setSyncRun(latest);
        setSectors(latest.setores);
        setLoading(isSyncActive(latest.status));

        const finalRun = isSyncActive(latest.status)
          ? await watchSynchronization(latest.job_id, setSyncRun, () => cancelled)
          : latest;
        if (!finalRun || cancelled) return;

        setSyncRun(finalRun);
        setLoading(false);
        if (finalRun.status === "failed") {
          setError(finalRun.erro || finalRun.mensagem);
        }
      } catch (failure) {
        if (!cancelled) {
          setLoading(false);
          setError(failure instanceof Error ? failure.message : "Falha ao consultar a última atualização.");
        }
      }
    }

    void restoreLatestSync();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSynchronize() {
    setLoading(true);
    setError("");
    setSyncRun(null);
    try {
      const { job_id: jobId } = await sincronizarOrdensTrabalho(sectors);
      const finalRun = await watchSynchronization(jobId, setSyncRun, () => false);
      if (finalRun?.status === "failed") {
        setError(finalRun.erro || finalRun.mensagem);
      }
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Falha ao sincronizar OTs do BMA.");
    } finally {
      setLoading(false);
    }
  }

  function handleContinue() {
    void router.push({ pathname: "/planejamento/ots", query: { setor: sectors } });
  }

  return (
    <>
      <Head>
        <title>Planejamento | BMA Intranet</title>
      </Head>
      <main className="mx-auto min-h-screen max-w-5xl px-4 py-10 sm:px-6">
        <header className="mb-8">
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-accent-400">Planejamento</p>
          <h1 className="mt-2 text-2xl font-semibold text-white">Coletar OTs do BMA</h1>
          <Link href="/planejamento/acompanhamento" className="pcm-primary-button mt-4 inline-flex">Acompanhar planejamentos e revisões →</Link>
        </header>

        <section className="grid gap-6">
          <fieldset className="min-w-0">
            <legend className="text-sm font-medium text-slate-300">Setor de manutenção</legend>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <span className="text-sm text-slate-400" aria-live="polite">
                {sectors.length} de {planningOptions.setoresManutencao.length} selecionados
              </span>
              <div className="flex items-center gap-4">
                <button
                  type="button"
                  onClick={() => {
                    setSectors([...planningOptions.setoresManutencao]);
                    setSectorQuery("");
                  }}
                  className="text-sm font-medium text-accent-400 transition hover:text-accent-500"
                >
                  Marcar todos
                </button>
                <button
                  type="button"
                  onClick={() => setSectors([])}
                  disabled={sectors.length === 0}
                  className="text-sm font-medium text-slate-400 transition hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Limpar
                </button>
              </div>
            </div>

            <div className="relative mt-2" onBlur={handleSectorBlur}>
              <input
                id="sector-combobox"
                type="text"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={sectorMenuOpen}
                aria-controls="sector-options"
                aria-activedescendant={sectorMenuOpen && availableSectors[activeSectorIndex]
                  ? `sector-option-${activeSectorIndex}`
                  : undefined}
                autoComplete="off"
                value={sectorQuery}
                onFocus={() => setSectorMenuOpen(true)}
                onChange={(event) => {
                  setSectorQuery(event.target.value);
                  setActiveSectorIndex(0);
                  setSectorMenuOpen(true);
                }}
                onKeyDown={handleSectorKeyDown}
                placeholder="Digite para buscar e adicionar setores"
                className="block w-full rounded-md border border-white/10 bg-navy-900 px-3 py-3 text-white outline-none placeholder:text-slate-500 focus:border-accent-400"
              />
              {sectorMenuOpen && (
                <ul
                  id="sector-options"
                  role="listbox"
                  aria-multiselectable="true"
                  className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-white/10 bg-navy-900 py-1 shadow-xl"
                >
                  {availableSectors.length ? availableSectors.map((option, index) => (
                    <li
                      id={`sector-option-${index}`}
                      key={option}
                      role="option"
                      aria-selected={index === activeSectorIndex}
                      className={`cursor-pointer px-3 py-2 text-sm text-white hover:bg-white/10 ${index === activeSectorIndex ? "bg-white/10" : ""}`}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => addSector(option)}
                    >
                      {option}
                    </li>
                  )) : (
                    <li className="px-3 py-2 text-sm text-slate-400">Nenhum setor encontrado.</li>
                  )}
                </ul>
              )}
            </div>

            {sectors.length > 0 && (
              <ul className="mt-3 flex flex-wrap gap-2" aria-label="Setores selecionados">
                {sectors.map((sector) => (
                  <li key={sector}>
                    <button
                      type="button"
                      onClick={() => setSectors((current) => current.filter((item) => item !== sector))}
                      aria-label={`Remover setor ${sector}`}
                      className="rounded-md border border-white/10 bg-navy-900 px-2.5 py-1.5 text-xs text-slate-200 transition hover:border-rose-400/60 hover:text-white"
                    >
                      {sector} <span aria-hidden="true">×</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>
        </section>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <button type="button" disabled={sectors.length === 0 || loading} onClick={handleSynchronize}
            className="pcm-primary-button disabled:opacity-40">
            {loading ? "Atualizando banco de dados..." : "Atualizar banco de dados · OTs do BMA"}
          </button>
          {canContinue && (
            <button
              type="button"
              onClick={handleContinue}
              className="rounded-lg bg-emerald-400 px-5 py-3 text-sm font-semibold text-navy-950 transition hover:bg-emerald-300 focus:outline-none focus:ring-2 focus:ring-emerald-400 focus:ring-offset-2 focus:ring-offset-navy-950"
            >
              Continuar planejamento →
            </button>
          )}
          <p className="w-full text-xs text-slate-400">Consulta novamente as OTs dos setores selecionados, incluindo mão de obra planejada (especialidade, quantidade e horas). O acesso ao BMA ocorre em segundo plano; se exigir MFA ou uma etapa manual, a coleta será interrompida. Não atualiza o cadastro de funcionários.</p>
          {error && <p className="mt-4 text-sm text-rose-300" role="alert">{error}</p>}
        </div>

        {syncRun && (
          <section className="mt-8 rounded-lg border border-white/10 bg-navy-900/70 p-4 sm:p-5" aria-labelledby="sync-log-title">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="sync-log-title" className="text-base font-semibold text-white">Acompanhamento da coleta</h2>
              <span className={`rounded-md px-2.5 py-1 text-xs font-medium ${syncRun.status === "failed" ? "bg-rose-400/10 text-rose-300" : syncRun.status === "completed" ? "bg-emerald-400/10 text-emerald-300" : "bg-accent-400/10 text-accent-400"}`}>
                {syncStatusLabels[syncRun.status]}
              </span>
            </div>
            <p className="mt-2 text-sm text-slate-300" aria-live="polite">{syncRun.mensagem}</p>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-xs uppercase text-slate-500">Etapa</dt>
                <dd className="mt-1 text-slate-200">{syncRun.etapa}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-slate-500">Página OSLC</dt>
                <dd className="mt-1 text-slate-200">{syncRun.pagina_atual}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-slate-500">OTs lidas / salvas</dt>
                <dd className="mt-1 text-slate-200">{syncRun.ots_lidas} / {syncRun.ots_salvas}</dd>
              </div>
            </dl>
            {syncRun.erro && (
              <p className="mt-4 rounded-md border border-rose-400/20 bg-rose-400/5 p-3 text-sm text-rose-300" role="alert">
                {syncRun.erro}
              </p>
            )}
            <ol className="mt-4 max-h-64 space-y-2 overflow-y-auto border-t border-white/10 pt-3" aria-label="Log de eventos da sincronização" aria-live="polite">
              {syncRun.eventos.map((event, index) => (
                <li key={`${event.data_hora}-${index}`} className="grid gap-1 text-xs sm:grid-cols-[150px_130px_1fr]">
                  <time className="text-slate-500">{new Date(event.data_hora).toLocaleTimeString("pt-BR")}</time>
                  <span className={event.nivel === "error" ? "text-rose-300" : "text-accent-400"}>{event.etapa}</span>
                  <span className="text-slate-300">{event.mensagem}</span>
                </li>
              ))}
            </ol>
          </section>
        )}
        {loading && (
          <div role="dialog" aria-modal="true" aria-labelledby="sync-progress-title"
            className="fixed inset-0 z-[120] flex items-center justify-center bg-black/75 p-4">
            <section className="w-full max-w-md rounded-lg border border-white/10 bg-navy-900 p-6 shadow-2xl">
              <div className="flex items-center gap-3">
                <LoaderCircle size={24} className="animate-spin text-accent-400" aria-hidden="true" />
                <div>
                  <h2 id="sync-progress-title" className="text-lg font-semibold text-white">Carregando OTs do BMA</h2>
                  <p className="mt-1 text-xs text-slate-400">Progresso estimado</p>
                </div>
                <span className="ml-auto text-2xl font-semibold tabular-nums text-white">
                  {Math.round(synchronizationProgress(syncRun))}%
                </span>
              </div>
              <div role="progressbar" aria-label="Progresso estimado da carga de OTs"
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(synchronizationProgress(syncRun))}
                className="mt-5 h-2 overflow-hidden rounded-full bg-white/10">
                <div className="h-full rounded-full bg-accent-400 transition-[width] duration-500"
                  style={{ width: `${synchronizationProgress(syncRun)}%` }} />
              </div>
              <p role="status" aria-live="polite" className="mt-4 text-sm text-slate-300">
                {syncRun?.mensagem || "Preparando a sincronização com o BMA..."}
              </p>
              {syncRun && <p className="mt-2 text-xs text-slate-500">
                Página {syncRun.pagina_atual} · {syncRun.ots_lidas} OT(s) lidas
              </p>}
            </section>
          </div>
        )}
      </main>
    </>
  );
}