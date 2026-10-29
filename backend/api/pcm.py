from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from models.database import listar_situacao_envios_bma
from services import pcm_planning as pcm
from services.nfe_report import export_synced_report
from services.log_service import registrar_log
from services.BMAService import BMAServiceError
from services.bma_page_monitor import BmaPageMonitor

router = APIRouter(prefix="/pcm")
page_monitor = BmaPageMonitor()


class BmaPageMonitorRequest(BaseModel):
    orders: list["BmaOrderPlanRequest"] = Field(min_length=1, max_length=100)


class BmaPageSearchRequest(BaseModel):
    wonum: str = Field(min_length=1, max_length=32)


class BmaLaborAssignmentRequest(BaseModel):
    dia: str = Field(min_length=10, max_length=10)
    laborcode: str = Field(min_length=1, max_length=30)
    horas: float = Field(gt=0, le=24)


class BmaOrderPlanRequest(BaseModel):
    siteid: str = Field(min_length=1, max_length=16)
    wonum: str = Field(min_length=1, max_length=32)
    planned_start: str = Field(min_length=19, max_length=19)
    planned_finish: str = Field(min_length=19, max_length=19)
    specialty: str = Field(default="", max_length=30)
    assignments: list[BmaLaborAssignmentRequest] = Field(min_length=1, max_length=500)


def execute(operation, *args):
    try:
        return operation(*args)
    except pcm.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        registrar_log("WARNING", f"Planejamento PCM: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bma-page-monitor", status_code=202)
def start_bma_page_monitor(payload: BmaPageMonitorRequest):
    try:
        return page_monitor.start([order.dict() for order in payload.orders])
    except BMAServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/bma-page-monitor/search", status_code=202)
def start_bma_page_search(payload: BmaPageSearchRequest):
    try:
        return page_monitor.start_search(payload.wonum)
    except BMAServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bma-page-monitor/open-order", status_code=202)
def open_bma_page_order(payload: BmaPageSearchRequest):
    try:
        return page_monitor.start_open_order(payload.wonum)
    except BMAServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bma-page-monitor/abrir-ot", status_code=202)
def open_order_in_bma(payload: BmaPageSearchRequest):
    try:
        return page_monitor.abrir_ot_bma(payload.wonum)
    except BMAServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/planos/{plan_id}/envios-bma")
def bma_send_status(plan_id: str):
    return listar_situacao_envios_bma(plan_id)


@router.post("/bma-page-monitor/observar", status_code=202)
def observe_bma_page():
    return page_monitor.iniciar_observacao()


@router.post("/planos/{plan_id}/enviar-planejamento", status_code=202)
def send_planning_to_bma(plan_id: str):
    try:
        return page_monitor.enviar_planejamento(plan_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BMAServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/bma-page-monitor/{monitor_id}")
def get_bma_page_monitor(monitor_id: str):
    state = page_monitor.get(monitor_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Monitor BMA não encontrado.")
    return state


@router.delete("/bma-page-monitor/{monitor_id}")
def stop_bma_page_monitor(monitor_id: str):
    state = page_monitor.stop(monitor_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Monitor BMA não encontrado.")
    return state


@router.get("/planos")
def plans():
    return pcm.list_plans()


@router.post("/planos")
def create(payload: pcm.NewPlan):
    return execute(pcm.create_plan, payload.setores)


@router.post("/exportar")
def export(payload: pcm.ExportOrders):
    data = execute(pcm.spreadsheet, payload)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="carteira-{payload.modo}.xlsx"'})


@router.get("/planos/{plan_id}")
def get(plan_id: str):
    return execute(pcm.get_plan, plan_id)


@router.get("/exportar-nfe/{job_id}")
def export_nfe(job_id: str):
    data = execute(export_synced_report, job_id)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="Planejamento NFE.xlsx"'})


@router.put("/planos/{plan_id}")
def save(plan_id: str, payload: pcm.PlanChange):
    return execute(pcm.save_plan, plan_id, payload)


@router.put("/planos/{plan_id}/equipe")
def update_team(plan_id: str, payload: pcm.PlanTeamChange):
    return execute(pcm.update_plan_team, plan_id, payload)


@router.delete("/planos/{plan_id}")
def delete(plan_id: str):
    return execute(pcm.delete_plan, plan_id)


@router.post("/planos/{plan_id}/sugerir")
def suggest(plan_id: str, payload: pcm.Suggestion):
    return execute(pcm.suggest, execute(pcm.get_plan, plan_id), payload)


@router.post("/planos/{plan_id}/especialidades")
def refresh_specialties(plan_id: str, payload: pcm.PlanChange):
    return execute(pcm.refresh_labor, execute(pcm.get_plan, plan_id), payload)


@router.get("/planos/{plan_id}/revisoes")
def revisions(plan_id: str):
    return execute(pcm.revisions, plan_id)


@router.get("/planos/{plan_id}/revisoes/{revision}/pdf")
def pdf(plan_id: str, revision: int):
    data = execute(pcm.get_pdf, plan_id, revision)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="cronograma-{plan_id}-r{revision}.pdf"'})
