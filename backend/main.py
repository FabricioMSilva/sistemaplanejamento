import hmac
import os

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.routes import router
from api.pcm import router as pcm_router
from models.database import init_db

app = FastAPI(
    title="RoboMario",
    description="Processamento de planilhas de anomalias para criação de OT no BMA.",
    version="1.0.0",
)


@app.middleware("http")
async def protect_desktop_backend(request: Request, call_next):
    token = os.environ.get("BMA_DESKTOP_TOKEN", "")
    if token and not hmac.compare_digest(request.headers.get("x-planning-token", ""), token):
        return JSONResponse({"detail": "Acesso local nao autorizado."}, status_code=403)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(pcm_router, prefix="/api")


def authenticate_desktop_browser():
    import logging
    from services.BMAService import BMAService

    driver = None
    try:
        service = BMAService()
        driver = service._create_browser(headless=False)
        driver.get(service.wotrack_url)
        service._wait_for_work_tracking(driver)
    except Exception:
        logging.exception("Falha na autenticacao interativa BMA")
    finally:
        if driver:
            driver.quit()


@app.post("/api/desktop/authenticate", status_code=202)
def authenticate_desktop(background_tasks: BackgroundTasks):
    if os.getenv("BMA_DESKTOP") != "1":
        raise HTTPException(status_code=404)
    background_tasks.add_task(authenticate_desktop_browser)
    return {"status": "starting"}


@app.on_event("startup")
def startup():
    init_db()
