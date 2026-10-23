from fastapi import APIRouter, HTTPException, Response

from services import pcm_planning as pcm
from services.nfe_report import export_synced_report
from services.log_service import registrar_log

router = APIRouter(prefix="/pcm")


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
