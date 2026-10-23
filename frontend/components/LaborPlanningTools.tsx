import { useEffect, useState } from "react";
import {
  atualizarMaoDeObra, listarHistoricoEquipe, obterConferenciaNf, obterEquipePadrao,
  obterSincronizacao, salvarEquipePadrao, salvarVinculoNf,
  type ConferenciaNf, type HistoricoEquipe, type PlanejamentoEquipe,
} from "@/services/api";
import { chaveExecutante } from "@/utils/laborPlanning";
import { normalize } from "@/utils/orderFilters";

type Props = {
  setores: string[]; planejador: string; setPlanejador: (value: string) => void;
  plan: () => PlanejamentoEquipe; valid: boolean; disabled: boolean;
  onApply: (plan: PlanejamentoEquipe) => void;
  onChanged: () => Promise<void>; onBusy: (busy: boolean) => void;
};
const explain = (error: unknown) => error instanceof Error ? error.message : "Falha de comunicação.";

export default function LaborPlanningTools(props: Props) {
  const { setores } = props;
  const [history, setHistory] = useState<HistoricoEquipe[]>([]);
  const [nf, setNf] = useState<ConferenciaNf | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [historyId, setHistoryId] = useState("");
  const [linkChoices, setLinkChoices] = useState<Record<number, string>>({});
  const isNf = setores.some((sector) => sector.toUpperCase() === "RES-TC-NF");
  const disabled = busy || props.disabled;
  useEffect(() => {
    let cancelled = false;
    Promise.all([listarHistoricoEquipe(setores), isNf ? obterConferenciaNf(setores) : Promise.resolve(null)])
      .then(([rows, result]) => { if (!cancelled) { setHistory(rows); setNf(result); } })
      .catch((reason: unknown) => { if (!cancelled) setError(explain(reason)); });
    return () => { cancelled = true; };
  }, [setores, isNf]);

  function working(value: boolean) { setBusy(value); props.onBusy(value); }
  async function action(run: () => Promise<void>) {
    setError(""); setMessage(""); working(true);
    try { await run(); } catch (reason) { setError(explain(reason)); } finally { working(false); }
  }
  useEffect(() => {
    if (!job) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const status = await obterSincronizacao(job);
        if (cancelled) return;
        setMessage(status.mensagem);
        if (status.status === "failed") throw new Error(status.mensagem);
        if (status.status === "completed") {
          if (isNf) {
            const result = await obterConferenciaNf(setores);
            if (cancelled) return;
            setNf(result);
          }
          await props.onChanged();
          if (!cancelled) { setJob(""); working(false); }
        } else timer = setTimeout(poll, 2000);
      } catch (reason) {
        if (!cancelled) { setError(explain(reason)); setJob(""); working(false); }
      }
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
    // Polling belongs to one job; changing draft inputs must not restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);

  return <section className="mb-5 space-y-3 rounded-xl border border-white/10 bg-black/10 p-4" aria-label="Gestão da mão de obra">
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    {message && <p role="status" className="text-sm text-sky-200">{message}</p>}
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-56 flex-1 text-xs text-slate-300">Planejador · nome ou matrícula
        <input aria-label="Planejador" maxLength={120} value={props.planejador} disabled={disabled}
          onChange={(event) => props.setPlanejador(event.target.value)}
          className="mt-1 block w-full rounded border border-white/20 bg-navy-950 p-2 text-sm" />
      </label>
      <button type="button" disabled={disabled} className="pcm-small-button" onClick={() => {
        setError(""); setMessage(""); working(true);
        atualizarMaoDeObra(setores).then((result) => setJob(result.job_id))
          .catch((reason: unknown) => { setError(explain(reason)); working(false); });
      }}>{job ? "Atualizando BMA / SharePoint…" : "Atualizar mão de obra"}</button>
      <button type="button" disabled={disabled || !props.planejador.trim()} className="pcm-small-button" onClick={() => void action(async () => {
        const result = await obterEquipePadrao(setores, props.planejador.trim());
        if (!result) throw new Error("Nenhuma equipe padrão salva para este planejador e setor.");
        props.onApply(result); setMessage("Padrão aplicado com segunda a sexta disponíveis. Revise os dias e salve o planejamento.");
      })}>Usar minha equipe padrão</button>
      <button type="button" disabled={disabled || !props.valid || !props.planejador.trim()} className="pcm-small-button" onClick={() => void action(async () => {
        await salvarEquipePadrao(props.plan());
        localStorage.setItem("pcm-planejador", props.planejador.trim());
        setMessage("Equipe padrão salva por planejador e setor. Ao reutilizar, segunda a sexta virão marcados com 8 h/dia.");
      })}>Salvar como meu padrão</button>
    </div>
    <p className="text-xs text-slate-400">Identificação declarada, sem autenticação individual. A atualização consulta o BMA e, para NF, a lista de ativos do SharePoint. OTs não são sincronizadas aqui.</p>
    <div className="flex flex-wrap items-end gap-2">
      <label className="min-w-56 flex-1 text-xs text-slate-300">Últimos 10 planejamentos · compartilhados por setor
        <select aria-label="Histórico de planejamentos" disabled={disabled} value={historyId} onChange={(event) => setHistoryId(event.target.value)}
          className="mt-1 block w-full rounded border border-white/20 bg-navy-950 p-2 text-sm">
          <option value="">Selecione um planejamento</option>
          {history.map((row) => <option key={row.id} value={row.id}>
            {row.planejamento.inicio.split("-").reverse().join("/")} a {row.planejamento.fim.split("-").reverse().join("/")} · {row.planejamento.planejador || "Legado"} · {row.planejamento.executantes.length} executantes · {new Date(row.salvo_em).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })}
          </option>)}
        </select>
      </label>
      <button type="button" disabled={disabled || !historyId} className="pcm-small-button" onClick={() => {
        const row = history.find((item) => item.id === Number(historyId));
        if (row) { props.onApply(row.planejamento); setMessage("Equipe histórica aplicada como rascunho. Dias disponíveis são mantidos no mesmo período; para outro período, segunda a sexta vêm marcados. Revise antes de salvar."); }
      }}>Reutilizar equipe</button>
    </div>
    {isNf && <details className="rounded border border-sky-400/20 p-3">
      <summary className="cursor-pointer text-sm text-sky-200">Conferência de ativos NF · {nf?.verificada ? `${nf.vinculados.length} vinculados / ${nf.pendentes.length} pendentes` : "Atualização necessária"}</summary>
      <p className="my-2 text-xs text-slate-400">Somente pessoas presentes na lista SharePoint e vinculadas ao BMA entram no efetivo. Nomes abreviados não são associados automaticamente. Confirme a identidade antes de vincular; a função e a matrícula continuam vindo do BMA.</p>
      {nf?.verificada && <div className="max-h-72 space-y-2 overflow-y-auto">
        {[...nf.pendentes, ...nf.vinculados].map((row) => {
          const linked = nf.vinculados.find((item) => item.id === row.id);
          const currentKey = linked ? chaveExecutante({ orgid: linked.orgid, matricula: linked.matricula_bma }) : "";
          const choice = linkChoices[row.id] ?? currentKey;
          const tokens = normalize(row.nome).split(" ").filter((token) => !["de", "da", "do", "dos", "das", "e"].includes(token));
          const suggestions = nf.candidatos.filter((person) => {
            const full = new Set(normalize(person.nome).split(" "));
            return tokens.length >= 2 && tokens.every((token) => full.has(token));
          });
          const suggestedKeys = new Set(suggestions.map(chaveExecutante));
          return <label key={row.id} className="grid gap-2 border-t border-white/10 py-2 text-xs sm:grid-cols-2">
            <span>{row.nome} <span className={linked ? "text-emerald-300" : "text-amber-300"}>{linked ? `· ${linked.matricula_bma}` : "· sem vínculo, não incluído"}</span></span>
            <span className="flex min-w-0 flex-wrap gap-2">
              <select aria-label={`Vínculo BMA de ${row.nome}`} disabled={disabled}
                value={choice} onChange={(event) => setLinkChoices((current) => ({ ...current, [row.id]: event.target.value }))}
                className="min-w-0 flex-1 rounded border border-white/20 bg-navy-950 p-2">
                <option value="">Selecione a pessoa correspondente no BMA</option>
                {suggestions.length > 0 && <optgroup label="Possíveis correspondências por nome — confirme a identidade">
                  {suggestions.map((person) => <option key={chaveExecutante(person)} value={chaveExecutante(person)}>
                    {person.nome} ({person.matricula}) · {person.setor} / {person.local_trabalho}
                  </option>)}
                </optgroup>}
                <optgroup label="Demais candidatos BMA da unidade RES">
                  {nf.candidatos.filter((person) => !suggestedKeys.has(chaveExecutante(person))).map((person) => <option key={chaveExecutante(person)} value={chaveExecutante(person)}>
                    {person.nome} ({person.matricula}) · {person.setor} / {person.local_trabalho}
                  </option>)}
                </optgroup>
              </select>
              <button type="button" className="pcm-small-button" disabled={disabled || !choice || choice === currentKey} onClick={() => {
                const person = nf.candidatos.find((candidate) => chaveExecutante(candidate) === choice);
                if (person) void action(async () => {
                  setNf(await salvarVinculoNf(setores, row.id, person.orgid, person.matricula));
                  await props.onChanged(); setMessage(`Vínculo confirmado para ${row.nome}.`);
                });
              }}>Confirmar vínculo</button>
            </span>
          </label>;
        })}
      </div>}
    </details>}
  </section>;
}
