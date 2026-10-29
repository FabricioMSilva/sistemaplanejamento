export type DashboardData = {
  ultimo_arquivo: {
    nome_arquivo: string;
    data_upload: string;
    total_registros: number;
    registros_processados: number;
    registros_ignorados: number;
  } | null;
  total_registros_processados: number;
  total_pendente: number;
  status_sistema: string;
};

export type ProcessResult = {
  id: number;
  nome_arquivo: string;
  data_upload: string;
  total_registros: number;
  registros_processados: number;
  registros_ignorados: number;
  coluna_ot: string;
  coluna_status?: string | null;
  colunas_identificadas: string[];
  preview_colunas: string[];
  preview: Record<string, unknown>[];
  json: Record<string, unknown>[];
};

export type LogEntry = {
  id?: number;
  data_hora: string;
  nivel: string;
  mensagem: string;
  nome_arquivo?: string | null;
  quantidade_processada?: number | null;
};

export type OrdemTrabalho = {
  siteid: string;
  wonum: string;
  status: string;
  maintenanceshop: string;
  lead?: string | null;
  schedstart?: string | null;
  planning_status?: "Planejada" | "Parcial" | "Não planejada" | "Não verificada";
  dados: Record<string, unknown>;
  sincronizado_em: string;
};

export type MaoDeObra = {
  unidade: string;
  sincronizado_em: string | null;
  total: number;
  verificacao_nf?: { necessaria: boolean; verificada: boolean; sincronizado_em: string | null; pendentes: number };
  profissionais: {
    orgid: string;
    matricula: string;
    personid: string | null;
    nome: string;
    unidade: string;
    local_trabalho: string;
    setor: string;
    status: string;
    especialidades: {
      codigo: string;
      descricao: string | null;
      nivel: string | null;
      principal: boolean;
    }[];
  }[];
};

