import { apiFetch, parseError, type OrdemTrabalho, type PlanejamentoEquipe } from "@/services/api";

export type PlanningMode = "pm" | "corretiva";
export type Requirement = {
  duracao: number | null; pessoas: number | null; orgid: string; funcao: string;
  prioridade: number; liberada: boolean; observacao: string;
  todas_especialidades?: boolean;
  selecionada?: boolean;
  na_nuvem?: boolean;
};
export type Allocation = {
  id: string; ot: string; dia: string; inicio: number; horas: number; executantes: string[];
};
export type Unavailable = { executante: string; dia: string; motivo: string };
export type Placement = { ot: string; executante: string; dia: string };
export type OvertimeAllocation = { ot: string; executante: string; dia: string; horas: number };
export type BmaPreparationRequirement = { especialidade: string; orgid: string; quantidade: number; horas_normais: string };
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
  posicionamentos?: Placement[]; horas_extras?: OvertimeAllocation[];
};
export type PlanSummary = Pick<WorkPlan, "id" | "revisao" | "status" | "inicio" | "fim" | "setores" | "planejador" | "atualizado_em" | "motivo">;
export type PlanRevision = { revisao: number; salvo_em: string; motivo: string };
export type PlanChange = Pick<WorkPlan, "revisao" | "requisitos" | "blocos" | "indisponibilidades" | "posicionamentos" | "horas_extras"> & { motivo: string; confirmar: boolean; atualizar_especialidades?: boolean };
export type BmaPageField = { tag: string; id: string; name: string; label: string; type: string; disabled: boolean; frame?: string };
export type BmaPlanningResult = {
  numero_ot: string; descricao: string; tipo_ordem: string; status: string; equipamento: string;
  localizacao: string; data_planejada: string; inicio_planejado: string; termino_planejado: string;
  janela_execucao: string; dia_execucao: string; executor: string; equipe_responsavel: string;
  duracao_planejada: string; prioridade: string; dados_adicionais: Record<string, unknown>;
  requisitos_mao_de_obra?: BmaPreparationRequirement[];
  situacao_consulta: "sucesso" | "planejada" | "ja_planejada" | "pendente_planejador" | "nao_encontrada" | "erro"; erro: string | null;
};
export type RondaSharePointItem = {
  id: number;
  numero_ot: string;
  status: string;
  ronda: string;
  executantes: { nome: string; matricula: string | null; matricula_lista: string | null; orgid: string | null;
    vinculo: "confirmado" | "referencia_json" | "sem_vinculo" | "ambiguo"; fonte_matricula?: "json" | null }[];
  bloqueios_matricula: string[];
};
export type RondaEmployee = {
  nome: string; matricula_lista: string; matricula_bma: string; orgid: string;
  vinculo: "confirmado" | "referencia_json" | "sem_vinculo" | "ambiguo"; atualizado_em: string;
};
export type RondaDashboard = {
  total: number; pendentes: number; aptas: number; bloqueadas: number; criadas: number; falhas_criacao: number;
  salvas: number; numeros_gerados: number;
  falhas: { sharepoint_id: number; ronda: string; numero_ot: string | null; registrado_em: string | null;
    status: "erro" | "numero_gerado" | "salva"; erro: string | null }[];
  rondas: { nome: string; total: number; aptas: number }[];
  atualizado_em: string | null; funcionarios: number;
  graficos: {
    inicio: string; fim: string;
    modalidades: { key: string; label: string; meta_diaria: number }[];
    diario: { date: string; label: string; weekday: string; analises: number; analises_meta: number;
      equipamentos: number; equipamentos_meta: number; medidores: number; medidores_meta: number }[];
    equipes: string[];
    faltas_por_dia_semana: ({ weekday: string } & Record<string, number | string>)[];
    faltas_detalhadas: { date: string; weekday: string; team: string; turno: string; modalidade: string; faltantes: number }[];
  };
};
export type BmaPageMonitor = {
  monitor_id: string; status: "starting" | "monitoring" | "pausing" | "paused" | "stopping" | "stopped" | "completed" | "failed";
  message: string; fields: BmaPageField[]; elapsed_seconds?: number;
  mode?: "search_only" | "open_order" | "preparation_collection" | "planning_read" | "planning_send" | "planning_import" | "open_ot" | "observe" | "ronda_sharepoint" | "ronda_excel_export" | "ronda_creation" | "bma_entry"; inspection_only?: boolean;
  progress?: number;
  stage?: string; selected_wonums?: string[]; opened_wonum?: string | null;
  queue_total?: number; current_order_index?: number; current_wonum?: string | null;
  completed_wonums?: string[]; failed_wonum?: string | null;
  failed_wonums?: { wonum: string; message: string }[];
  collected_count?: number; rows_found?: number; empty_count?: number; failed_count?: number;
  page_url?: string; page_title?: string;
  processadas?: number; planejadas?: number; pendentes?: number; com_erro?: number; resultados?: BmaPlanningResult[];
  importadas?: string[]; avisos_importacao?: string[]; plan_revision?: number; import_applied?: boolean;
  ronda_items?: RondaSharePointItem[]; ronda_items_bloqueados?: RondaSharePointItem[];
  ronda_counts?: Record<string, number>;
  ronda_funcionarios?: RondaEmployee[]; ronda_funcionarios_novos?: number;
  ronda_ots_criadas?: { numero_ot: string; sharepoint_ids: number[]; ronda: string; status?: string }[];
  ronda_ots_salvas?: { numero_ot: string; sharepoint_ids: number[]; ronda: string; status: string }[];
  ronda_remaining?: number;
  current_sharepoint_ids?: number[];
  events?: { stage: string; message: string; at: string }[];
};
export type BmaOrderPlan = {
  siteid: string; wonum: string; planned_start: string; planned_finish: string; specialty: string;
  assignments: { dia: string; laborcode: string; horas: number }[];
};
export type BmaPreparationOrder = { siteid: string; wonum: string };
export const orderKey = (order: OrdemTrabalho) => `${order.siteid}:${order.wonum}`;
const BASE = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/pcm`;

async function request<T>(path: string, method = "GET", payload?: unknown): Promise<T> {
  const response = await apiFetch(`${BASE}${path}`, {
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
export const addOrdersToPlan = (id: string, revisao: number, ordens: string[]) =>
  request<WorkPlan>(`/planos/${encodeURIComponent(id)}/ordens`, "POST", { revisao, ordens });
export const refreshPlanOrders = (id: string, revisao: number) =>
  request<{ plano: WorkPlan; atualizadas: number }>(`/planos/${encodeURIComponent(id)}/atualizar-ots`, "POST", { revisao });
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
export const startBmaPreparationCollection = (orders: BmaPreparationOrder[]) =>
  request<{ monitor_id: string }>("/bma-page-monitor/preparation-collection", "POST", { orders });
export const startRondaSharePointCollection = () =>
  request<{ monitor_id: string }>("/bma-page-monitor/ronda-sharepoint", "POST");
export const startRondaExcelExport = () =>
  request<{ monitor_id: string }>("/bma-page-monitor/ronda-excel", "POST");
export const startRondaCreation = (retryFailed = true, quantity: "uma" | "lote" = "uma") =>
  request<{ monitor_id: string }>("/bma-page-monitor/ronda-criar", "POST", { retry_failed: retryFailed, quantidade: quantity });
export const pauseRondaCreation = (id: string) =>
  request<BmaPageMonitor>(`/bma-page-monitor/${encodeURIComponent(id)}/pause`, "POST");
export const resumeRondaCreation = (id: string) =>
  request<BmaPageMonitor>(`/bma-page-monitor/${encodeURIComponent(id)}/resume`, "POST");
export const getRondaDashboard = () => request<RondaDashboard>("/bma-page-monitor/ronda-dashboard");
export const startBmaEntry = () => request<{ monitor_id: string }>("/bma-page-monitor/enter-bma", "POST");
export const getRondaEmployees = () => request<RondaEmployee[]>("/bma-page-monitor/ronda-funcionarios");
export const sendPlanningToBmaReader = (planId: string) =>
  request<{ monitor_id: string; total: number }>(`/planos/${encodeURIComponent(planId)}/enviar-planejamento`, "POST");
export const importPlanningFromBma = (planId: string) =>
  request<{ monitor_id: string; total: number }>(`/planos/${encodeURIComponent(planId)}/importar-bma`, "POST");
export const applyBmaPlanningImport = (planId: string, monitorId: string) =>
  request<BmaPageMonitor>(`/planos/${encodeURIComponent(planId)}/importar-bma/aplicar`, "POST", { monitor_id: monitorId });
export type BmaSendStatus = { numero_ot: string; situacao: BmaPlanningResult["situacao_consulta"]; registrado_em: string; erro: string | null };
export const getBmaSendStatus = (planId: string) => request<BmaSendStatus[]>(`/planos/${encodeURIComponent(planId)}/envios-bma`);
export const openOrderInBma = (wonum: string) => request<{ monitor_id: string }>("/bma-page-monitor/abrir-ot", "POST", { wonum });
export const getBmaPageMonitor = (id: string) => request<BmaPageMonitor>(`/bma-page-monitor/${encodeURIComponent(id)}`);
export const stopBmaPageMonitor = (id: string) => request<BmaPageMonitor>(`/bma-page-monitor/${encodeURIComponent(id)}`, "DELETE");

async function download(path: string, name: string, payload?: unknown) {
  const response = await apiFetch(`${BASE}${path}`, payload === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = name; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const fileDate = (isoDate: string) => `${isoDate.slice(8, 10)}-${isoDate.slice(5, 7)}`;
const safeFileName = (value: string) => value.trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, " ").replace(/\s+/g, "_") || "Integrante";
export const downloadSchedule = (id: string, revision: number, inicio: string, fim: string) =>
  download(`/planos/${encodeURIComponent(id)}/revisoes/${revision}/pdf`,
    `Geral-Cronograma-dia-${fileDate(inicio)}-a-${fileDate(fim)}.pdf`);
export const downloadPersonSchedule = (id: string, revision: number, executante: string, nome: string) =>
  download(`/planos/${encodeURIComponent(id)}/revisoes/${revision}/pdf?executante=${encodeURIComponent(executante)}`,
    `${safeFileName(nome)}-NFE-Cronograma.pdf`);
export const getSchedulePdf = async (id: string, revision: number): Promise<Blob> => {
  const response = await apiFetch(`${BASE}/planos/${encodeURIComponent(id)}/revisoes/${revision}/pdf`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.blob();
};
export const exportPortfolio = (setores: string[], inicio: string, fim: string, modo: PlanningMode, ordens: OrdemTrabalho[]) =>
  download("/exportar", `carteira-${modo}-${inicio || "carteira-aberta"}.xlsx`, { setores, inicio: inicio || null, fim: fim || null, modo, ordens: ordens.map(orderKey) });
export const exportNfeReport = (jobId: string) =>
  download(`/exportar-nfe/${encodeURIComponent(jobId)}`, "Planejamento NFE.xlsx");
