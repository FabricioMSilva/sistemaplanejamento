import { Fragment, useDeferredValue, useMemo, useState, type FocusEvent } from "react";
import OrderDetails from "@/components/OrderDetails";
import type { OrdemTrabalho } from "@/services/api";
import {
  applyFilters,
  buildSelectOptions,
  cellText,
  countActiveFilters,
  emptyFilters,
  normalize,
  orderColumns,
  sortOrders,
  type ColumnDef,
  type OrderFilters,
} from "@/utils/orderFilters";

const PAGE_SIZE = 200;

type Props = {
  orders: OrdemTrabalho[];
  filters: OrderFilters;
  onFiltersChange: (filters: OrderFilters) => void;
  loading?: boolean;
};

type SelectFilterProps = {
  column: ColumnDef;
  orders: OrdemTrabalho[];
  filters: OrderFilters;
  onChange: (values: string[]) => void;
};

function SelectFilter({ column, orders, filters, onChange }: SelectFilterProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const selected = filters.select[column.key] ?? [];
  const options = useMemo(() => buildSelectOptions(orders, filters, column), [orders, filters, column]);
  const visible = options.filter((option) => normalize(option.label).includes(normalize(search)));

  function toggle(value: string, checked: boolean) {
    onChange(checked ? [...selected, value] : selected.filter((item) => item !== value));
  }

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
  }

  const summary =
    selected.length === 0 ? "Todos" : selected.length === 1 ? selected[0] : `${selected.length} selec.`;

  return (
    <div className="relative" onBlur={handleBlur}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Filtrar ${column.label}`}
        onClick={() => setOpen((current) => !current)}
        className={`flex w-full min-w-[7rem] items-center justify-between gap-2 rounded border px-2 py-1.5 text-left text-xs normal-case ${
          selected.length
            ? "border-accent-400 bg-accent-400/10 text-accent-400"
            : "border-white/10 bg-navy-950 text-slate-300 hover:border-white/30"
        }`}
      >
        <span className="truncate">{summary}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 z-30 mt-1 w-72 rounded-md border border-white/10 bg-navy-900 p-2 normal-case shadow-xl">
          <input
            autoFocus
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar…"
            className="mb-2 w-full rounded border border-white/10 bg-navy-950 px-2 py-1.5 text-xs text-white outline-none placeholder:text-slate-500 focus:border-accent-400"
          />
          <div className="mb-2 flex items-center justify-between text-xs">
            <button
              type="button"
              onClick={() => onChange(Array.from(new Set([...selected, ...visible.map(({ value }) => value)])))}
              className="font-medium text-accent-400 hover:text-accent-500"
            >
              Marcar visíveis
            </button>
            <button
              type="button"
              onClick={() => onChange([])}
              disabled={selected.length === 0}
              className="text-slate-400 hover:text-white disabled:opacity-40"
            >
              Limpar
            </button>
          </div>
          <ul role="listbox" aria-multiselectable="true" className="max-h-64 overflow-y-auto">
            {visible.map((option) => (
              <li key={option.value}>
                <label
                  className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-white/5 ${
                    option.count === 0 ? "text-slate-500" : "text-slate-200"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(option.value)}
                    onChange={(event) => toggle(option.value, event.target.checked)}
                    className="h-3.5 w-3.5 accent-amber-400"
                  />
                  <span className="flex-1 truncate" title={option.label}>{option.label}</span>
                  <span className="tabular-nums text-slate-400">{option.count}</span>
                </label>
              </li>
            ))}
            {visible.length === 0 && <li className="px-2 py-2 text-xs text-slate-400">Nada encontrado.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function OrdersTable({ orders, filters, onFiltersChange, loading }: Props) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [expandedOrder, setExpandedOrder] = useState<string | null>(null);
  const deferredFilters = useDeferredValue(filters);

  const filtered = useMemo(() => applyFilters(orders, deferredFilters), [orders, deferredFilters]);
  const sorted = useMemo(() => sortOrders(filtered, sortKey, sortDirection), [filtered, sortKey, sortDirection]);
  const activeCount = countActiveFilters(filters);

  function setText(key: string, value: string) {
    setLimit(PAGE_SIZE);
    onFiltersChange({ ...filters, text: { ...filters.text, [key]: value } });
  }

  function setSelect(key: string, values: string[]) {
    setLimit(PAGE_SIZE);
    onFiltersChange({ ...filters, select: { ...filters.select, [key]: values } });
  }

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("asc");
    }
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-white">Ordens de trabalho</h2>
        <div className="flex items-center gap-4">
          <p className="text-sm text-slate-400" aria-live="polite">
            {filtered.length} de {orders.length} OTs
          </p>
          {activeCount > 0 && (
            <button
              type="button"
              onClick={() => onFiltersChange(emptyFilters)}
              className="text-sm font-medium text-accent-400 transition hover:text-accent-500"
            >
              Limpar {activeCount} filtro{activeCount > 1 ? "s" : ""}
            </button>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-white/10">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-navy-900 text-xs text-slate-300">
              <tr>
                <th scope="col" className="px-3 pt-3">Detalhes</th>
                {orderColumns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={sortKey === column.key ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}
                    className="whitespace-nowrap px-3 pt-3 font-semibold"
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className="inline-flex items-center gap-1 hover:text-white"
                      title="Ordenar"
                    >
                      {column.label}
                      <span aria-hidden="true" className="text-slate-500">
                        {sortKey === column.key ? (sortDirection === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    </button>
                  </th>
                ))}
              </tr>
              <tr className="border-b border-white/10">
                <th aria-label="Sem filtro de detalhes" />
                {orderColumns.map((column) => (
                  <th key={column.key} className="px-3 pb-3 pt-2 font-normal">
                    {column.kind === "text" ? (
                      <div className="relative">
                        <input
                          type="text"
                          value={filters.text[column.key] ?? ""}
                          onChange={(event) => setText(column.key, event.target.value)}
                          placeholder={column.placeholder}
                          aria-label={`Filtrar ${column.label}`}
                          title={'Várias palavras = todas; "frase"; !excluir; =exato; a|b = ou'}
                          className={`w-full min-w-[8rem] rounded border bg-navy-950 px-2 py-1.5 pr-6 text-xs text-white outline-none placeholder:text-slate-600 focus:border-accent-400 ${
                            (filters.text[column.key] ?? "").trim() ? "border-accent-400" : "border-white/10"
                          }`}
                        />
                        {(filters.text[column.key] ?? "") && (
                          <button
                            type="button"
                            onClick={() => setText(column.key, "")}
                            aria-label={`Limpar filtro ${column.label}`}
                            className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ) : (
                      <SelectFilter
                        column={column}
                        orders={orders}
                        filters={filters}
                        onChange={(values) => setSelect(column.key, values)}
                      />
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10 bg-navy-950/60">
              {sorted.slice(0, limit).map((order) => (
                <Fragment key={`${order.siteid}-${order.wonum}`}>
                <tr className="text-slate-300">
                  <td className="px-3 py-2.5">
                    <button
                      type="button"
                      aria-label={`Detalhes da OT ${order.wonum}`}
                      aria-expanded={expandedOrder === `${order.siteid}-${order.wonum}`}
                      onClick={() => setExpandedOrder(
                        expandedOrder === `${order.siteid}-${order.wonum}` ? null : `${order.siteid}-${order.wonum}`,
                      )}
                      className="font-medium text-accent-400 hover:text-accent-500"
                    >
                      {expandedOrder === `${order.siteid}-${order.wonum}` ? "Fechar" : "Ver"}
                    </button>
                  </td>
                  {orderColumns.map((column) => {
                    const value = cellText(order, column.key);
                    return (
                      <td key={column.key} className="max-w-xs truncate whitespace-nowrap px-3 py-2.5" title={value}>
                        {value || "—"}
                      </td>
                    );
                  })}
                </tr>
                {expandedOrder === `${order.siteid}-${order.wonum}` && (
                  <tr>
                    <td colSpan={orderColumns.length + 1} className="p-4">
                      <OrderDetails order={order} />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={orderColumns.length + 1} className="px-4 py-8 text-center text-slate-400">
                    {loading ? "Carregando OTs..." : "Nenhuma OT corresponde aos filtros."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {sorted.length > limit && (
          <div className="border-t border-white/10 p-3 text-center">
            <button
              type="button"
              onClick={() => setLimit((current) => current + PAGE_SIZE)}
              className="text-sm font-medium text-accent-400 transition hover:text-accent-500"
            >
              Mostrar mais ({sorted.length - limit} restantes)
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
