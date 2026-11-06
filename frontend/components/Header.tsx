import { ClipboardList } from "lucide-react";

type HeaderProps = {
  status: string;
};

export default function Header({ status }: HeaderProps) {
  const online = status === "online";

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border bg-card px-5 py-4 shadow-card">
      <div className="flex items-center gap-4">
        <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <ClipboardList size={24} aria-hidden="true" />
        </span>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Ordens de trabalho</p>
          <h1 className="text-xl font-semibold text-card-foreground">Criar OT</h1>
        </div>
      </div>
      <div className="flex items-center gap-2 rounded-full border border-border bg-muted px-4 py-2" role="status">
        <span className={`h-2.5 w-2.5 rounded-full ${online ? "bg-success" : "bg-danger"}`} aria-hidden="true" />
        <span className="text-sm text-foreground">{online ? "Sistema online" : "Sistema offline"}</span>
      </div>
    </header>
  );
}
