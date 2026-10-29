import type { CalendarioTurnos, MaoDeObra, OrdemTrabalho, PlanejamentoEquipe } from "@/services/api";
import { chaveExecutante, horasExecutante, periodoValido } from "@/utils/laborPlanning";
import { cellText, getWorkType, hasExistingPlanningInfo, isCorrectiveAvailable, planningStatus } from "@/utils/orderFilters";

export const numberFormat = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
export const formatNumber = (value: number | null) => value === null ? "—" : numberFormat.format(value);
const dateFormatter = new Intl.DateTimeFormat("sv-SE", { timeZone: "America/Sao_Paulo" });
export function localDate(value: string): string | null {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value) && periodoValido(value, value)) return value;
  const date = new Date(value);
  return value && Number.isFinite(date.getTime()) ? dateFormatter.format(date) : null;
}
export function orderInPeriod(order: OrdemTrabalho, start: string, end: string): boolean {
  if (!periodoValido(start, end)) return false;
  const targetStart = localDate(cellText(order, "targstartdate"));
  const targetEnd = localDate(cellText(order, "targcompdate"));
  const scheduledStart = localDate(cellText(order, "schedstart"));
  const scheduledEnd = localDate(cellText(order, "schedfinish"));
  const overlaps = (from: string | null, to: string | null) =>
    !!from && !!to && from <= to && from <= end && to >= start;
  const inside = (date: string | null) => !!date && date >= start && date <= end;
  return overlaps(targetStart, targetEnd) || overlaps(scheduledStart, scheduledEnd)
    || [targetStart, targetEnd, scheduledStart, scheduledEnd].some(inside);
}
export function numericField(order: OrdemTrabalho, key: string): number | null {
  const raw = cellText(order, key).trim();
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : null;
}
export function isPreventiveOrder(order: OrdemTrabalho): boolean {
  return ["I", "S"].includes(getWorkType(order)) && /^PM/i.test(cellText(order, "description").trim());
}
export function daysBetween(start: string, end: string): string[] {
  if (!periodoValido(start, end)) return [];
  const days = [];
  for (let time = Date.parse(`${start}T00:00:00Z`); time <= Date.parse(`${end}T00:00:00Z`); time += 86400000) {
    days.push(new Date(time).toISOString().slice(0, 10));
  }
  return days;
}

export function portfolio(orders: OrdemTrabalho[], types: readonly string[]) {
  const rows = orders.filter((order) => types.includes(getWorkType(order)));
  const estimates = rows.map((order) => numericField(order, "estlabhrs"));
  return {
    rows, count: rows.length,
    hours: estimates.reduce<number>((total, value) => total + (value ?? 0), 0),
    missingHours: estimates.filter((value) => value === null).length,
    assets: new Set(rows.map((order) => cellText(order, "assetnum")).filter(Boolean)).size,
    missingAssets: rows.filter((order) => !cellText(order, "assetnum")).length,
  };
}

