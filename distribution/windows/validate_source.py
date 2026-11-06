import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from launcher import available_port, desktop_environment, smoke_test, wait_ready
from win_shell import ProcessGroup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", default=shutil.which("node"))
    arguments = parser.parse_args()
    if not arguments.node:
        parser.error("Pass --node with the approved Node.js executable")
    root = Path(__file__).resolve().parents[2]
    build = root / "build" / "windows"
    build.mkdir(parents=True, exist_ok=True)
    report = build / "source-runtime-validation.json"
    frontend = build / "payload" / "frontend" / "server.js"
    if not frontend.is_file():
        parser.error("Build the standalone frontend first with build_frontend.cjs")
    processes = []
    group = ProcessGroup()
    try:
        with tempfile.TemporaryDirectory(prefix="planning-source-validation-") as temporary, \
             (build / "source-backend.log").open("wb") as backend_log, \
             (build / "source-frontend.log").open("wb") as frontend_log:
            data = Path(temporary)
            backend_port = available_port()
            frontend_port = available_port()
            while frontend_port == backend_port:
                frontend_port = available_port()
            environment = desktop_environment(root, data, backend_port, frontend_port)
            try:
                commands = (
                    ([sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(root / "backend"),
                      "--host", "127.0.0.1", "--port", str(backend_port)], backend_log),
                    ([arguments.node, str(frontend)], frontend_log),
                )
                for command, output in commands:
                    process = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                               stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
                    processes.append(process)
                    group.add(process)
                backend_url = f"http://127.0.0.1:{backend_port}"
                url = f"http://127.0.0.1:{frontend_port}"
                wait_ready(processes, f"{backend_url}/api/health", environment["BMA_DESKTOP_TOKEN"])
                wait_ready(processes, f"{url}/api/desktop/api/health")
                smoke_test(url, backend_url, environment["BMA_DESKTOP_TOKEN"], report)
                result = json.loads(report.read_text(encoding="utf-8"))
                result["kind"] = "source-backend+standalone-frontend"
                report.write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(report.read_text(encoding="utf-8"))
            finally:
                group.close()
                for process in processes:
                    process.wait(timeout=15)
    except Exception as error:
        report.write_text(json.dumps({"ok": False, "error": str(error)}), encoding="utf-8")
        raise
    finally:
        group.close()


if __name__ == "__main__":
    main()