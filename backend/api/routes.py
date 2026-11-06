from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from models.database import (
    atualizar_sincronizacao,
    criar_sincronizacao,
    get_connection,
    listar_ordens_trabalho,
    listar_alteracoes_ordens_trabalho,
    listar_historico_ots,
    listar_mao_de_obra,
    listar_especialidades,
    obter_ultima_sincronizacao,
    obter_sincronizacao,
    salvar_planejamento,
    obter_equipe,
    salvar_equipe,
    upsert_ordens_trabalho,
    listar_historico,
    listar_equipes_salvas,
    equipe_padrao,
    conferencia_nf,
    salvar_vinculo_nf,
    salvar_equipe_nomeada,
)
from services.BMAService import BMAConfigurationError, BMAService, BMAServiceError
from services.log_service import listar_logs, registrar_log
from services.labor_planning import PlanejamentoEquipe, calcular_equipe, calendario_turnos

router = APIRouter()
bma_service = BMAService()
labor_refresh_lock = Lock()


@router.get("/planejamento/calendario-turnos")
def obter_calendario_turnos():
    return calendario_turnos()


@router.get("/planejamento/equipe")
def carregar_equipe(setor: list[str] = Query(min_length=1, max_length=28)):
    return obter_equipe(setor)


@router.put("/planejamento/equipe")
def gravar_equipe(payload: PlanejamentoEquipe):
    try:
        if not payload.planejador.strip():
            raise ValueError("Informe o nome/matrícula do planejador.")
        summary = calcular_equipe(payload, listar_mao_de_obra(payload.setores))
        data = payload.model_dump(mode="json")
        salvar_equipe(data)
        return {"planejamento": data, "resumo": summary}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/planejamento/historico")
def historico_equipes(setor: list[str] = Query(min_length=1, max_length=28)):
    return listar_historico(setor)


@router.get("/planejamento/equipes-salvas")
def equipes_salvas(setor: list[str] = Query(min_length=1, max_length=28)):
    return listar_equipes_salvas(setor)


