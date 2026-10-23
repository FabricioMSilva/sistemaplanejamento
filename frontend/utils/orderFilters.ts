import type { OrdemTrabalho } from "@/services/api";

export type ColumnKind = "text" | "select";

export type ColumnDef = {
  key: string;
  label: string;
  kind: ColumnKind;
  // Em colunas de lista (ex.: Nº OT) os termos digitados funcionam como OU.
  anyTerm?: boolean;
  placeholder?: string;
};

export const orderColumns: ColumnDef[] = [
  { key: "wonum", label: "Ordem de Trabalho", kind: "text", anyTerm: true, placeholder: "RES123 RES456" },
  { key: "description", label: "Descrição", kind: "text", placeholder: "palavras…" },
  { key: "location", label: "Local", kind: "text", placeholder: "local…" },
  { key: "assetnum", label: "Equipamento", kind: "text", placeholder: "equip…" },
  { key: "status", label: "Status da OT", kind: "select" },
  { key: "worktype", label: "Tipo de trabalho", kind: "select" },
  { key: "maintenanceshop", label: "Setor de manutenção", kind: "select" },
];

export type OrderFilters = {
  text: Record<string, string>;
  select: Record<string, string[]>;
};

export const emptyFilters: OrderFilters = { text: {}, select: {} };

export function countActiveFilters(filters: OrderFilters): number {
  return (
    Object.values(filters.text).filter((value) => value.trim()).length +
    Object.values(filters.select).filter((value) => value.length).length
  );
}

export function cellText(order: OrdemTrabalho, key: string): string {
  const value = order.dados[key] ?? order[key as keyof OrdemTrabalho];
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    const nested = value as Record<string, unknown>;
    return String(nested.value ?? nested._value ?? nested.description ?? "");
  }
  return String(value);
}

export function getWorkType(order: OrdemTrabalho): string {
  return cellText(order, "worktype").trim().toUpperCase();
}

function selectValue(order: OrdemTrabalho, key: string): string {
  return cellText(order, key).trim().toUpperCase() || "—";
}

export function normalize(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function parseTerms(query: string): string[] {
  const terms: string[] = [];
  for (const match of query.matchAll(/"([^"]+)"|(\S+)/g)) {
    const term = normalize(match[1] ?? match[2] ?? "").trim();
    if (term) terms.push(term);
  }
  return terms;
}

// Sintaxe: palavras (todas devem existir), "frase exata", !excluir, =igual, a|b (ou).
function termMatches(haystack: string, rawTerm: string): boolean {
  let term = rawTerm;
  let negate = false;
  let exact = false;
  if ((term[0] === "!" || term[0] === "-") && term.length > 1) {
    negate = true;
    term = term.slice(1);
  }
  if (term[0] === "=" && term.length > 1) {
    exact = true;
    term = term.slice(1);
  }
  const alternatives = term.split("|").filter(Boolean);
  const hit = alternatives.some((alt) => (exact ? haystack === alt : haystack.includes(alt)));
  return negate ? !hit : hit;
}

export function matchesText(value: string, query: string, anyTerm = false): boolean {
  const terms = parseTerms(query);
  if (terms.length === 0) return true;
  const haystack = normalize(value);
  return anyTerm
    ? terms.some((term) => termMatches(haystack, term))
    : terms.every((term) => termMatches(haystack, term));
}

function passesColumn(order: OrdemTrabalho, column: ColumnDef, filters: OrderFilters): boolean {
  if (column.kind === "text") {
    const query = filters.text[column.key] ?? "";
    return !query.trim() || matchesText(cellText(order, column.key), query, column.anyTerm);
  }
  const selected = filters.select[column.key] ?? [];
  return selected.length === 0 || selected.includes(selectValue(order, column.key));
}

// skipKey ignora o filtro da própria coluna, para calcular contagens dinâmicas (busca facetada).
export function applyFilters(
  orders: OrdemTrabalho[],
  filters: OrderFilters,
  skipKey?: string,
): OrdemTrabalho[] {
  const active = orderColumns.filter((column) => column.key !== skipKey);
  return orders.filter((order) => active.every((column) => passesColumn(order, column, filters)));
}

export type SelectOption = { value: string; label: string; count: number };

export function buildSelectOptions(
  baseOrders: OrdemTrabalho[],
  filters: OrderFilters,
  column: ColumnDef,
): SelectOption[] {
  const labels = new Map<string, string>();
  for (const order of baseOrders) {
    const value = selectValue(order, column.key);
    if (labels.has(value)) continue;
    const description = column.key === "status" ? cellText(order, "status_description") : "";
    labels.set(value, description ? `${value} – ${description}` : value);
  }

  const counts = new Map<string, number>();
  for (const order of applyFilters(baseOrders, filters, column.key)) {
    const value = selectValue(order, column.key);
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }

  return Array.from(labels, ([value, label]) => ({ value, label, count: counts.get(value) ?? 0 })).sort(
    (a, b) => b.count - a.count || a.value.localeCompare(b.value),
  );
}

export function sortOrders(
  orders: OrdemTrabalho[],
  key: string | null,
  direction: "asc" | "desc",
): OrdemTrabalho[] {
  if (!key) return orders;
  const factor = direction === "asc" ? 1 : -1;
  return [...orders].sort(
    (a, b) =>
      factor *
      cellText(a, key).localeCompare(cellText(b, key), "pt-BR", { numeric: true, sensitivity: "base" }),
  );
}