export async function listarMaoDeObra(setores: string[]): Promise<MaoDeObra> {
  const query = new URLSearchParams();
  setores.forEach((setor) => query.append("setor", setor));
  const response = await fetch(`${API_URL}/api/planejamento/mao-de-obra?${query}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export type ExecutantePlanejado = {
  orgid: string;
  matricula: string;
  funcao: string;
  jornada: "adm" | "08-16" | "16-00" | "00-08" | "equipe";
  equipe?: number | null;
  ajustes_datas?: Record<string, number>;
  inicio_ciclo: string | null;
  ajuste_horas: number;
  ausencias?: string[];
  capacidade?: "escala" | "dias_6h" | "dias_8h";
  dias_disponiveis?: string[] | null;
};

export type CalendarioTurnos = {
  ano: number;
  legenda: Record<string, string>;
  dias: Record<string, Record<string, { turno: string; marcacao: string | null }>>;
};

export async function obterCalendarioTurnos(): Promise<CalendarioTurnos> {
  const response = await fetch(`${API_URL}/api/planejamento/calendario-turnos`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export type PlanejamentoEquipe = {
  setores: string[];
  inicio: string;
  fim: string;
  executantes: ExecutantePlanejado[];
  planejador?: string;
};

export type HistoricoEquipe = { id: number; salvo_em: string; planejamento: PlanejamentoEquipe };
export type ConferenciaNf = {
  verificada: boolean; sincronizado_em: string | null;
  candidatos: MaoDeObra["profissionais"];
  vinculados: { id: number; nome: string; orgid: string; matricula_bma: string }[];
  pendentes: { id: number; nome: string; motivo: string }[];
};

async function workforceRequest<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${API_URL}/api/planejamento/${path}`, {
    method, headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}
const sectorQuery = (sectors: string[]) => new URLSearchParams(sectors.map((sector) => ["setor", sector])).toString();
export const atualizarMaoDeObra = (setores: string[]) =>
  workforceRequest<{ job_id: string }>("mao-de-obra/atualizar", "POST", { setores });
export const listarHistoricoEquipe = (setores: string[]) =>
  workforceRequest<HistoricoEquipe[]>(`historico?${sectorQuery(setores)}`);
export const obterEquipePadrao = (setores: string[], planejador: string) =>
  workforceRequest<PlanejamentoEquipe | null>(`equipe-padrao?${sectorQuery(setores)}&planejador=${encodeURIComponent(planejador)}`);
export const salvarEquipePadrao = (plan: PlanejamentoEquipe) =>
  workforceRequest<PlanejamentoEquipe>("equipe-padrao", "PUT", plan);
export const obterConferenciaNf = (setores: string[]) =>
  workforceRequest<ConferenciaNf>(`vinculos-nf?${sectorQuery(setores)}`);
export const salvarVinculoNf = (setores: string[], sharepoint_id: number, orgid: string, matricula: string) =>
  workforceRequest<ConferenciaNf>("vinculos-nf", "PUT", { setores, sharepoint_id, orgid, matricula });

export async function obterEquipe(setores: string[]): Promise<PlanejamentoEquipe | null> {
  const query = new URLSearchParams();
  setores.forEach((setor) => query.append("setor", setor));
  const response = await fetch(`${API_URL}/api/planejamento/equipe?${query}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function salvarEquipe(plan: PlanejamentoEquipe): Promise<void> {
  const response = await fetch(`${API_URL}/api/planejamento/equipe`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(plan),
  });
  if (!response.ok) throw new Error(await parseError(response));
}

export type SyncEvent = {
  nivel: string;
  etapa: string;
  mensagem: string;
  pagina: number | null;
  ots: number | null;
  data_hora: string;
};

export type SyncRun = {
  job_id: string;
  status: "queued" | "running" | "saving" | "completed" | "failed";
  etapa: string;
  mensagem: string;
  erro: string | null;
  setores: string[];
  pagina_atual: number;
  ots_lidas: number;
  ots_salvas: number;
  iniciada_em: string;
  atualizada_em: string;
  concluida_em: string | null;
  eventos: SyncEvent[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function parseError(response: Response): Promise<string> {
  try {
    const payload = await response.json();
    if (Array.isArray(payload.detail)) {
      return payload.detail.map((issue: { msg: string }) => issue.msg).join("; ");
    }
    return payload.detail || "Falha na comunicação com o servidor.";
  } catch {
    return "Falha na comunicação com o servidor.";
  }
}

export async function getDashboard(): Promise<DashboardData> {
  const response = await fetch(`${API_URL}/api/dashboard`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function getLogs(): Promise<LogEntry[]> {
  const response = await fetch(`${API_URL}/api/logs`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type CriarOtsResult = {
  quantidade: number;
  indices: number[];
  status: string;
  mensagem: string;
};

export async function processarArquivo(file: File): Promise<ProcessResult> {
  const formData = new FormData();
  formData.append("arquivo", file);
  const response = await fetch(`${API_URL}/api/processar`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function criarOts(arquivoId: number, indices: number[]): Promise<CriarOtsResult> {
  const response = await fetch(`${API_URL}/api/criar-ots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ arquivo_id: arquivoId, indices }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function sincronizarOrdensTrabalho(
  setores: string[],
): Promise<{ job_id: string }> {
  const response = await fetch(`${API_URL}/api/planejamento/sincronizar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ setores }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function obterSincronizacao(jobId: string): Promise<SyncRun> {
  const response = await fetch(`${API_URL}/api/planejamento/sincronizar/${encodeURIComponent(jobId)}`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function obterUltimaSincronizacao(): Promise<SyncRun | null> {
  const response = await fetch(`${API_URL}/api/planejamento/sincronizacao/ultima`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function listarOrdensTrabalho(setores: string[], statuses: string[] = []): Promise<OrdemTrabalho[]> {
  const query = new URLSearchParams();
  setores.forEach((setor) => query.append("setor", setor));
  statuses.forEach((status) => query.append("status", status));
  const response = await fetch(`${API_URL}/api/planejamento/ots?${query.toString()}`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}
