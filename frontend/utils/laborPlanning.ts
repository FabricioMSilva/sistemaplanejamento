import type { CalendarioTurnos, ExecutantePlanejado, MaoDeObra, PlanejamentoEquipe } from "@/services/api";

export type Profissional = MaoDeObra["profissionais"][number];
export type ConfiguracaoExecutante = Omit<ExecutantePlanejado, "jornada"> & {
  jornada: ExecutantePlanejado["jornada"] | "";
};
export const chaveExecutante = (person: { orgid: string; matricula: string }) =>
  JSON.stringify([person.orgid, person.matricula]);

type PlannerPerson = Pick<Profissional, "matricula" | "nome">;
const normalizePlannerSearch = (value: string) => value.trim().normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");

export function formatPlannerIdentity(person: PlannerPerson): string {
  const matricula = person.matricula.trim(), nome = person.nome.trim();
  if (!matricula || !nome) throw new Error("O funcionário precisa ter matrícula e nome cadastrados.");
  return `${matricula} - ${nome}`.toLocaleUpperCase("pt-BR");
}

export function searchPlannerPeople(query: string, people: PlannerPerson[]): PlannerPerson[] {
  const normalized = normalizePlannerSearch(query);
  if (!normalized) return [];
  return people.filter((person) => person.matricula.trim() && person.nome.trim()
    && (normalizePlannerSearch(person.matricula).includes(normalized)
      || normalizePlannerSearch(person.nome).includes(normalized)))
    .slice(0, 8);
}

export function resolvePlannerIdentity(value: string, people: PlannerPerson[]): string {
  const query = normalizePlannerSearch(value);
  const matches = new Map<string, PlannerPerson>();
  for (const person of people) {
    let identity: string;
    try { identity = formatPlannerIdentity(person); } catch { continue; }
    if ([person.matricula, person.nome, identity].some((candidate) => normalizePlannerSearch(candidate) === query))
      matches.set(identity, person);
  }
  if (matches.size !== 1) {
    throw new Error(matches.size ? "Nome ambíguo. Selecione o funcionário correto na lista."
      : "Planejador não encontrado. Selecione um funcionário da lista carregada.");
  }
  return [...matches.keys()][0];
}

const DAY = 86400000;
function dayNumber(value: string): number {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return NaN;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(timestamp) || new Date(timestamp).toISOString().slice(0, 10) !== value) return NaN;
  return timestamp / DAY;
}
export function periodoValido(inicio: string, fim: string): boolean {
  return Number.isFinite(dayNumber(inicio)) && Number.isFinite(dayNumber(fim)) && fim >= inicio;
}
export function formatPlanningDate(value: string): string {
  return periodoValido(value, value) ? value.split("-").reverse().join("/") : "";
}
export function parsePlanningDate(value: string): string {
  if (!/^\d{2}\/\d{2}\/\d{4}$/.test(value)) return "";
  const iso = value.split("/").reverse().join("-");
  return periodoValido(iso, iso) ? iso : "";
}

export function equipeDefinida(
  plan: PlanejamentoEquipe | null, inicio: string, fim: string, setores: string[],
): boolean {
  if (!plan || !periodoValido(inicio, fim) || !plan.executantes.length
    || plan.inicio !== inicio || plan.fim !== fim || !setores.length) return false;
  const normalizeSectors = (values: string[]) => [...new Set(values.map((value) => value.toUpperCase()))].sort();
  const current = normalizeSectors(setores);
  const saved = normalizeSectors(plan.setores);
  return current.length === saved.length && current.every((value, index) => value === saved[index]);
}

