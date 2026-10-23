type HeaderProps = {
  status: string;
};

export default function Header({ status }: HeaderProps) {
  const online = status === "online";

  return (
    <header className="flex items-center justify-between rounded-2xl border border-white/10 bg-navy-800/70 px-5 py-4 shadow-lg backdrop-blur">
      <div className="flex items-center gap-4">
        <img src="/logo.svg?v=robomario" alt="Logo RoboMario" className="h-12 w-12" />
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-accent-400">Intranet local</p>
          <h1 className="text-xl font-semibold text-white">RoboMario</h1>
          <p className="text-sm text-slate-300">Processamento de planilhas para Ordens de Trabalho</p>
          <p className="text-xs text-slate-400">Em homenagem ao Romario</p>
        </div>
      </div>
      <div className="flex items-center gap-2 rounded-full border border-white/10 bg-navy-950/70 px-4 py-2">
        <span className={`h-2.5 w-2.5 rounded-full ${online ? "bg-emerald-400" : "bg-rose-400"}`} />
        <span className="text-sm text-slate-200">{online ? "Sistema online" : "Sistema offline"}</span>
      </div>
    </header>
  );
}