export function buildDashboard(
  orders: OrdemTrabalho[], plan: PlanejamentoEquipe | null,
  labor: MaoDeObra | null, calendar: CalendarioTurnos | null,
  period: { inicio: string; fim: string } | null = null,
  requirePeriod = false,
) {
  const sectorPending = orders.filter((order) => !["CAN", "CLOSE", "COMP", "HISTEDIT"].includes(order.status.toUpperCase()));
  const periodFilterActive = !!period && periodoValido(period.inicio, period.fim);
  const pending = periodFilterActive ? sectorPending.filter((order) => getWorkType(order) === "E" || orderInPeriod(order, period.inicio, period.fim))
    : requirePeriod ? [] : sectorPending;
  const people = new Map((labor?.profissionais ?? []).map((person) => [chaveExecutante(person), person]));
  const days = plan ? daysBetween(plan.inicio, plan.fim) : [];
  const team = (plan?.executantes ?? []).map((member) => {
    const person = people.get(chaveExecutante(member));
    const craft = person?.especialidades.find((item) => item.codigo === member.funcao);
    const hours = plan && person && craft ? horasExecutante(plan.inicio, plan.fim, member, calendar) : null;
    return { member, person, craft, hours };
  });
  const verified = !labor?.verificacao_nf?.necessaria || labor.verificacao_nf.verificada;
  const validTeam = verified && team.length > 0 && team.every((row) => row.hours !== null);
  const availableHours = validTeam ? team.reduce((total, row) => total + (row.hours?.horas ?? 0), 0) : null;
  const estimates = pending.map((order) => numericField(order, "estlabhrs"));
  const missingHours = estimates.filter((value) => value === null).length;
  const neededHours = estimates.reduce<number>((total, hours) => total + (hours ?? 0), 0);
  const daily = days.map((day) => {
    let capacity = 0;
    let complete = team.length > 0;
    for (const row of team) {
      const result = row.person && row.craft
        ? horasExecutante(day, day, { ...row.member, ajuste_horas: 0 }, calendar) : null;
      if (!result) complete = false;
      capacity += result?.horas ?? 0;
    }
    const scheduled = pending.filter((order) => localDate(cellText(order, "schedstart")) === day);
    return {
      date: day, label: day.slice(8) + "/" + day.slice(5, 7),
      capacity: complete ? capacity : null,
      demand: scheduled.reduce((total, order) => total + (numericField(order, "estlabhrs") ?? 0), 0),
      orders: scheduled.length,
    };
  });
  const disciplines = new Map<string, { name: string; hours: number; people: number }>();
  for (const row of team) {
    if (!row.hours || !row.craft) continue;
    const key = JSON.stringify([row.member.orgid, row.member.funcao]);
    const group = disciplines.get(key) ?? { name: row.craft.descricao || row.member.funcao, hours: 0, people: 0 };
    group.hours += row.hours.horas;
    group.people++;
    disciplines.set(key, group);
  }
  const types = new Map<string, { name: string; count: number; hours: number }>();
  for (const order of pending) {
    const name = getWorkType(order) || "Sem tipo";
    const group = types.get(name) ?? { name, count: 0, hours: 0 };
    group.count++;
    group.hours += numericField(order, "estlabhrs") ?? 0;
    types.set(name, group);
  }
  const dated = pending.flatMap((order) => {
    const start = localDate(cellText(order, "schedstart"));
    const end = localDate(cellText(order, "schedfinish"));
    return start && end && end >= start ? [{ order, start, end }] : [];
  }).sort((a, b) => a.start.localeCompare(b.start));
  const gantt = plan ? dated.filter((row) => row.start <= plan.fim && row.end >= plan.inicio) : [];
  const locations = new Map<string, number>();
  for (const order of pending) {
    const location = cellText(order, "location");
    if (location) locations.set(location, (locations.get(location) ?? 0) + 1);
  }
  const grouping = [...locations].sort((a, b) => b[1] - a[1])[0];
  const averageCapacity = availableHours !== null && days.length ? availableHours / days.length : null;
  const pmCandidates = pending.filter(isPreventiveOrder);
  const availablePm = pmCandidates.filter((order) => !hasExistingPlanningInfo(order));
  const pmAlreadyPlannedExcluded = pmCandidates.filter((order) => ["Planejada", "Parcial"].includes(planningStatus(order))).length;
  return {
    pending, sectorPending, periodFilterActive, team, validTeam, availableHours, neededHours, missingHours, daily,
    disciplines: [...disciplines.values()].sort((a, b) => b.hours - a.hours),
    types: [...types.values()].sort((a, b) => b.count - a.count), gantt, dated: dated.length, grouping,
    backlogDays: averageCapacity && missingHours === 0 ? neededHours / averageCapacity : null,
    availability: labor && labor.total > 0 && validTeam ? team.length / labor.total * 100 : null,
    adjustments: team.reduce((sum, row) => sum + row.member.ajuste_horas, 0),
    pm: portfolio(availablePm, ["I", "S"]),
    pmAllRows: pmCandidates,
    pmExcluded: pending.filter((order) => ["I", "S"].includes(getWorkType(order)) && !isPreventiveOrder(order)).length,
    pmAlreadyPlannedExcluded,
    pmUnverifiedExcluded: pmCandidates.filter((order) => planningStatus(order) === "Não verificada").length,
    corrective: portfolio(sectorPending.filter(isCorrectiveAvailable), ["E"]),
  };
}
export type PcmData = ReturnType<typeof buildDashboard>;
