import type { LogEntry } from "@/services/api";

type LogPanelProps = {
  logs: LogEntry[];
};

export default function LogPanel({ logs }: LogPanelProps) {
  return (
    <section className="flex min-h-80 flex-col rounded-2xl border border-white/10 bg-navy-800/60 p-5">
      <h2 className="text-lg font-semibold text-white">Logs</h2>
      <div className="mt-3 flex-1 overflow-auto rounded-xl bg-navy-950/70 p-3 font-mono text-xs">
        {logs.length === 0 ? (
          <p className="text-slate-400">Nenhum log registrado ainda.</p>
        ) : (
          <ul className="space-y-2">
            {logs.map((log, index) => (
              <li key={`${log.data_hora}-${index}`} className="text-slate-300">
                <span className="text-accent-400">{log.data_hora}</span>
                <span className={`ml-2 uppercase ${log.nivel === "error" ? "text-rose-400" : "text-sky-300"}`}>
                  [{log.nivel}]
                </span>
                <span className="ml-2">{log.mensagem}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
