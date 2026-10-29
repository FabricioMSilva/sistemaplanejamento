import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState, type FocusEvent, type KeyboardEvent } from "react";
import { AlertCircle, ArrowRight, CheckCircle2, LoaderCircle, X } from "lucide-react";
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
  if (run.status === "failed") return 100;
  if (run.status === "saving") return 96;
  if (run.status === "queued") return 3;

  const stage = run.etapa.toLowerCase();
  if (stage.includes("autentic") || stage.includes("navegador") || stage.includes("wotrack")) return 12;
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
  const [syncModalOpen, setSyncModalOpen] = useState(false);
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
        setSyncModalOpen(isSyncActive(latest.status));

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
    setSyncModalOpen(true);
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
              className="pcm-primary-button"
            >
              Planejar com Banco de Dados existente <ArrowRight size={16} aria-hidden="true" />
            </button>
          )}
          <p className="w-full text-xs text-slate-400">Consulta novamente as OTs dos setores selecionados, incluindo mão de obra planejada (especialidade, quantidade e horas). O acesso ao BMA ocorre em segundo plano; se exigir MFA ou uma etapa manual, a coleta será interrompida. Não atualiza o cadastro de funcionários.</p>
          {error && <p className="mt-4 text-sm text-rose-300" role="alert">{error}</p>}
        </div>

        {syncModalOpen && (
          <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="sync-progress-title"
              aria-describedby="sync-progress-message"
              className="w-full max-w-xl overflow-hidden rounded-xl border border-white/10 bg-navy-950 shadow-2xl shadow-black/40"
            >
              <div className="h-1 bg-accent-400/20">
                <div
                  className={`h-full transition-[width] duration-700 ${syncRun?.status === "failed" || error ? "bg-rose-400" : syncRun?.status === "completed" ? "bg-emerald-400" : "bg-accent-400"}`}
                  style={{ width: `${synchronizationProgress(syncRun)}%` }}
                />
              </div>
              <div className="p-6 sm:p-8">
                <div className="flex items-start gap-4">
                  <div className={`grid size-12 shrink-0 place-items-center rounded-full ${syncRun?.status === "failed" || error ? "bg-rose-400/10 text-rose-300" : syncRun?.status === "completed" ? "bg-emerald-400/10 text-emerald-300" : "bg-accent-400/10 text-accent-300"}`}>
                    {loading
                      ? <LoaderCircle size={25} className="animate-spin" aria-hidden="true" />
                      : syncRun?.status === "completed"
                        ? <CheckCircle2 size={25} aria-hidden="true" />
                        : <AlertCircle size={25} aria-hidden="true" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
                      Atualização do banco · Ordens de trabalho
                    </p>
                    <h2 id="sync-progress-title" className="mt-1 text-xl font-semibold text-white">
                      {loading ? "Coletando ordens de trabalho" : syncRun?.status === "completed" ? "Coleta concluída" : "Coleta não concluída"}
                    </h2>
                    <span className={`mt-2 inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${syncRun?.status === "failed" || error ? "bg-rose-400/10 text-rose-300" : syncRun?.status === "completed" ? "bg-emerald-400/10 text-emerald-300" : "bg-accent-400/10 text-accent-300"}`}>
                      {syncRun ? syncStatusLabels[syncRun.status] : loading ? "Iniciando" : "Falhou"}
                    </span>
                  </div>
                  {!loading && (
                    <button
                      type="button"
                      onClick={() => setSyncModalOpen(false)}
                      aria-label="Fechar acompanhamento da coleta"
                      title="Fechar"
                      className="rounded-md p-2 text-slate-400 transition hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-accent-400"
                    >
                      <X size={18} aria-hidden="true" />
                    </button>
                  )}
                </div>

                <p id="sync-progress-message" role="status" aria-live="polite" className="mt-6 text-sm leading-6 text-slate-300">
                  {error || syncRun?.erro || syncRun?.mensagem || "Preparando a coleta no BMA..."}
                </p>

                <div
                  role="progressbar"
                  aria-label="Progresso estimado da coleta"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(synchronizationProgress(syncRun))}
                  className="mt-5 h-1.5 overflow-hidden rounded-full bg-white/10"
                >
                  <div
                    className={`h-full rounded-full transition-[width] duration-700 ${syncRun?.status === "failed" || error ? "bg-rose-400" : syncRun?.status === "completed" ? "bg-emerald-400" : "bg-accent-400"}`}
                    style={{ width: `${synchronizationProgress(syncRun)}%` }}
                  />
                </div>

                <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-white/10 pt-5 sm:grid-cols-3">
                  <div>
                    <dt className="text-xs text-slate-500">Setores selecionados</dt>
                    <dd className="mt-1 truncate text-sm font-medium text-slate-200" title={(syncRun?.setores ?? sectors).join(", ")}>
                      {(syncRun?.setores ?? sectors).join(", ") || "-"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500">OTs lidas</dt>
                    <dd className="mt-1 text-sm font-semibold tabular-nums text-white">{syncRun?.ots_lidas ?? 0}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500">OTs gravadas</dt>
                    <dd className="mt-1 text-sm font-semibold tabular-nums text-white">{syncRun?.ots_salvas ?? 0}</dd>
                  </div>
                </dl>

                {syncRun && syncRun.pagina_atual > 0 && loading && (
                  <p className="mt-4 text-xs text-slate-500">Página consultada: {syncRun.pagina_atual}</p>
                )}

                {!loading && (
                  <div className="mt-7 flex flex-wrap justify-end gap-3 border-t border-white/10 pt-5">
                    <button
                      type="button"
                      onClick={() => setSyncModalOpen(false)}
                      className="pcm-small-button"
                    >
                      <X size={15} aria-hidden="true" /> Fechar
                    </button>
                    {canContinue && (
                      <button
                        type="button"
                        onClick={handleContinue}
                        className="pcm-primary-button w-full sm:w-auto"
                      >
                        Planejar com Banco de Dados existente <ArrowRight size={16} aria-hidden="true" />
                      </button>
                    )}
                  </div>
                )}
              </div>
            </section>
          </div>
        )}
      </main>
    </>
  );
}