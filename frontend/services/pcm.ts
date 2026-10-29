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
export type BmaPageField = { tag: string; id: string; name: string; label: string; type: string; disabled: boolean; frame?: string };
export type BmaPlanningResult = {
  numero_ot: string; descricao: string; tipo_ordem: string; status: string; equipamento: string;
  localizacao: string; data_planejada: string; inicio_planejado: string; termino_planejado: string;
  janela_execucao: string; dia_execucao: string; executor: string; equipe_responsavel: string;
  duracao_planejada: string; prioridade: string; dados_adicionais: Record<string, unknown>;
  situacao_consulta: "sucesso" | "planejada" | "ja_planejada" | "pendente_planejador" | "nao_encontrada" | "erro"; erro: string | null;
};
export type BmaPageMonitor = {
  monitor_id: string; status: "starting" | "monitoring" | "stopping" | "stopped" | "completed" | "failed";
  message: string; fields: BmaPageField[]; elapsed_seconds?: number;
  mode?: "search_only" | "open_order" | "planning_read" | "planning_send" | "open_ot" | "observe"; inspection_only?: boolean;
  progress?: number;
  stage?: string; selected_wonums?: string[]; opened_wonum?: string | null;
  queue_total?: number; current_order_index?: number; current_wonum?: string | null;
  completed_wonums?: string[]; failed_wonum?: string | null;
  page_url?: string; page_title?: string;
  processadas?: number; planejadas?: number; pendentes?: number; com_erro?: number; resultados?: BmaPlanningResult[];
};
export type BmaOrderPlan = {
  siteid: string; wonum: string; planned_start: string; planned_finish: string; specialty: string;
  assignments: { dia: string; laborcode: string; horas: number }[];
};
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
export const deleteWorkPlan = (id: string) => request<{ id: string; deleted: boolean }>(`/planos/${encodeURIComponent(id)}`, "DELETE");
export const saveWorkPlan = (id: string, change: PlanChange) => request<WorkPlan>(`/planos/${id}`, "PUT", change);
export const updateWorkPlanTeam = (id: string, revisao: number, equipe: PlanejamentoEquipe) =>
  request<WorkPlan>(`/planos/${encodeURIComponent(id)}/equipe`, "PUT", { revisao, equipe });
export const suggestWorkPlan = (id: string, modo: PlanningMode, alteracoes: PlanChange, ordens: string[]) =>
  request<{ blocos: Allocation[]; mensagens: string[] }>(`/planos/${id}/sugerir`, "POST", { modo, alteracoes, ordens });
export const getRevisions = (id: string) => request<PlanRevision[]>(`/planos/${id}/revisoes`);
export const refreshPlanSpecialties = (id: string, change: PlanChange) =>
  request<{ plano: WorkPlan; atualizadas: number }>(`/planos/${id}/especialidades`, "POST", change);
export const startBmaPageMonitor = (orders: BmaOrderPlan[]) => request<{ monitor_id: string }>("/bma-page-monitor", "POST", { orders });
export const startBmaPageSearch = (wonum: string) => request<{ monitor_id: string }>("/bma-page-monitor/search", "POST", { wonum });
export const startBmaPageOpenOrder = (wonum: string) => request<{ monitor_id: string }>("/bma-page-monitor/open-order", "POST", { wonum });
export const sendPlanningToBmaReader = (planId: string) =>
  request<{ monitor_id: string; total: number }>(`/planos/${encodeURIComponent(planId)}/enviar-planejamento`, "POST");
export type BmaSendStatus = { numero_ot: string; situacao: BmaPlanningResult["situacao_consulta"]; registrado_em: string; erro: string | null };
export const getBmaSendStatus = (planId: string) => request<BmaSendStatus[]>(`/planos/${encodeURIComponent(planId)}/envios-bma`);
export const openOrderInBma = (wonum: string) => request<{ monitor_id: string }>("/bma-page-monitor/abrir-ot", "POST", { wonum });
export const getBmaPageMonitor = (id: string) => request<BmaPageMonitor>(`/bma-page-monitor/${encodeURIComponent(id)}`);
export const stopBmaPageMonitor = (id: string) => request<BmaPageMonitor>(`/bma-page-monitor/${encodeURIComponent(id)}`, "DELETE");

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
export const getSchedulePdf = async (id: string, revision: number): Promise<Blob> => {
  const response = await fetch(`${BASE}/planos/${encodeURIComponent(id)}/revisoes/${revision}/pdf`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.blob();
};
export const exportPortfolio = (setores: string[], inicio: string, fim: string, modo: PlanningMode, ordens: OrdemTrabalho[]) =>
  download("/exportar", `carteira-${modo}-${inicio || "carteira-aberta"}.xlsx`, { setores, inicio: inicio || null, fim: fim || null, modo, ordens: ordens.map(orderKey) });
export const exportNfeReport = (jobId: string) =>
  download(`/exportar-nfe/${encodeURIComponent(jobId)}`, "Planejamento NFE.xlsx");