class EquipeNomeadaPayload(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    planejamento: PlanejamentoEquipe
    persistir_atual: bool = True


@router.put("/planejamento/equipes-salvas")
def gravar_equipe_nomeada(payload: EquipeNomeadaPayload):
    try:
        if not payload.planejamento.planejador.strip():
            raise ValueError("Informe o nome/matrícula do planejador.")
        calcular_equipe(payload.planejamento, listar_mao_de_obra(payload.planejamento.setores))
        data = payload.planejamento.model_dump(mode="json")
        return salvar_equipe_nomeada(data, payload.nome, persistir_atual=payload.persistir_atual)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/planejamento/equipe-padrao")
def carregar_padrao(planejador: str = Query(min_length=1, max_length=120),
                    setor: list[str] = Query(min_length=1, max_length=28)):
    try:
        return equipe_padrao(setor, planejador)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/planejamento/equipe-padrao")
def gravar_padrao(payload: PlanejamentoEquipe):
    try:
        calcular_equipe(payload, listar_mao_de_obra(payload.setores))
        data = payload.model_dump(mode="json")
        for member in data["executantes"]:
            member.update(ausencias=[], ajustes_datas={}, ajuste_horas=0)
            if member.get("capacidade") in ("dias_6h", "dias_8h"):
                member["dias_disponiveis"] = None
        return equipe_padrao(payload.setores, payload.planejador, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/planejamento/vinculos-nf")
def carregar_vinculos_nf(setor: list[str] = Query(min_length=1, max_length=28)):
    return conferencia_nf(setor)


class VinculoNfPayload(BaseModel):
    setores: list[str] = Field(min_length=1, max_length=28)
    sharepoint_id: int = Field(gt=0)
    orgid: str = Field(min_length=1)
    matricula: str = Field(min_length=1)


@router.put("/planejamento/vinculos-nf")
def gravar_vinculo_nf(payload: VinculoNfPayload):
    try:
        salvar_vinculo_nf(payload.setores, payload.sharepoint_id, payload.orgid, payload.matricula)
        return conferencia_nf(payload.setores)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SincronizarOtsPayload(BaseModel):
    setores: list[str] = Field(min_length=1, max_length=28)


def _executar_sincronizacao(job_id: str, setores: list[str]) -> None:
    def report(stage: str, message: str, page: int | None, orders: int | None) -> None:
        atualizar_sincronizacao(
            job_id,
            status="running",
            etapa=stage,
            mensagem=message,
            pagina=page,
            ots=orders,
        )

    try:
        existing_orders = listar_ordens_trabalho(setores)
        records = bma_service.listar_ots_por_setor(
            setores, progress=report, existing_orders=existing_orders,
        )
        atualizar_sincronizacao(
            job_id,
            status="saving",
            etapa="sqlite",
            mensagem=f"Gravando {len(records)} OT(s) no SQLite. A mão de obra é atualizada somente no modal.",
            ots=len(records),
        )
        saved = upsert_ordens_trabalho(records, setores)
    except Exception as exc:
        message = str(exc) or "Falha não identificada durante a sincronização."
        atualizar_sincronizacao(
            job_id,
            status="failed",
            etapa="erro",
            mensagem=message,
            nivel="error",
            erro=f"{type(exc).__name__}: {message}",
        )
        registrar_log(f"Falha na sincronização BMA: {type(exc).__name__}: {message}", nivel="error")
        return

    message = (
        f"Sincronização concluída: {saved} OT(s) de {len(setores)} setor(es)."
    )
    atualizar_sincronizacao(
        job_id,
        status="completed",
        etapa="concluido",
        mensagem=message,
        ots=len(records),
        ots_salvas=saved,
    )
    registrar_log(message, quantidade_processada=saved)


def _executar_atualizacao_mao_de_obra(job_id: str, setores: list[str]) -> None:
    def report(stage, message, page, orders):
        atualizar_sincronizacao(job_id, status="running", etapa=stage, mensagem=message)
    try:
        labor, roster = bma_service.atualizar_mao_de_obra(
            "RES-TC-NF" in {s.upper() for s in setores}, progress=report,
        )
        salvar_planejamento([], setores, labor, roster=roster)
        message = f"Cadastro BMA atualizado: {len(labor)} profissionais. "
        if roster is not None:
            result = conferencia_nf(setores)
            message += f"NF: {len(result['vinculados'])} vínculos confirmados; {len(result['pendentes'])} para conferir."
        atualizar_sincronizacao(job_id, status="completed", etapa="concluido", mensagem=message)
        registrar_log(message)
    except Exception as exc:
        message = f"Falha ao atualizar mão de obra: {exc}. O snapshot anterior foi preservado se a coleta falhou."
        atualizar_sincronizacao(job_id, status="failed", etapa="erro", mensagem=message,
                               erro=f"{type(exc).__name__}: {exc}", nivel="error")
        registrar_log(message, nivel="error")
    finally:
        labor_refresh_lock.release()


@router.post("/planejamento/mao-de-obra/atualizar", status_code=202)
def atualizar_mao_de_obra(payload: SincronizarOtsPayload, background_tasks: BackgroundTasks):
    if any(not s or not all(c.isalnum() or c == "-" for c in s) for s in payload.setores):
        raise HTTPException(status_code=400, detail="Setor inválido.")
    if not labor_refresh_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Já existe uma atualização de mão de obra em andamento.")
    job_id = uuid4().hex
    try:
        criar_sincronizacao(job_id, payload.setores, tipo="mao_de_obra")
        background_tasks.add_task(_executar_atualizacao_mao_de_obra, job_id, payload.setores)
    except Exception:
        labor_refresh_lock.release()
        raise
    return {"job_id": job_id}


@router.get("/health")
def health():
    return {"status": "online", "sistema": "RoboMario"}


@router.post("/planejamento/sincronizar", status_code=202)
def sincronizar_ordens_trabalho(
    payload: SincronizarOtsPayload,
    background_tasks: BackgroundTasks,
):
    job_id = uuid4().hex
    criar_sincronizacao(job_id, payload.setores)
    background_tasks.add_task(_executar_sincronizacao, job_id, payload.setores)
    return {"job_id": job_id}


@router.get("/planejamento/sincronizar/{job_id}")
def obter_progresso_sincronizacao(job_id: str):
    sync = obter_sincronizacao(job_id)
    if sync is None:
        raise HTTPException(status_code=404, detail="Sincronização não encontrada.")
    return sync


@router.get("/planejamento/sincronizacao/ultima")
def obter_ultima_execucao_sincronizacao():
    return obter_ultima_sincronizacao()


@router.get("/planejamento/ots")
def listar_ots_planejamento(
    setor: list[str] = Query(min_length=1, max_length=28),
    status: list[str] | None = Query(default=None),
):
    return listar_ordens_trabalho(setor, status)


@router.get("/planejamento/ots/alteracoes")
def listar_alteracoes_ots_planejamento(
    setor: list[str] = Query(min_length=1, max_length=28),
    limit: int = Query(default=100, ge=1, le=500),
):
    return listar_alteracoes_ordens_trabalho(setor, limit)


@router.get("/dashboard")
def dashboard():
    with get_connection() as conn:
        ultimo = conn.execute(
            """
            SELECT nome_arquivo, data_upload, total_registros, registros_processados, registros_ignorados
            FROM arquivos_processados
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        totais = conn.execute(
            """
            SELECT
                COALESCE(SUM(registros_processados), 0) AS total_processados,
                COALESCE(SUM(CASE WHEN id = (SELECT MAX(id) FROM arquivos_processados) THEN registros_processados ELSE 0 END), 0) AS total_pendente
            FROM arquivos_processados
            """
        ).fetchone()

    return {
        "ultimo_arquivo": dict(ultimo) if ultimo else None,
        "total_registros_processados": int(totais["total_processados"] if totais else 0),
        "total_pendente": int(totais["total_pendente"] if totais else 0),
        "status_sistema": "online",
    }


@router.get("/planejamento/mao-de-obra")
def obter_mao_de_obra(setor: list[str] = Query(min_length=1, max_length=28)):
    return listar_mao_de_obra(setor)


@router.get("/planejamento/especialidades")
def obter_especialidades(orgid: str = "BR"):
    return listar_especialidades(orgid)


@router.get("/historico")
def historico():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, nome_arquivo, data_upload, total_registros, registros_processados, registros_ignorados, status
            FROM arquivos_processados
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/logs")
def logs():
    return listar_logs()


@router.get("/historico-ots")
def historico_ots(
    busca: str = Query(default="", max_length=120),
    tipo: str = Query(default="todas", max_length=20),
    limite: int = Query(default=500, ge=1, le=500),
):
    return listar_historico_ots(busca, tipo, limite)
