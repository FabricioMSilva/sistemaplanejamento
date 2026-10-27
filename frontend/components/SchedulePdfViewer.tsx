import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";

export default function SchedulePdfViewer({ file }: { file: Blob }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [containerWidth, setContainerWidth] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let loadingTask: ReturnType<typeof import("pdfjs-dist").getDocument> | undefined;

    async function loadPdf() {
      setLoading(true);
      setError("");
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        loadingTask = pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) });
        const loaded = await loadingTask.promise;
        if (cancelled) {
          await loaded.destroy();
          return;
        }
        setDocument(loaded);
        setPageCount(loaded.numPages);
        setPageNumber(1);
      } catch (failure) {
        if (!cancelled) setError(failure instanceof Error ? failure.message : "Não foi possível carregar o PDF.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadPdf();
    return () => {
      cancelled = true;
      void loadingTask?.destroy();
    };
  }, [file]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const updateWidth = () => setContainerWidth(container.clientWidth);
    updateWidth();
    const observer = new ResizeObserver(updateWidth);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!document || !containerWidth || !canvasRef.current) return;
    let cancelled = false;
    let renderTask: RenderTask | undefined;

    async function renderPage() {
      try {
        const page = await document!.getPage(pageNumber);
        if (cancelled || !canvasRef.current) return;
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = Math.min(1.6, Math.max(0.1, (containerWidth - 40) / baseViewport.width));
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Não foi possível desenhar a página do PDF.");
        const outputScale = window.devicePixelRatio || 1;
        canvas.width = Math.ceil(viewport.width * outputScale);
        canvas.height = Math.ceil(viewport.height * outputScale);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        renderTask = page.render({
          canvasContext: context,
          viewport,
          transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
        });
        await renderTask.promise;
      } catch (failure) {
        if (!cancelled && !(failure instanceof Error && failure.name === "RenderingCancelledException"))
          setError(failure instanceof Error ? failure.message : "Não foi possível renderizar a página do PDF.");
      }
    }

    void renderPage();
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [containerWidth, document, pageNumber]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded bg-[#383838]">
      <div role="toolbar" aria-label="Navegação do PDF" className="flex shrink-0 items-center justify-center gap-3 border-b border-white/10 bg-[#242424] px-3 py-2">
        <button type="button" aria-label="Página anterior" title="Página anterior" disabled={pageNumber <= 1 || loading}
          className="rounded p-1.5 text-slate-200 hover:bg-white/10 disabled:opacity-40" onClick={() => setPageNumber((value) => Math.max(1, value - 1))}>
          <ChevronLeft size={18} />
        </button>
        <span aria-live="polite" className="min-w-24 text-center text-xs text-slate-200">{loading ? "Carregando PDF..." : `Página ${pageNumber} de ${pageCount}`}</span>
        <button type="button" aria-label="Próxima página" title="Próxima página" disabled={pageNumber >= pageCount || loading}
          className="rounded p-1.5 text-slate-200 hover:bg-white/10 disabled:opacity-40" onClick={() => setPageNumber((value) => Math.min(pageCount, value + 1))}>
          <ChevronRight size={18} />
        </button>
      </div>
      <div ref={containerRef} className="min-h-0 flex-1 overflow-auto p-3 sm:p-6">
        {loading && <div role="status" className="flex h-full items-center justify-center gap-2 text-sm text-slate-200"><Loader2 size={16} className="animate-spin" /> Carregando cronograma...</div>}
        {error && <p role="alert" className="mx-auto mt-6 max-w-xl rounded border border-rose-300/30 bg-rose-950/50 p-4 text-sm text-rose-100">Erro ao exibir o PDF: {error}</p>}
        <div className={`mx-auto w-fit bg-white shadow-xl ${loading || error ? "hidden" : ""}`}><canvas ref={canvasRef} className="block max-w-full" aria-label={`Página ${pageNumber} do cronograma PDF`} /></div>
      </div>
    </div>
  );
}
