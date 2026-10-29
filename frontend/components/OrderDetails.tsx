import type { OrdemTrabalho } from "@/services/api";
import { cellText } from "@/utils/orderFilters";
import { plannedLabor } from "@/utils/plannedLabor";

const groups = [
  {
    title: "Identificação e preparação",
    fields: [
      ["description", "Descrição"], ["location", "Local"], ["assetnum", "Equipamento"],
      ["status", "Status"], ["worktype", "Tipo"], ["maintenanceshop", "Setor"], ["lead", "Mão de obra"],
      ["planner", "Planejador"], ["crew", "Equipe"], ["jpnum", "Plano de trabalho"],
      ["pmnum", "PM"], ["route", "Rota"], ["parent", "OT principal"],
      ["interruptible", "Pode ser interrompida"],
    ],
  },
  {
    title: "Datas de planejamento e acompanhamento",
    fields: [
      ["sneconstraint", "Não iniciar antes de"], ["fnlconstraint", "Não terminar depois de"],
      ["targstartdate", "Início previsto"], ["targcompdate", "Término previsto"],
      ["schedstart", "Início planejado"], ["schedfinish", "Término programado"],
      ["pmduedate", "Vencimento da PM"], ["pmnextduedate", "Próximo vencimento da PM"],
      ["actstart", "Início real"], ["actfinish", "Término real"],
      ["reportdate", "Registro"], ["statusdate", "Alteração do status"],
      ["changedate", "Última alteração"],
    ],
  },
  {
    title: "Duração e mão de obra",
    fields: [
      ["estdur", "Duração estimada (h)"], ["estlabhrs", "Mão de obra estimada (h)"],
      ["estintlabhrs", "Mão de obra interna estimada (h)"],
      ["estoutlabhrs", "Mão de obra externa estimada (h)"],
      ["actlabhrs", "Mão de obra realizada (h)"],
      ["reportedby", "Registrada por"], ["changeby", "Alterada por"],
    ],
  },
] as const;

const dateFields = new Set<string>(groups[1].fields.map(([key]) => key));
const dateFormatter = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short",
});

function displayValue(order: OrdemTrabalho, key: string): string {
  const value = cellText(order, key);
  if (!value) return "Não informado na coleta";
  if (key === "interruptible") {
    if (["true", "1"].includes(value)) return "Sim";
    if (["false", "0"].includes(value)) return "Não";
  }
  if (dateFields.has(key)) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      return `${dateFormatter.format(date)} (Brasília)`;
    }
  }
  return value;
}

function dateFieldStyle(key: string): string {
  if (key === "targstartdate") return "mt-1 inline-block rounded border border-white/70 bg-white/5 px-2 py-1";
  if (key === "sneconstraint" || key === "fnlconstraint")
    return "mt-1 inline-block rounded border border-amber-400/80 bg-amber-400/5 px-2 py-1";
  return "";
}

function Fields({ order }: { order: OrdemTrabalho }) {
  const labor = plannedLabor(order);
  return (
    <div className="space-y-5">
      <div>
        <h4 className="mb-2 font-semibold text-white">Instruções completas</h4>
        <p className="whitespace-pre-wrap break-words text-sm text-slate-300">
          {cellText(order, "description_longdescription") || "Instruções não informadas na coleta."}
        </p>
      </div>
      {groups.map((group) => (
        <section key={group.title}>
          <h4 className="mb-2 font-semibold text-white">{group.title}</h4>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {group.fields.map(([key, label]) => (
              <div key={key}>
                <dt className="text-xs text-slate-400">{label}</dt>
                <dd className={`whitespace-normal break-words text-sm text-slate-200 ${dateFieldStyle(key)}`}>{displayValue(order, key)}</dd>
              </div>
            ))}
            <section>
              <h4 className="mb-2 font-semibold text-white">Mão de obra planejada no BMA</h4>
              {!Array.isArray(order.dados.wplabor) ? <p className="text-sm text-amber-300">Atualize o banco para coletar especialidade, quantidade e horas planejadas.</p>
                : !labor.length ? <p className="text-sm text-slate-400">Nenhuma especialidade planejada retornada pelo BMA.</p>
                  : <div className="space-y-2">{labor.map((row, i) => <p key={i} className="text-sm text-slate-200">
                    Especialidade {row.craft} · Organização {row.orgid || "não informada"} · Quantidade {row.quantity || "não informada"} · Horas normais {row.hours || "não informadas"}{row.skill ? ` · Nível ${row.skill}` : ""}
                  </p>)}</div>}
            </section>
          </dl>
        </section>
      ))}
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export default function OrderDetails({ order }: { order: OrdemTrabalho }) {
  const children = order.dados.children;
  return (
    <div className="max-w-6xl space-y-6 rounded-lg border border-white/10 bg-navy-900 p-5">
      <h3 className="text-lg font-semibold text-white">Detalhes da OT {order.wonum}</h3>
      <Fields order={order} />
      <section>
        <h4 className="mb-2 font-semibold text-white">OTs filhas e tarefas diretas</h4>
        {!Array.isArray(children) ? (
          <p className="text-sm text-amber-300">Sincronize novamente para coletar as filhas e tarefas.</p>
        ) : children.length === 0 ? (
          <p className="text-sm text-slate-400">Nenhuma filha ou tarefa direta retornada pelo BMA.</p>
        ) : (
          <div className="space-y-3">
            {children.filter(isRecord).map((child, index) => {
              const childOrder: OrdemTrabalho = {
                siteid: String(child.siteid ?? ""),
                wonum: String(child.wonum ?? ""),
                status: String(child.status ?? ""),
                maintenanceshop: String(child.maintenanceshop ?? ""),
                sincronizado_em: order.sincronizado_em,
                dados: child,
              };
              return (
                <details key={`${childOrder.wonum}-${index}`} className="rounded border border-white/10 p-3">
                  <summary className="cursor-pointer text-sm font-medium text-accent-400">
                    {childOrder.wonum} — {cellText(childOrder, "description")}
                  </summary>
                  <div className="mt-4"><Fields order={childOrder} /></div>
                </details>
              );
            })}
          </div>
        )}
      </section>
      <p className="text-xs text-slate-400">
        Última sincronização: {dateFormatter.format(new Date(order.sincronizado_em))} (Brasília).
        Materiais, ferramentas, anexos e equipes detalhadas não são consultados nesta coleta.
      </p>
    </div>
  );
}
