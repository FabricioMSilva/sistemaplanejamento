import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser


def user_data_dir():
    return Path(os.environ["LOCALAPPDATA"]) / "Michelin" / "PlanningScheduling"


def configure_logging(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / f"{name}.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def read_json(url, token=None, method="GET"):
    headers = {"x-planning-token": token} if token else {}
    request = urllib.request.Request(url, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=2) as response:
        return json.load(response)


def wait_ready(processes, url, token=None, timeout=90):
    deadline = time.monotonic() + timeout
    pause = threading.Event()
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("Um servico encerrou durante a inicializacao. Consulte os logs.")
        try:
            if read_json(url, token).get("status") == "online":
                return
        except (OSError, ValueError):
            pass
        pause.wait(0.25)
    raise RuntimeError("Os servicos nao responderam no prazo. Consulte os logs ou a TI.")


def desktop_environment(root, data, backend_port, frontend_port):
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(("BMA_", "NEXT_PUBLIC_")) or key in ("NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONHOME"):
            environment.pop(key, None)
    environment.update({
        "BMA_DESKTOP": "1", "BMA_DATA_DIR": str(data),
        "BMA_FIREFOX_PROFILE": str(data / "FirefoxProfile"),
        "BMA_FIREFOX_BINARY": str(root / "browser" / "firefox" / "firefox.exe"),
        "BMA_GECKODRIVER": str(root / "browser" / "geckodriver.exe"),
        "BMA_DESKTOP_TOKEN": secrets.token_urlsafe(32),
        "BMA_BACKEND_PORT": str(backend_port), "PORT": str(frontend_port),
        "HOSTNAME": "127.0.0.1", "NODE_ENV": "production", "NEXT_TELEMETRY_DISABLED": "1",
        "NO_PROXY": ",".join(filter(None, (environment.get("NO_PROXY", ""), "127.0.0.1,localhost,::1"))),
    })
    return environment


def validate_payload(root):
    required_files = (
        "runtime/node.exe", "frontend/server.js", "browser/firefox/firefox.exe",
        "browser/geckodriver.exe",
    )
    for relative in required_files:
        if not (root / relative).is_file():
            raise RuntimeError(f"Arquivo do aplicativo ausente: {relative}. Reinstale o Planning & Scheduling.")
    employee_reference = Path("database/data/funcionario.json")
    bundle_roots = (root, Path(getattr(sys, "_MEIPASS", root / "_internal")), root / "_internal")
    if not any((bundle_root / employee_reference).is_file() for bundle_root in bundle_roots):
        raise RuntimeError(
            f"Arquivo do aplicativo ausente: {employee_reference.as_posix()}. Reinstale o Planning & Scheduling."
        )


def run_backend():
    configure_logging(Path(os.environ["BMA_DATA_DIR"]) / "logs", "backend")
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=int(os.environ["BMA_BACKEND_PORT"]),
                log_config=None, access_log=False, workers=1)


def self_test(root, report):
    with tempfile.TemporaryDirectory(prefix="planning-self-test-") as temporary:
        data = Path(temporary)
        os.environ.update(desktop_environment(root, data, available_port(), available_port()))
        from models.database import DB_PATH, get_connection, init_db
        from services.BMAService import BMAService
        from services.nf_workforce import _load_ronda_reference
        from services.labor_planning import calendario_turnos
        from services.pcm_pdf import BRAND_IMAGE
        from services.pcm_pdf import render_schedule
        from reportlab.pdfgen.canvas import Canvas
        from io import BytesIO
        import pandas as pd

        init_db()
        with get_connection() as connection:
            assert connection.execute("SELECT COUNT(*) FROM pcm_planos").fetchone()[0] == 0
        assert DB_PATH.is_relative_to(data)
        assert _load_ronda_reference()
        assert calendario_turnos()["dias"]
        pdf = data / "check.pdf"
        canvas = Canvas(str(pdf))
        canvas.drawImage(str(BRAND_IMAGE), 10, 10, width=200, height=70, mask="auto")
        canvas.save()
        assert pdf.read_bytes().startswith(b"%PDF")
        schedule = render_schedule({
            "id": "distribution-self-test", "revisao": 1, "status": "rascunho",
            "inicio": "2026-11-02", "fim": "2026-11-03", "setores": [], "planejador": "Package validation",
            "atualizado_em": "2026-10-29T00:00:00Z", "motivo": "Temporary validation",
            "pessoas": [], "ordens": [], "requisitos": {}, "blocos": [], "indisponibilidades": [],
        })
        assert schedule.startswith(b"%PDF")
        spreadsheet = BytesIO()
        pd.DataFrame({"check": [1]}).to_excel(spreadsheet, index=False, engine="openpyxl")
        spreadsheet.seek(0)
        assert pd.read_excel(spreadsheet, engine="openpyxl").iloc[0, 0] == 1
        profile = data / "FirefoxProfile"
        profile.mkdir()
        (profile / "authenticated.marker").touch()
        browser = BMAService()._create_browser(headless=True)
        try:
            browser.get("data:text/html,<title>Planning distribution check</title>")
            assert browser.title == "Planning distribution check"
            browser_version = browser.capabilities["browserVersion"]
        finally:
            browser.quit()
        report.write_text(json.dumps({"ok": True, "sqlite": True, "catalogs": True,
                                      "pdf": True, "excel": True, "firefox": browser_version}), encoding="utf-8")


