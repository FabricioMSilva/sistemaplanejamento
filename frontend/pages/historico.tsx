import Head from "next/head";
import { useEffect, useState } from "react";
import { AlertCircle, Check, Clock3, History, LoaderCircle, Pencil, Plus, RefreshCw, Search } from "lucide-react";
import { getOtHistory, type OtHistoryItem, type OtHistoryType } from "@/services/api";

const FILTERS: { value: OtHistoryType; label: string }[] = [
  { value: "todas", label: "Todas" },
  { value: "criadas", label: "Criadas" },
  { value: "planejadas", label: "Planejadas" },
  { value: "alteradas", label: "Alteradas" },
];

function actionLabel(item: OtHistoryItem) {
  if (item.acao === "criacao_solicitada") return "Criação solicitada";
  if (item.acao === "criada") return "Criada";
  if (item.acao === "planejada") return "Planejada";
  if (item.acao === "alterada") return "Alterada";
  if (item.acao === "pendente") return "Pendente";
  if (item.acao === "erro") return "Erro";
  return "Consulta";
}

function actionIcon(item: OtHistoryItem) {
  if (item.acao === "criada" || item.acao === "criacao_solicitada") return Plus;
  if (item.acao === "planejada") return Check;
  if (item.acao === "alterada") return Pencil;
  if (item.acao === "pendente" || item.acao === "erro") return AlertCircle;
  return Clock3;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("pt-BR");
}

export default function HistoryPage() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<OtHistoryType>("todas");
  const [items, setItems] = useState<OtHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      getOtHistory(search, filter)
        .then((rows) => { if (!cancelled) setItems(rows); })
        .catch((reason: unknown) => {
          if (!cancelled) setError(reason instanceof Error ? reason.message : "Falha ao carregar o histórico.");
        })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [search, filter, reload]);

  return (
    <>
      <Head>
        <title>Histórico de OTs | Planning & Scheduling Michelin</title>
      </Head>
      <main className="mx-auto min-h-[calc(100vh-4rem)] w-full max-w-[1600px] space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Ordens de trabalho</p>
            <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold text-foreground">
              <History size={23} aria-hidden="true" /> Histórico de OTs
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">Ações registradas pelo programa no fluxo de criação e planejamento.</p>
          </div>
          <button type="button" className="pcm-small-button" disabled={loading} onClick={() => setReload((value) => value + 1)}
            aria-label="Atualizar histórico" title="Atualizar histórico">
            {loading ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            Atualizar
          </button>
        </header>

        <p className="border-l-2 border-accent bg-muted/60 px-4 py-3 text-sm text-muted-foreground">
          Solicitações de criação ficam identificadas como “Criação solicitada” até o BMA retornar o número da OT.
        </p>

        <section aria-label="Filtros do histórico" className="flex flex-col gap-4 border-b border-border pb-5 md:flex-row md:items-center md:justify-between">
          <label className="relative block w-full md:max-w-md">
            <Search size={17} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              aria-label="Pesquisar histórico de OTs"
              placeholder="Pesquisar por OT, descrição, executante ou arquivo"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="h-11 w-full rounded-lg border border-input bg-surface pl-10 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/30"
            />
          </label>
          <div role="group" aria-label="Filtrar por tipo de ação" className="inline-flex w-full overflow-x-auto rounded-lg border border-border bg-muted p-1 md:w-auto">
            {FILTERS.map(({ value, label }) => (
              <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}
                className={`min-h-9 flex-1 whitespace-nowrap rounded-md px-3 text-sm font-medium transition md:flex-none ${
                  filter === value ? "bg-surface text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                }`}>
                {label}
              </button>
            ))}
          </div>
        </section>

        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{loading ? "Carregando…" : `${items.length} registro${items.length === 1 ? "" : "s"}`}</span>
        </div>

        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full min-w-[860px] border-collapse text-left text-sm">
            <thead className="bg-muted text-xs font-semibold uppercase text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-3">Data e hora</th>
                <th scope="col" className="px-4 py-3">OT</th>
                <th scope="col" className="px-4 py-3">Ação</th>
                <th scope="col" className="px-4 py-3">Status</th>
                <th scope="col" className="px-4 py-3">Detalhes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {!loading && items.map((item) => {
                const Icon = actionIcon(item);
                const arquivo = typeof item.detalhes.arquivo === "string" ? item.detalhes.arquivo : "";
                return (
                  <tr key={item.id} className="align-top hover:bg-muted/40">
                    <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{formatDate(item.registrado_em)}</td>
                    <td className="px-4 py-3 font-semibold text-foreground">
                      {item.wonum
                        ? item.wonum.toUpperCase().startsWith(item.siteid.toUpperCase())
                          ? item.wonum
                          : `${item.siteid}:${item.wonum}`
                        : <span className="font-normal text-muted-foreground">Sem número BMA</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-2 whitespace-nowrap font-medium text-foreground">
                        <Icon size={15} aria-hidden="true" className={item.acao === "erro" ? "text-danger" : item.acao === "alterada" ? "text-warning" : "text-primary"} />
                        {actionLabel(item)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{item.status || item.situacao || "—"}</td>
                    <td className="max-w-[520px] px-4 py-3 text-muted-foreground">
                      <p title={item.resumo || item.origem} className="line-clamp-3 break-words text-foreground">{item.resumo || item.origem}</p>
                      <p className="mt-1 text-xs">{item.origem}{arquivo ? ` · ${arquivo}` : ""}</p>
                    </td>
                  </tr>
                );
              })}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                    {error ? "Não foi possível carregar os registros." : "Nenhum registro corresponde à pesquisa e ao filtro."}
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                    <span role="status" className="inline-flex items-center gap-2"><LoaderCircle size={17} className="animate-spin" /> Carregando histórico…</span>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}