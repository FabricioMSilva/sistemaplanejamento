import { useEffect, useMemo, useRef, useState } from "react";
import { listarMaoDeObra, obterCalendarioTurnos, salvarEquipe, type CalendarioTurnos, type MaoDeObra, type PlanejamentoEquipe } from "@/services/api";
import {
  chaveExecutante, configuracaoInicial, configurarDiasDisponiveis, horasExecutante, resolvePlannerIdentity, escalaPeriodo,
  type ConfiguracaoExecutante, type Profissional,
} from "@/utils/laborPlanning";
import { normalize } from "@/utils/orderFilters";
import LaborAvailability from "@/components/LaborAvailability";
import LaborPlanningTools from "@/components/LaborPlanningTools";
import { reutilizarEquipe } from "@/utils/laborPlanning";

type Props = {
  inicio: string;
  fim: string;
  setores: string[];
  saved: PlanejamentoEquipe | null;
  onClose: () => void;
  onSave: (plan: PlanejamentoEquipe) => void;
  onLaborUpdate: (data: MaoDeObra) => void;
  persistTeam?: (plan: PlanejamentoEquipe) => Promise<void>;
};
const inputClass = "rounded border border-white/20 bg-navy-950 px-2 py-1.5 text-sm text-white";
const buttonClass = "rounded border border-white/20 px-3 py-2 text-sm text-accent-400 disabled:cursor-not-allowed disabled:opacity-40";