def smoke_test(url, backend_url, token, report):
    import urllib.error

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    assert read_json(f"{url}/api/desktop/api/pcm/planos") == []
    calendar = read_json(f"{url}/api/desktop/api/planejamento/calendario-turnos")
    assert calendar["dias"]
    with opener.open(f"{url}/planejamento/acompanhamento", timeout=15) as page:
        assert page.status == 200
        script_sources = re.findall(r'<script[^>]+src="(/_next/static/[^\"]+)"', page.read().decode("utf-8"))
    assert script_sources, "The desktop page did not reference Next.js scripts"
    for source in script_sources:
        with opener.open(f"{url}{source}", timeout=5) as script:
            assert script.status == 200 and script.headers.get_content_type() in ("application/javascript", "text/javascript")
    for request in (
        urllib.request.Request(f"{backend_url}/api/health"),
        urllib.request.Request(f"{url}/api/desktop/api/health", headers={"Origin": "https://untrusted.invalid"}),
    ):
        try:
            opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("An untrusted request reached a desktop service")
    report.write_text(json.dumps({"ok": True, "frontend": True, "backend": True,
                                  "proxy": True, "empty_database": True, "origin_protection": True}), encoding="utf-8")


def run_desktop(root, data, report=None):
    from win_shell import ProcessGroup, acquire_instance, alert, kernel, run_tray

    data.mkdir(parents=True, exist_ok=True)
    logs = data / "logs"
    configure_logging(logs, "launcher")
    mutex, first = None, True
    processes = []
    streams = []
    group = None
    state = data / "running.json"
    try:
        validate_payload(root)
        if report is None:
            mutex, first = acquire_instance()
        if not first:
            try:
                import re

                url = json.loads(state.read_text(encoding="utf-8"))["url"]
                if not re.fullmatch(r"http://127\.0\.0\.1:\d+", url):
                    raise ValueError("Invalid local URL")
                if read_json(f"{url}/api/desktop/api/health")["status"] == "online":
                    webbrowser.open(f"{url}/planejamento")
                    return
            except (OSError, ValueError, KeyError):
                alert("O Planning & Scheduling ja esta iniciando. Aguarde alguns instantes.")
                return
        backend_port = available_port()
        frontend_port = available_port()
        while frontend_port == backend_port:
            frontend_port = available_port()
        environment = desktop_environment(root, data, backend_port, frontend_port)
        url = f"http://127.0.0.1:{frontend_port}"
        backend_url = f"http://127.0.0.1:{backend_port}"
        group = ProcessGroup()
        commands = ([str(root / "PlanningScheduling.exe"), "--backend"],
                    [str(root / "runtime" / "node.exe"), str(root / "frontend" / "server.js")])
        for name, command in zip(("backend-process", "frontend"), commands):
            log_path = logs / f"{name}.log"
            if log_path.exists() and log_path.stat().st_size > 5_000_000:
                log_path.replace(log_path.with_suffix(".previous.log"))
            stream = log_path.open("ab")
            streams.append(stream)
            process = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=stream, creationflags=subprocess.CREATE_NO_WINDOW)
            processes.append(process)
            group.add(process)
        wait_ready(processes, f"{backend_url}/api/health", environment["BMA_DESKTOP_TOKEN"])
        wait_ready(processes, f"{url}/api/desktop/api/health")
        if report:
            smoke_test(url, backend_url, environment["BMA_DESKTOP_TOKEN"], report)
            return
        state.write_text(json.dumps({"url": url}), encoding="utf-8")
        open_app = lambda: webbrowser.open(f"{url}/planejamento")

        def authenticate():
            try:
                read_json(f"{backend_url}/api/desktop/authenticate", environment["BMA_DESKTOP_TOKEN"], "POST")
            except (OSError, ValueError):
                logging.exception("Nao foi possivel iniciar a autenticacao BMA")
                alert("Nao foi possivel abrir o BMA. Consulte os logs ou aguarde a operacao atual.")

        open_app()
        run_tray(root / "PlanningScheduling.exe", open_app, authenticate,
                 lambda: os.startfile(str(logs)), lambda: all(process.poll() is None for process in processes))
    finally:
        if group:
            group.close()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for stream in streams:
            stream.close()
        if first:
            state.unlink(missing_ok=True)
        if mutex:
            kernel.CloseHandle(mutex)
        logging.shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    root = Path(sys.executable).resolve().parent
    try:
        if arguments.backend:
            run_backend()
        elif arguments.self_test or arguments.smoke_test:
            if arguments.report is None:
                raise ValueError("Validation requires --report")
            if arguments.self_test:
                self_test(root, arguments.report)
            else:
                with tempfile.TemporaryDirectory(prefix="planning-smoke-") as temporary:
                    run_desktop(root, Path(temporary), arguments.report)
        else:
            run_desktop(root, user_data_dir())
    except Exception as error:
        logging.exception("Falha na execucao do aplicativo")
        if arguments.report:
            arguments.report.write_text(json.dumps({"ok": False, "error": str(error)}), encoding="utf-8")
        elif not arguments.backend:
            from win_shell import alert

            alert(f"Nao foi possivel iniciar o Planning & Scheduling.\n\n{error}\n\nLogs: {user_data_dir() / 'logs'}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())