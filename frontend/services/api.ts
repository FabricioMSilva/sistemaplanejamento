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

export type LogEntry = {
  id?: number;
  data_hora: string;
  nivel: string;
  mensagem: string;
  nome_arquivo?: string | null;
  quantidade_processada?: number | null;
};

export type OtHistoryType = "todas" | "criadas" | "planejadas" | "alteradas";
export type OtHistoryItem = {
  id: string;
  siteid: string;
  wonum: string;
  acao: string;
  situacao: string;
  status: string;
  registrado_em: string;
  origem: string;
  resumo: string;
  detalhes: Record<string, unknown>;
};

export type OrdemTrabalho = {
  siteid: string;
  wonum: string;
  status: string;
  maintenanceshop: string;
  lead?: string | null;
  schedstart?: string | null;
  planejamento_bma_importado?: boolean;
  planejamento_adicionado?: boolean;
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
  const response = await apiFetch(`${API_URL}/api/planejamento/mao-de-obra?${query}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export type Especialidade = { orgid: string; codigo: string; descricao: string };

export async function listarEspecialidades(orgid: string): Promise<Especialidade[]> {
  const query = new URLSearchParams({ orgid });
  const response = await apiFetch(`${API_URL}/api/planejamento/especialidades?${query}`);
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
  const response = await apiFetch(`${API_URL}/api/planejamento/calendario-turnos`);
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
export type EquipeSalva = { nome: string; salvo_em: string; planejamento: PlanejamentoEquipe };
export type ConferenciaNf = {
  verificada: boolean; sincronizado_em: string | null;
  candidatos: MaoDeObra["profissionais"];
  vinculados: { id: number; nome: string; orgid: string; matricula_bma: string }[];
  pendentes: { id: number; nome: string; motivo: string }[];
};

async function workforceRequest<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await apiFetch(`${API_URL}/api/planejamento/${path}`, {
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
export const listarEquipesSalvas = (setores: string[]) =>
  workforceRequest<EquipeSalva[]>(`equipes-salvas?${sectorQuery(setores)}`);
export const salvarEquipeNomeada = (nome: string, planejamento: PlanejamentoEquipe, persistirAtual = true) =>
  workforceRequest<EquipeSalva>("equipes-salvas", "PUT", { nome, planejamento, persistir_atual: persistirAtual });
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
  const response = await apiFetch(`${API_URL}/api/planejamento/equipe?${query}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function salvarEquipe(plan: PlanejamentoEquipe): Promise<void> {
  const response = await apiFetch(`${API_URL}/api/planejamento/equipe`, {
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

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (error) {
    if (init?.signal?.aborted) throw error;
    const requestUrl = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    let target = "o endereço configurado";
    try {
      target = new URL(requestUrl, typeof window === "undefined" ? "http://localhost" : window.location.href).origin;
    } catch {
      // Keep the generic target when the request URL cannot be parsed.
    }
    throw new Error(
      `Não foi possível conectar à API local em ${target}. Verifique se o serviço está iniciado e tente novamente.`,
    );
  }
}

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
  const response = await apiFetch(`${API_URL}/api/dashboard`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function getLogs(): Promise<LogEntry[]> {
  const response = await apiFetch(`${API_URL}/api/logs`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function getOtHistory(busca = "", tipo: OtHistoryType = "todas"): Promise<OtHistoryItem[]> {
  const query = new URLSearchParams({ busca, tipo });
  const response = await apiFetch(`${API_URL}/api/historico-ots?${query.toString()}`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function sincronizarOrdensTrabalho(
  setores: string[],
): Promise<{ job_id: string }> {
  const response = await apiFetch(`${API_URL}/api/planejamento/sincronizar`, {
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
  const response = await apiFetch(`${API_URL}/api/planejamento/sincronizar/${encodeURIComponent(jobId)}`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function obterUltimaSincronizacao(): Promise<SyncRun | null> {
  const response = await apiFetch(`${API_URL}/api/planejamento/sincronizacao/ultima`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function listarOrdensTrabalho(setores: string[], statuses: string[] = []): Promise<OrdemTrabalho[]> {
  const query = new URLSearchParams();
  setores.forEach((setor) => query.append("setor", setor));
  statuses.forEach((status) => query.append("status", status));
  const response = await apiFetch(`${API_URL}/api/planejamento/ots?${query.toString()}`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}