export function horasExecutante(
  inicio: string, fim: string, person: ConfiguracaoExecutante,
  calendar?: CalendarioTurnos | null,
): { dias: number; base: number; horas: number } | null {
  if (!periodoValido(inicio, fim) || !person.jornada || !person.funcao) return null;
  const start = dayNumber(inicio);
  const length = dayNumber(fim) - start + 1;
  if (person.capacidade === "dias_6h" || person.capacidade === "dias_8h") {
    const available = person.dias_disponiveis;
    if (!available || available.some((day) => !Number.isFinite(dayNumber(day)))
      || new Set(available).size !== available.length || person.ajuste_horas !== 0
      || Object.keys(person.ajustes_datas ?? {}).length || person.ausencias?.length) return null;
    const days = available.filter((day) => day >= inicio && day <= fim).length;
    const hours = days * (person.capacidade === "dias_8h" ? 8 : 6);
    return { dias: days, base: hours, horas: hours };
  }
  const absences = new Set(person.ausencias ?? []);
  if ([...absences].some((day) => !Number.isFinite(dayNumber(day)))) return null;
  if (person.jornada === "equipe") {
    const schedule = escalaPeriodo(inicio, fim, person.equipe, calendar);
    if (!schedule) return null;
    let days = 0, base = 0;
    for (const row of schedule) {
      const hours = absences.has(row.data) ? 0 : row.marcacao ? person.ajustes_datas?.[row.data] : row.turno === "F" ? 0 : 8;
      if (hours === undefined || !Number.isFinite(hours) || hours < 0 || hours > 24) return null;
      base += hours;
      if (hours > 0) days++;
    }
    const hours = Math.round((base + person.ajuste_horas) * 100) / 100;
    if (!Number.isFinite(hours) || hours < 0) return null;
    return { dias: days, base, horas: hours };
  }
  const admin = person.jornada === "adm";
  const cycle = person.inicio_ciclo ? dayNumber(person.inicio_ciclo) : NaN;
  if (!admin && !Number.isFinite(cycle)) return null;
  const period = admin ? 7 : 8;
  const full = Math.floor(length / period);
  const mod = (value: number, divisor: number) => ((value % divisor) + divisor) % divisor;
  const phase = admin ? mod(start + 3, 7) : mod(start - cycle, 8);
  let days = full * (admin ? 5 : 6);
  for (let i = 0; i < length % period; i++) {
    if (mod(phase + i, period) < (admin ? 5 : 6)) days++;
  }
  for (const day of absences) {
    if (day >= inicio && day <= fim) {
      const offset = dayNumber(day) - start;
      if (mod(phase + offset, period) < (admin ? 5 : 6)) days--;
    }
  }

  const base = days * (admin ? 6 : 8);
  const hours = Math.round((base + person.ajuste_horas) * 100) / 100;
  if (!Number.isFinite(hours) || hours < 0) return null;
  return { dias: days, base, horas: hours };
}

export function escalaPeriodo(
  inicio: string, fim: string, equipe: number | null | undefined,
  calendar: CalendarioTurnos | null | undefined,
): { data: string; turno: string; marcacao: string | null }[] | null {
  if (!calendar || !equipe || !periodoValido(inicio, fim)
    || !calendar.dias[inicio] || !calendar.dias[fim]) return null;
  const rows = [];
  for (let day = dayNumber(inicio); day <= dayNumber(fim); day++) {
    const data = new Date(day * DAY).toISOString().slice(0, 10);
    const row = calendar.dias[data]?.[String(equipe)];
    if (!row) return null;
    rows.push({ data, ...row });
  }
  return rows;
}

export function configuracaoInicial(person: Profissional): ConfiguracaoExecutante {
  const primary = person.especialidades.find((craft) => craft.principal);
  return {
    orgid: person.orgid, matricula: person.matricula,
    funcao: primary?.codigo ?? (person.especialidades.length === 1 ? person.especialidades[0].codigo : ""),
    jornada: "", inicio_ciclo: null, ajuste_horas: 0,
  };
}

export function diasUteis(inicio: string, fim: string): string[] {
  if (!periodoValido(inicio, fim)) return [];
  const days: string[] = [];
  for (let day = dayNumber(inicio); day <= dayNumber(fim); day++) {
    const date = new Date(day * DAY);
    if (![0, 6].includes(date.getUTCDay())) days.push(date.toISOString().slice(0, 10));
  }
  return days;
}

export function configurarDiasDisponiveis(member: ConfiguracaoExecutante, inicio: string, fim: string): ConfiguracaoExecutante {
  return {
    ...member, jornada: member.jornada || "adm", capacidade: "dias_8h",
    dias_disponiveis: (member.capacidade === "dias_6h" || member.capacidade === "dias_8h") && member.dias_disponiveis != null
      ? member.dias_disponiveis.filter((day) => day >= inicio && day <= fim)
      : diasUteis(inicio, fim).filter((day) => !(member.ausencias ?? []).includes(day)),
    ajuste_horas: 0, ajustes_datas: {}, ausencias: [],
  };
}

export function reutilizarEquipe(plan: PlanejamentoEquipe, inicio: string, fim: string): ConfiguracaoExecutante[] {
  const samePeriod = plan.inicio === inicio && plan.fim === fim;
  return plan.executantes.map((member) => ({
    ...member,
    ausencias: samePeriod ? member.ausencias ?? [] : [],
    ajustes_datas: samePeriod ? member.ajustes_datas ?? {} : {},
    ajuste_horas: samePeriod ? member.ajuste_horas : 0,
    ...((member.capacidade === "dias_6h" || member.capacidade === "dias_8h") ? { dias_disponiveis: samePeriod && member.dias_disponiveis != null
      ? member.dias_disponiveis : diasUteis(inicio, fim) } : {}),
  }));
}