export default function LaborPlanningModal({ inicio, fim, setores, saved, onClose, onSave, onLaborUpdate, persistTeam }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [data, setData] = useState<MaoDeObra | null>(null);
  const [calendar, setCalendar] = useState<CalendarioTurnos | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [toolsBusy, setToolsBusy] = useState(false);
  const [planejador, setPlanejador] = useState(saved?.planejador ?? "");
  const [attempt, setAttempt] = useState(0);
  const [search, setSearch] = useState("");
  const [checkedTotal, setCheckedTotal] = useState<string[]>([]);
  const [checkedAvailable, setCheckedAvailable] = useState<string[]>([]);
  const [available, setAvailable] = useState<ConfiguracaoExecutante[]>(saved
    ? reutilizarEquipe(saved, inicio, fim).map((member) => configurarDiasDisponiveis(member, inicio, fim)) : []);
  const [configs, setConfigs] = useState<Record<string, ConfiguracaoExecutante>>({});

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (!saved?.planejador) setPlanejador(localStorage.getItem("pcm-planejador") ?? "");
    return () => { element?.close(); document.body.style.overflow = oldOverflow; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.allSettled([listarMaoDeObra(setores), obterCalendarioTurnos()])
      .then(([result, calendarResult]) => {
        if (cancelled) return;
        if (result.status === "rejected") throw result.reason;
        setData(result.value);
        if (calendarResult.status === "fulfilled") setCalendar(calendarResult.value);
        else setError("Calendário de referência indisponível. A capacidade continua sendo calculada pelos dias marcados × 8 h.");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Falha ao carregar o efetivo.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [attempt, setores]);

  const people = useMemo(() => new Map(
    (data?.profissionais ?? []).map((person) => [chaveExecutante(person), person]),
  ), [data]);
  const selectedKeys = new Set(available.map(chaveExecutante));
  const total = (data?.profissionais ?? []).filter((person) => !selectedKeys.has(chaveExecutante(person)));
  const visibleTotal = total.filter((person) => normalize([
    person.nome, person.matricula, person.setor,
    person.local_trabalho,
    ...person.especialidades.map((craft) => `${craft.codigo} ${craft.descricao ?? ""}`),
  ].join(" ")).includes(normalize(search)));

  function label(person: Profissional): string {
    return `${person.nome || "Nome não informado"} (${person.matricula}) — ${
      person.especialidades.map((craft) => craft.descricao || craft.codigo).join(", ") || "Função não informada"
    }`;
  }
  function transferToAvailable(keys: string[]) {
    const additions = keys.filter((key) => !selectedKeys.has(key)).flatMap((key) => {
      const person = people.get(key);
      return person ? [configs[key] ?? configurarDiasDisponiveis(configuracaoInicial(person), inicio, fim)] : [];
    });
    setAvailable((current) => [...current, ...additions]);
    setCheckedTotal([]);
    setError("");
  }
  function transferToTotal(keys: string[]) {
    setConfigs((current) => ({
      ...current,
      ...Object.fromEntries(available.filter((person) => keys.includes(chaveExecutante(person)))
        .map((person) => [chaveExecutante(person), person])),
    }));
    setAvailable((current) => current.filter((person) => !keys.includes(chaveExecutante(person))));
    setCheckedAvailable([]);
    setError("");
  }
  function update(key: string, change: Partial<ConfiguracaoExecutante>) {
    setAvailable((current) => current.map((person) =>
      chaveExecutante(person) === key ? { ...person, ...change } : person));
    setError("");
  }

  const calculated = available.map((member) => {
    const person = people.get(chaveExecutante(member));
    const validCraft = person?.especialidades.some((craft) => craft.codigo === member.funcao);
    return { member, person, hours: validCraft ? horasExecutante(inicio, fim, member, calendar) : null };
  });
  const pending = calculated.filter((row) => !row.hours);
  const summary = new Map<string, { label: string; count: number; hours: number }>();
  for (const row of calculated) {
    if (!row.hours || !row.person) continue;
    const key = JSON.stringify([row.member.orgid, row.member.funcao]);
    const craft = row.person.especialidades.find((item) => item.codigo === row.member.funcao);
    const current = summary.get(key) ?? {
      label: `${row.member.funcao} — ${craft?.descricao ?? "Descrição não cadastrada"} (${row.member.orgid})`,
      count: 0, hours: 0,
    };
    current.count++;
    current.hours = Math.round((current.hours + row.hours.horas) * 100) / 100;
    summary.set(key, current);
  }
  const totalHours = [...summary.values()].reduce((sum, row) => sum + row.hours, 0);

  function currentPlan(planner = resolvePlannerIdentity(planejador, data?.profissionais ?? [])): PlanejamentoEquipe {
    return {
      setores, inicio, fim, planejador: planner,
      executantes: available.map((person) => {
        if (!person.jornada) throw new Error("Jornada não configurada.");
        return {
          ...person, jornada: person.jornada,
          ajustes_datas: Object.fromEntries(Object.entries(person.ajustes_datas ?? {})
            .filter(([day]) => day >= inicio && day <= fim)),
          ausencias: (person.ausencias ?? []).filter((day) => day >= inicio && day <= fim),
          dias_disponiveis: (person.dias_disponiveis ?? []).filter((day) => day >= inicio && day <= fim),
        };
      }),
    };
  }

  async function refreshLabor() {
    const result = await listarMaoDeObra(setores);
    setData(result);
    onLaborUpdate(result);
  }

  async function save() {
    if (pending.length || !planejador.trim() || toolsBusy) return;
    setSaving(true);
    setError("");
    try {
      const canonicalPlanner = resolvePlannerIdentity(planejador, data?.profissionais ?? []);
      const plan = currentPlan(canonicalPlanner);
      if (persistTeam) await persistTeam(plan);
      else await salvarEquipe(plan);
      setPlanejador(canonicalPlanner);
      localStorage.setItem("pcm-planejador", canonicalPlanner);
      onSave(plan);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao salvar a equipe.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); if (!saving && !toolsBusy) onClose(); }}
      aria-labelledby="labor-modal-title"
      className="max-h-[94vh] w-[96vw] max-w-7xl overflow-y-auto rounded-xl border border-white/20 bg-navy-900 p-5 text-slate-200 backdrop:bg-black/70">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 id="labor-modal-title" className="text-xl font-semibold text-white">{persistTeam ? "Editar mão de obra deste planejamento" : "Definir mão de obra disponível"}</h2>
          <p className="mt-1 text-sm">Período: {inicio.split("-").reverse().join("/")} a {fim.split("-").reverse().join("/")} (inclusive).</p>
        </div>
        <button type="button" onClick={onClose} disabled={saving || toolsBusy} className={buttonClass}>Cancelar</button>
      </div>
      <LaborPlanningTools setores={setores} planejador={planejador} setPlanejador={setPlanejador}
        profissionais={data?.profissionais ?? []}
        plan={currentPlan} valid={!loading && !pending.length && available.length > 0}
        disabled={saving || loading} onApply={(plan) => {
          setAvailable(reutilizarEquipe(plan, inicio, fim).map((member) => configurarDiasDisponiveis(member, inicio, fim)));
          setCheckedAvailable([]); setCheckedTotal([]); setError("");
        }} onChanged={refreshLabor} onBusy={setToolsBusy} />
      {error && <p role="alert" className="mb-4 text-rose-300">{error}</p>}
      {loading ? <p>Carregando efetivo...</p> : !data ? (
        <button type="button" onClick={() => setAttempt((value) => value + 1)} className={buttonClass}>Tentar novamente</button>
      ) : !data.sincronizado_em ? (
        <p className="text-amber-300">Use “Atualizar mão de obra” neste modal para carregar o efetivo do BMA.</p>
      ) : (
        <>
          <p className="mb-4 text-xs text-slate-400">
            {setores.some((sector) => sector.toUpperCase() === "RES-TC-NF")
              ? "NF: cadastro RES do BMA cruzado com os ativos da ListaFuncionario do SharePoint, sem filtro de setor/local no BMA."
              : `Inclui setor(es) ${setores.join(", ")} ou local de trabalho NFE.`} Atualizado em {new Intl.DateTimeFormat("pt-BR", {
              dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo",
            }).format(new Date(data.sincronizado_em))} (Brasília). A disponibilidade é definida manualmente.
          </p>
          {data.verificacao_nf?.necessaria && <p className="mb-4 text-sm text-amber-200">
            {data.verificacao_nf.verificada
              ? `Ativos conferidos no SharePoint. ${data.verificacao_nf.pendentes} pessoa(s) sem vínculo, não incluídas no efetivo; confira acima.`
              : "NF ainda não conferido no SharePoint. Atualize a mão de obra e confirme os vínculos para selecionar somente ativos."}
          </p>}
          <fieldset disabled={saving || toolsBusy}>
            <div className="grid gap-4 md:grid-cols-[1fr_auto_1fr]">
              <div>
                <label htmlFor="labor-total" className="font-semibold">Efetivo total ({total.length})</label>
                <input aria-label="Buscar no efetivo total" placeholder="Nome, matrícula, setor ou função"
                  value={search} onChange={(event) => { setSearch(event.target.value); setCheckedTotal([]); }}
                  className={`${inputClass} my-2 w-full`} />
                <select id="labor-total" multiple size={12} value={checkedTotal}
                  onChange={(event) => setCheckedTotal(Array.from(event.target.selectedOptions, (option) => option.value))}
                  className={`${inputClass} h-72 w-full`}>
                  {visibleTotal.map((person) => <option key={chaveExecutante(person)} value={chaveExecutante(person)}>{label(person)}</option>)}
                </select>
              </div>
              <div className="flex justify-center gap-2 md:flex-col">
                <button type="button" aria-label="Adicionar selecionados" disabled={!checkedTotal.length}
                  onClick={() => transferToAvailable(checkedTotal)} className={buttonClass}>&gt;</button>
                <button type="button" aria-label="Adicionar todos os resultados da busca" disabled={!visibleTotal.length}
                  onClick={() => transferToAvailable(visibleTotal.map(chaveExecutante))} className={buttonClass}>&gt;&gt;</button>
                <button type="button" aria-label="Remover selecionados" disabled={!checkedAvailable.length}
                  onClick={() => transferToTotal(checkedAvailable)} className={buttonClass}>&lt;</button>
                <button type="button" aria-label="Remover todos" disabled={!available.length}
                  onClick={() => transferToTotal(available.map(chaveExecutante))} className={buttonClass}>&lt;&lt;</button>
              </div>
              <div>
                <label htmlFor="labor-available" className="font-semibold">Disponível ({available.length})</label>
                <p className="my-2 text-xs text-slate-400">Selecione e use &lt; para retirar. Ctrl/Shift permite seleção múltipla.</p>
                <select id="labor-available" multiple size={12} value={checkedAvailable}
                  onChange={(event) => setCheckedAvailable(Array.from(event.target.selectedOptions, (option) => option.value))}
                  className={`${inputClass} h-72 w-full`}>
                  {available.map((member) => {
                    const person = people.get(chaveExecutante(member));
                    return <option key={chaveExecutante(member)} value={chaveExecutante(member)}>
                      {person ? label(person) : `${member.matricula} — não confirmado no efetivo; confira vínculo/cadastro ou remova`}
                    </option>;
                  })}
                </select>
              </div>
            </div>
            <h3 className="mb-2 mt-6 font-semibold">Dias disponíveis e capacidade de cada executante</h3>
            <p className="mb-3 text-xs text-slate-400">
              Marque os dias em que cada integrante poderá trabalhar. Cada dia marcado equivale a 8 horas disponíveis para atividades.
              Segunda a sexta vêm marcados inicialmente; sábados, domingos e feriados podem ser incluídos ou retirados.
              Equipe e turno são apenas referência e não alteram as horas. Não é necessário digitar horas ou ajustes.
              Ao revisar um planejamento antigo, a nova regra só será persistida após salvar.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead><tr>{["Executante", "Função", "Equipe / Jornada (referência)", "Dias disponíveis · 8 h/dia", "Escala de referência", "H×H automático"].map((title) =>
                  <th key={title} scope="col" className="px-2 py-2">{title}</th>)}</tr></thead>
                <tbody>
                  {calculated.map(({ member, person, hours }) => {
                    const key = chaveExecutante(member);
                    return (
                      <tr key={key} className="border-t border-white/10">
                        <td className="px-2 py-3">{person?.nome || member.matricula}<span className="block text-xs text-slate-400">{member.matricula}</span></td>
                        <td className="px-2 py-3">
                          <select aria-label={`Função de ${member.matricula}`} value={member.funcao}
                            onChange={(event) => update(key, { funcao: event.target.value })} className={`${inputClass} max-w-64`}>
                            <option value="">Selecione a função</option>
                            {person?.especialidades.filter((craft, index, all) => all.findIndex((item) => item.codigo === craft.codigo) === index)
                              .map((craft) => <option key={craft.codigo} value={craft.codigo}>{craft.codigo} — {craft.descricao || "Sem descrição"}</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-3">
                          <select aria-label={`Jornada de ${member.matricula}`}
                            value={member.jornada === "equipe" ? `equipe-${member.equipe}` : member.jornada}
                            onChange={(event) => {
                              const value = event.target.value;
                              if (/^equipe-[1-4]$/.test(value)) {
                                update(key, { jornada: "equipe", equipe: Number(value.slice(-1)), ajustes_datas: {} });
                                return;
                              }
                              if (value === "" || value === "adm" || value === "08-16" || value === "16-00" || value === "00-08") {
                                update(key, { jornada: value, equipe: null, ajustes_datas: {} });
                              }
                            }} className={inputClass}>
                            <option value="">Selecione</option>
                            <option value="adm">Administrativo</option>
                            {[1, 2, 3, 4].map((team) => <option key={team} value={`equipe-${team}`}>Equipe {team}</option>)}
                            {["08-16", "16-00", "00-08"].includes(member.jornada) && (
                              <option value={member.jornada}>Turno fixo anterior ({member.jornada}) — revise</option>
                            )}
                          </select>
                        </td>
                        <td className="px-2 py-3 align-top">
                          <LaborAvailability inicio={inicio} fim={fim} matricula={member.matricula} disponiveis={member.dias_disponiveis ?? []}
                            onChange={(dias_disponiveis) => update(key, { dias_disponiveis })}
                            canCopy={checkedAvailable.some((selected) => selected !== key)}
                            onCopy={() => setAvailable((current) => current.map((person) =>
                              checkedAvailable.includes(chaveExecutante(person)) ? { ...person, dias_disponiveis: [...(member.dias_disponiveis ?? [])] } : person))} />
                        </td>
                        <td className="px-2 py-3">
                          {member.jornada === "equipe" ? (() => {
                            const schedule = escalaPeriodo(inicio, fim, member.equipe, calendar);
                            if (!schedule) return <span className="text-slate-400">Calendário de referência disponível somente para 2026. HH calculado pelos dias marcados.</span>;
                            return <details>
                              <summary className="cursor-pointer text-accent-400">Ver turnos (informativo)</summary>
                              <div className="mt-2 max-h-64 min-w-64 space-y-2 overflow-y-auto">
                                {schedule.map((row) => (
                                  <div key={row.data} className="border-b border-white/10 pb-2 text-xs">
                                    <p>{row.data.split("-").reverse().join("/")} — {calendar?.legenda[row.turno]}</p>
                                    {row.marcacao && <p className="text-amber-300">{row.marcacao} · referência</p>}
                                    <p className="text-sky-200">{member.dias_disponiveis?.includes(row.data) ? "Disponível · 8 h" : "Não disponível · 0 h"}</p>
                                  </div>
                                ))}
                              </div>
                            </details>;
                          })() : <span className="text-slate-400">{member.jornada === "adm" ? "Administrativo · referência" : `Turno ${member.jornada} · referência`}</span>}
                        </td>
                        <td className="px-2 py-3">{hours ? `${hours.horas.toLocaleString("pt-BR")} h (${hours.dias} dias)` : <span className="text-amber-300">Pendente</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </fieldset>
          {pending.length > 0 && <p role="status" className="my-3 text-sm text-amber-300">
            {pending.length} executante(s) pendente(s): confirme cadastro ativo, função e dias disponíveis. Eles não estão incluídos no somatório.
          </p>}
          <section className="my-5 rounded border border-white/10 p-4" aria-label="Somatório de horas por função">
            <h3 className="mb-2 font-semibold">H×H disponível por função {pending.length ? "(parcial)" : ""}</h3>
            {[...summary].map(([key, row]) => <p key={key} className="text-sm">
              {row.label}: {row.count} executante(s) — <strong>{row.hours.toLocaleString("pt-BR")} H×H</strong>
            </p>)}
            <p className="mt-2 font-semibold" aria-live="polite">Total: {totalHours.toLocaleString("pt-BR")} H×H</p>
          </section>
          {!planejador.trim() && <p className="mb-3 text-sm text-amber-200">Informe o planejador para salvar e identificar este planejamento.</p>}
          <button type="button" disabled={saving || toolsBusy || pending.length > 0 || !planejador.trim() || (data.verificacao_nf?.necessaria && !data.verificacao_nf.verificada)}
            onClick={save} className="rounded bg-accent-400 px-4 py-2 font-semibold text-navy-950 disabled:opacity-40">
            {saving ? "Salvando..." : persistTeam ? "Atualizar equipe deste planejamento" : "Salvar período e equipe"}
          </button>
        </>
      )}
    </dialog>
  );
}
