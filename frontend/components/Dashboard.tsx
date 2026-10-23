import type { DashboardData } from "@/services/api";

type DashboardProps = {
  data: DashboardData | null;
};

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-navy-900/80 p-4">
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-2 truncate text-lg font-semibold text-white" title={value}>
        {value}
      </p>
    </div>
  );
}

export default function Dashboard({ data }: DashboardProps) {
  const ultimo = data?.ultimo_arquivo?.nome_arquivo || "Nenhum arquivo";
  const processados = data?.total_registros_processados ?? 0;
  const pendente = data?.total_pendente ?? 0;
  const status = data?.status_sistema === "online" ? "Online" : "Offline";

  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Card label="Último arquivo enviado" value={ultimo} />
      <Card label="Total de registros processados" value={String(processados)} />
      <Card label="Total pendente (aguardando OT)" value={String(pendente)} />
      <Card label="Status do sistema" value={status} />
    </section>
  );
}
