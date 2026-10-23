import { parseError, type OrdemTrabalho, type PlanejamentoEquipe } from "@/services/api";

export type PlanningMode = "pm" | "corretiva";
export type Requirement = {
  duracao: number | null; pessoas: number | null; orgid: string; funcao: string;
  prioridade: number; liberada: boolean; observacao: string;
  todas_especialidades?: boolean;
  selecionada?: boolean;
};
export type Allocation = {
  id: string; ot: string; dia: string; inicio: number; horas: number; executantes: string[];
};
export type Unavailable = { executante: string; dia: string; motivo: string };
export type Placement = { ot: string; executante: string; dia: string };
export type PlanPerson = {
  id: string; nome: string; orgid: string; matricula: string; funcao: string;
  funcao_descricao: string; dias: string[];
};
export type WorkPlan = {
  id: string; revisao: number; status: "rascunho" | "confirmado";
  inicio: string; fim: string; setores: string[]; planejador: string;
  atualizado_em: string; motivo: string;
  integracoes: { bma: "pendente_configuracao"; sharepoint: "pendente_configuracao" };
  equipe: PlanejamentoEquipe; pessoas: PlanPerson[]; ordens: OrdemTrabalho[];
  requisitos: Record<string, Requirement>; blocos: Allocation[]; indisponibilidades: Unavailable[];
  posicionamentos?: Placement[];
};
export type PlanSummary = Pick<WorkPlan, "id" | "revisao" | "status" | "inicio" | "fim" | "setores" | "planejador" | "atualizado_em" | "motivo">;
export type PlanRevision = { revisao: number; salvo_em: string; motivo: string };
export type PlanChange = Pick<WorkPlan, "revisao" | "requisitos" | "blocos" | "indisponibilidades" | "posicionamentos"> & { motivo: string; confirmar: boolean; atualizar_especialidades?: boolean };
export const orderKey = (order: OrdemTrabalho) => `${order.siteid}:${order.wonum}`;
const BASE = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/pcm`;

async function request<T>(path: string, method = "GET", payload?: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method, headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}
export const createWorkPlan = (setores: string[]) => request<WorkPlan>("/planos", "POST", { setores });
export const getWorkPlan = (id: string) => request<WorkPlan>(`/planos/${encodeURIComponent(id)}`);
export const listWorkPlans = () => request<PlanSummary[]>("/planos");
export const saveWorkPlan = (id: string, change: PlanChange) => request<WorkPlan>(`/planos/${id}`, "PUT", change);
export const suggestWorkPlan = (id: string, modo: PlanningMode, alteracoes: PlanChange, ordens: string[]) =>
  request<{ blocos: Allocation[]; mensagens: string[] }>(`/planos/${id}/sugerir`, "POST", { modo, alteracoes, ordens });
export const getRevisions = (id: string) => request<PlanRevision[]>(`/planos/${id}/revisoes`);
export const refreshPlanSpecialties = (id: string, change: PlanChange) =>
  request<{ plano: WorkPlan; atualizadas: number }>(`/planos/${id}/especialidades`, "POST", change);

async function download(path: string, name: string, payload?: unknown) {
  const response = await fetch(`${BASE}${path}`, payload === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const downloadSchedule = (id: string, revision: number) =>
  download(`/planos/${id}/revisoes/${revision}/pdf`, `cronograma-${id}-r${revision}.pdf`);
export const exportPortfolio = (setores: string[], inicio: string, fim: string, modo: PlanningMode, ordens: OrdemTrabalho[]) =>
  download("/exportar", `carteira-${modo}-${inicio || "carteira-aberta"}.xlsx`, { setores, inicio: inicio || null, fim: fim || null, modo, ordens: ordens.map(orderKey) });
export const exportNfeReport = (jobId: string) =>
  download(`/exportar-nfe/${encodeURIComponent(jobId)}`, "Planejamento NFE.xlsx");
