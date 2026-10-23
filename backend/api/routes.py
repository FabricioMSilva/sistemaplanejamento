import json
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from models.database import (
    atualizar_sincronizacao,
    criar_sincronizacao,
    get_connection,
    listar_ordens_trabalho,
    listar_mao_de_obra,
    listar_especialidades,
    obter_ultima_sincronizacao,
    obter_sincronizacao,
    salvar_planejamento,
    obter_equipe,
    salvar_equipe,
    upsert_ordens_trabalho,
    listar_historico,
    equipe_padrao,
    conferencia_nf,
    salvar_vinculo_nf,
)
from services.BMAService import BMAConfigurationError, BMAService, BMAServiceError
from services.excel_service import InvalidSpreadsheetError, processar_planilha
from services.log_service import listar_logs, registrar_log
from services.labor_planning import PlanejamentoEquipe, calcular_equipe, calendario_turnos
from utils.validators import INVALID_FILE_MESSAGE

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


class CriarOtsPayload(BaseModel):
    arquivo_id: int
    indices: list[int] = Field(min_length=1)


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
        records = bma_service.listar_ots_por_setor(setores, progress=report)
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


@router.post("/processar")
async def processar(arquivo: UploadFile = File(...)):
    if not arquivo.filename:
        raise HTTPException(status_code=400, detail=INVALID_FILE_MESSAGE)

    try:
        conteudo = await arquivo.read()
        resultado = processar_planilha(arquivo.filename, conteudo)
        return resultado
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidSpreadsheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        registrar_log(f"Erro inesperado: {exc}", nivel="error", nome_arquivo=arquivo.filename)
        raise HTTPException(status_code=500, detail="Falha ao processar o arquivo.") from exc


@router.post("/criar-ots")
def criar_ots(payload: CriarOtsPayload):
    with get_connection() as conn:
        arquivo = conn.execute(
            """
            SELECT id, nome_arquivo, json_resultado
            FROM arquivos_processados
            WHERE id = ?
            """,
            (payload.arquivo_id,),
        ).fetchone()

    if not arquivo:
        raise HTTPException(status_code=404, detail="Arquivo processado não encontrado.")

    try:
        registros = json.loads(arquivo["json_resultado"] or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="JSON do arquivo processado está inválido.") from exc

    indices_invalidos = [index for index in payload.indices if index < 0 or index >= len(registros)]
    if indices_invalidos:
        raise HTTPException(status_code=400, detail="Uma ou mais linhas selecionadas são inválidas.")

    selecionados = [registros[index] for index in payload.indices]
    try:
        resultado = bma_service.criar_ot(selecionados)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mensagem = resultado.get(
        "mensagem",
        f"{len(selecionados)} OT(s) enviada(s) para criação.",
    )
    registrar_log(
        mensagem,
        nome_arquivo=arquivo["nome_arquivo"],
        quantidade_processada=len(selecionados),
    )
    return {
        "quantidade": len(selecionados),
        "indices": payload.indices,
        "status": resultado.get("status", "solicitado"),
        "mensagem": mensagem,
    }


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
