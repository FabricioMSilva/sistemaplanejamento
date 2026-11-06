import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from unittest.mock import AsyncMock
import asyncio


spec = importlib.util.spec_from_file_location(
    "desktop_launcher", Path(__file__).resolve().parents[2] / "distribution" / "windows" / "launcher.py",
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class DesktopLauncherTests(unittest.TestCase):
    def test_environment_uses_only_packaged_browser_and_user_data(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(os.environ, {"BMA_FIREFOX_BINARY": "personal-firefox", "BMA_WOTRACK_URL": "personal-url",
                                     "BMA_DESKTOP_TOKEN": "developer-token", "NODE_OPTIONS": "--inspect"}):
            root = Path(temporary) / "installed"
            data = Path(temporary) / "user-data"
            environment = launcher.desktop_environment(root, data, 18101, 18102)
            self.assertEqual(environment["BMA_FIREFOX_BINARY"], str(root / "browser" / "firefox" / "firefox.exe"))
            self.assertEqual(environment["BMA_FIREFOX_PROFILE"], str(data / "FirefoxProfile"))
            self.assertEqual(environment["HOSTNAME"], "127.0.0.1")
            self.assertNotEqual(environment["BMA_DESKTOP_TOKEN"], "developer-token")
            self.assertNotIn("BMA_WOTRACK_URL", environment)
            self.assertNotIn("NODE_OPTIONS", environment)
            self.assertNotEqual(environment["BMA_DESKTOP_TOKEN"], launcher.desktop_environment(root, data, 1, 2)["BMA_DESKTOP_TOKEN"])

    def test_missing_payload_fails_without_starting_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, "runtime/node.exe"):
                launcher.validate_payload(Path(temporary))

    def test_payload_requires_employee_reference_roster(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                "runtime/node.exe", "frontend/server.js", "browser/firefox/firefox.exe",
                "browser/geckodriver.exe",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            with self.assertRaisesRegex(RuntimeError, "database/data/funcionario.json"):
                launcher.validate_payload(root)

    def test_payload_accepts_employee_reference_in_pyinstaller_internal_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in (
                "runtime/node.exe", "frontend/server.js", "browser/firefox/firefox.exe",
                "browser/geckodriver.exe",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            bundle = root / "_internal"
            reference = bundle / "database/data/funcionario.json"
            reference.parent.mkdir(parents=True)
            reference.touch()

            launcher.validate_payload(root)

    def test_preflight_failure_closes_temporary_launcher_log(self):
        directory = str(Path(__file__).resolve().parents[2] / "distribution" / "windows")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "payload"
            root.mkdir()
            data = Path(temporary) / "smoke"
            with patch.object(sys, "path", [directory, *sys.path]):
                with self.assertRaisesRegex(RuntimeError, "runtime/node.exe"):
                    launcher.run_desktop(root, data, Path(temporary) / "report.json")
            shutil.rmtree(data)

    def test_ready_check_requires_the_actual_backend_response(self):
        with patch.object(launcher, "read_json", return_value={"status": "online"}) as read:
            launcher.wait_ready([Mock(poll=Mock(return_value=None))], "http://127.0.0.1:18101/api/health", "nonce")
            read.assert_called_once_with("http://127.0.0.1:18101/api/health", "nonce")

    def test_ready_check_stops_when_a_child_crashes(self):
        with self.assertRaisesRegex(RuntimeError, "encerrou"):
            launcher.wait_ready([Mock(poll=Mock(return_value=1))], "http://127.0.0.1:18101/api/health")

    def test_native_job_and_mutex_can_be_created(self):
        import sys

        directory = str(Path(__file__).resolve().parents[2] / "distribution" / "windows")
        with patch.object(sys, "path", [directory, *sys.path]):
            from win_shell import ProcessGroup, acquire_instance, kernel

            group = ProcessGroup()
            group.close()
            handle, first = acquire_instance()
            second_handle, second = acquire_instance()
            try:
                self.assertTrue(first)
                self.assertFalse(second)
            finally:
                kernel.CloseHandle(second_handle)
                kernel.CloseHandle(handle)

    def test_installed_backend_requires_its_private_launcher_token(self):
        from main import protect_desktop_backend
        from starlette.requests import Request

        async def verify():
            next_handler = AsyncMock(return_value="allowed")
            with patch.dict(os.environ, {"BMA_DESKTOP_TOKEN": "private-nonce"}):
                denied = await protect_desktop_backend(Request({"type": "http", "headers": []}), next_handler)
                self.assertEqual(denied.status_code, 403)
                next_handler.assert_not_called()
                request = Request({"type": "http", "headers": [(b"x-planning-token", b"private-nonce")]})
                self.assertEqual(await protect_desktop_backend(request, next_handler), "allowed")
            with patch.dict(os.environ, {"BMA_DESKTOP_TOKEN": ""}):
                self.assertEqual(await protect_desktop_backend(Request({"type": "http", "headers": []}), next_handler), "allowed")

        asyncio.run(verify())


if __name__ == "__main__":
    unittest.main()