import { useEffect, useRef, useState } from "react";
import type { ProcessResult } from "@/services/api";

type PreviewPanelProps = {
  result: ProcessResult | null;
  error: string | null;
  creating?: boolean;
  onCriarOts?: (indices: number[]) => void;
};

const PREVIEW_LETTERS = ["A", "C", "D", "F"];

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}

export default function PreviewPanel({ result, error, creating = false, onCriarOts }: PreviewPanelProps) {
  const columns = result?.preview_colunas || [];
  const rows = result?.preview || [];
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setSelected(new Set());
  }, [result?.id]);

  const allSelected = rows.length > 0 && selected.size === rows.length;
  const someSelected = selected.size > 0 && !allSelected;

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someSelected;
    }
  }, [someSelected]);

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(rows.map((_, index) => index)));
  }

  function toggleRow(index: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  return (
    <section className="flex min-h-80 flex-col rounded-2xl border border-white/10 bg-navy-800/60 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Pré-visualização</h2>
          <p className="mt-1 text-sm text-slate-400">
            Selecione um a um ou todos de uma vez para criar as OTs. Colunas A, C, D e F das linhas elegíveis.
          </p>
        </div>
        {rows.length > 0 && (
          <button
            type="button"
            onClick={() => onCriarOts?.(Array.from(selected).sort((a, b) => a - b))}
            disabled={selected.size === 0 || creating || !onCriarOts}
            className="rounded-lg bg-accent-500 px-4 py-2.5 text-sm font-semibold text-navy-950 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {creating
              ? "Criando OTs..."
              : selected.size === 0
                ? "Criar OTs"
                : `Criar ${selected.size} OT${selected.size === 1 ? "" : "s"}`}
          </button>
        )}
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          {error}
        </div>
      )}

      {result ? (
        <>
          <div className="mt-4 grid grid-cols-3 gap-2 text-center text-sm">
            <div className="rounded-lg bg-navy-950/70 p-3">
              <p className="text-slate-400">Total de linhas</p>
              <p className="mt-1 text-xl font-semibold text-white">{result.total_registros}</p>
            </div>
            <div className="rounded-lg bg-navy-950/70 p-3">
              <p className="text-slate-400">Elegíveis</p>
              <p className="mt-1 text-xl font-semibold text-emerald-300">{result.registros_processados}</p>
            </div>
            <div className="rounded-lg bg-navy-950/70 p-3">
              <p className="text-slate-400">Ignoradas</p>
              <p className="mt-1 text-xl font-semibold text-amber-300">{result.registros_ignorados}</p>
            </div>
          </div>

          {rows.length === 0 ? (
            <p className="mt-4 text-sm text-slate-400">Nenhuma linha elegível para exibir.</p>
          ) : (
            <>
              <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-300">
                <label className="inline-flex cursor-pointer items-center gap-2">
                  <input
                    ref={selectAllRef}
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    className="h-4 w-4 accent-accent-500"
                  />
                  Selecionar todos
                </label>
                <span className="text-slate-500">
                  {selected.size} de {rows.length} selecionada{selected.size === 1 ? "" : "s"}
                </span>
              </div>
              <div className="mt-3 flex-1 overflow-auto rounded-xl border border-white/10">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead className="sticky top-0 bg-navy-950">
                    <tr>
                      <th className="w-12 border-b border-white/10 px-3 py-2">
                        <span className="sr-only">Selecionar</span>
                      </th>
                      {columns.map((column, index) => (
                        <th
                          key={column}
                          className="whitespace-nowrap border-b border-white/10 px-3 py-2 font-semibold text-accent-400"
                        >
                          <span className="mr-2 text-xs text-slate-500">{PREVIEW_LETTERS[index]}</span>
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, rowIndex) => {
                      const isSelected = selected.has(rowIndex);
                      return (
                        <tr
                          key={rowIndex}
                          className={`${isSelected ? "bg-accent-500/10" : "odd:bg-navy-950/40 even:bg-navy-900/20"}`}
                        >
                          <td className="border-b border-white/5 px-3 py-2 align-top">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleRow(rowIndex)}
                              aria-label={`Selecionar linha ${rowIndex + 1}`}
                              className="h-4 w-4 accent-accent-500"
                            />
                          </td>
                          {columns.map((column) => (
                            <td key={column} className="max-w-md border-b border-white/5 px-3 py-2 align-top text-slate-200">
                              {cellText(row[column])}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      ) : (
        !error && (
          <p className="mt-4 text-sm text-slate-400">A tabela das colunas A, C, D e F aparecerá aqui após o processamento.</p>
        )
      )}
    </section>
  );
}
