type UploadPanelProps = {
  file: File | null;
  loading: boolean;
  onSelect: (file: File | null) => void;
  onProcess: () => void;
};

export default function UploadPanel({ file, loading, onSelect, onProcess }: UploadPanelProps) {
  return (
    <section className="rounded-2xl border border-white/10 bg-navy-800/60 p-6">
      <h2 className="text-lg font-semibold text-white">Upload da planilha</h2>
      <p className="mt-1 text-sm text-slate-300">
        Aceita apenas <strong>.xlsx</strong> e <strong>.xls</strong> no modelo padrão de anomalias.
        Elegível só com <strong>Nº OT BMA</strong> vazio e TaskStatus diferente de Planejado, Concluído, Preparado e Cancelado.
      </p>

      <label
        htmlFor="planilha"
        className="mt-5 flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-accent-400/40 bg-navy-950/40 px-4 py-8 text-center transition hover:border-accent-400"
      >
        <input
          id="planilha"
          type="file"
          accept=".xlsx,.xls,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          className="hidden"
          onChange={(event) => onSelect(event.target.files?.[0] || null)}
        />
        <p className="text-sm text-slate-300">Arraste o arquivo ou clique para selecionar</p>
        <p className="mt-2 text-base font-medium text-white">
          {file ? file.name : "Nenhum arquivo selecionado"}
        </p>
      </label>

      <div className="mt-5 flex flex-wrap gap-3">
        <label
          htmlFor="planilha"
          className="cursor-pointer rounded-lg bg-white/10 px-4 py-2.5 text-sm font-medium text-white hover:bg-white/15"
        >
          Selecionar Arquivo
        </label>
        <button
          type="button"
          onClick={onProcess}
          disabled={!file || loading}
          className="rounded-lg bg-accent-500 px-4 py-2.5 text-sm font-semibold text-navy-950 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "Processando..." : "Processar Arquivo"}
        </button>
      </div>
    </section>
  );
}
