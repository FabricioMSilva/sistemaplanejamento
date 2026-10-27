import type { OrdemTrabalho } from "@/services/api";
import type { Requirement, WorkPlan } from "@/services/pcm";

function fieldText(value: unknown): string {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const field = value as Record<string, unknown>;
    return String(field.value ?? field._value ?? "");
  }
  return value == null ? "" : String(value);
}

export function plannedLabor(order: OrdemTrabalho) {
  const raw = order.dados.wplabor;
  if (!Array.isArray(raw)) return [];
  return raw.filter((row): row is Record<string, unknown> => row !== null && typeof row === "object" && !Array.isArray(row))
    .map((row) => ({ craft: fieldText(row.craft).trim(), orgid: fieldText(row.orgid).trim(),
      quantity: fieldText(row.quantity), hours: fieldText(row.laborhrs), skill: fieldText(row.skilllevel) }))
    .filter((row) => row.craft);
}

export function plannedBmaOrders(plan: WorkPlan) {
  const orders = new Map(plan.ordens.map((order) => [`${order.siteid}:${order.wonum}`, order]));
  const people = new Map(plan.pessoas.map((person) => [person.id, person]));
  const grouped = new Map<string, { order: OrdemTrabalho; allocations: {
    dia: string; horas: number; executantes: string[];
  }[]; assignments: Map<string, { dia: string; laborcode: string; horas: number }>;
    specialties: Set<string>; }>();
  for (const block of plan.blocos) {
    const order = orders.get(block.ot);
    if (!order) continue;
    const row = grouped.get(block.ot) ?? { order, allocations: [], assignments: new Map(), specialties: new Set() };
    row.allocations.push({
      dia: block.dia,
      horas: block.horas,
      executantes: block.executantes.map((id) => {
        const person = people.get(id);
        return person ? `${person.nome} - ${person.matricula}` : id;
      }),
    });
    for (const personId of block.executantes) {
      const person = people.get(personId);
      if (!person?.matricula) continue;
      if (person.funcao?.trim()) row.specialties.add(person.funcao.trim());
      const assignmentKey = `${block.dia}:${person.matricula}`;
      const assignment = row.assignments.get(assignmentKey);
      if (assignment) assignment.horas += block.horas;
      else row.assignments.set(assignmentKey, {
        dia: block.dia, laborcode: person.matricula, horas: block.horas,
      });
    }
    grouped.set(block.ot, row);
  }
  return [...grouped.entries()].map(([key, row]) => {
    const dates = row.allocations.map((allocation) => allocation.dia).sort();
    const requirement = plan.requisitos[key];
    const specialty = requirement?.funcao || plannedLabor(row.order)[0]?.craft
      || (row.specialties.size === 1 ? [...row.specialties][0] : "");
    return { key, order: row.order, allocations: row.allocations,
      planning: {
        planned_start: dates.length ? `${dates[0]}T00:01:00` : "",
        planned_finish: dates.length ? `${dates[dates.length - 1]}T23:59:00` : "",
        specialty,
        assignments: [...row.assignments.values()].sort((a, b) =>
          a.dia.localeCompare(b.dia) || a.laborcode.localeCompare(b.laborcode)),
      },
    description: fieldText(row.order.dados.description).trim(),
    };
  }).sort((a, b) => a.order.wonum.localeCompare(b.order.wonum, "pt-BR", { numeric: true }));
}

export function missingPlanningData(order: OrdemTrabalho): string[] {
  const positive = (value: unknown) => {
    const parsed = Number(fieldText(value).trim().replace(",", "."));
    return Number.isFinite(parsed) && parsed > 0;
  };
  const missing: string[] = [];
  if (!positive(order.dados.estdur) && !positive(order.dados.estlabhrs)) missing.push("duração estimada");
  const labor = plannedLabor(order);
  if (!labor.length) missing.push("especialidade");
  if (!labor.some((row) => positive(row.quantity))) missing.push("quantidade de mão de obra");
  return missing;
}

export function orderSpecialties(order: OrdemTrabalho, requirement: Requirement) {
  const rows = plannedLabor(order);
  if (rows.length) return rows.map((row) => ({ code: row.craft, orgid: row.orgid }));
  return requirement.funcao && !requirement.todas_especialidades
    ? [{ code: requirement.funcao, orgid: requirement.orgid }] : [];
}

export function matchesOrderSpecialty(order: OrdemTrabalho, requirement: Requirement, filter: string): boolean {
  if (!filter) return true;
  const specialties = orderSpecialties(order, requirement);
  if (filter === "indefinida") return !specialties.length && !requirement.todas_especialidades;
  if (filter === "qualquer") return !plannedLabor(order).length && requirement.todas_especialidades === true;
  return specialties.some((row) => row.code === filter);
}
