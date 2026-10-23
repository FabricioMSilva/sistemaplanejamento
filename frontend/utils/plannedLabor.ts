import type { OrdemTrabalho } from "@/services/api";
import type { Requirement } from "@/services/pcm";

export function plannedLabor(order: OrdemTrabalho) {
  const raw = order.dados.wplabor;
  if (!Array.isArray(raw)) return [];
  const text = (value: unknown): string => {
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      const field = value as Record<string, unknown>;
      return String(field.value ?? field._value ?? "");
    }
    return value == null ? "" : String(value);
  };
  return raw.filter((row): row is Record<string, unknown> => row !== null && typeof row === "object" && !Array.isArray(row))
    .map((row) => ({ craft: text(row.craft).trim(), orgid: text(row.orgid).trim(),
      quantity: text(row.quantity), hours: text(row.laborhrs), skill: text(row.skilllevel) }))
    .filter((row) => row.craft);
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
