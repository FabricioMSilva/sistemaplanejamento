import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from utils.runtime_paths import data_root, resource_root, uploads_dir


class RuntimePathTests(unittest.TestCase):
    def test_development_keeps_repository_paths(self):
        with patch.dict(os.environ, {"BMA_DATA_DIR": ""}):
            self.assertEqual(resource_root(), Path(__file__).resolve().parents[2])
            self.assertEqual(data_root(), resource_root())
            self.assertEqual(uploads_dir(), resource_root() / "backend" / "uploads")

    def test_installed_data_is_separate_from_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "readonly-bundle"
            data = Path(temporary) / "user-data"
            with patch.object(sys, "_MEIPASS", str(bundle), create=True), \
                 patch.dict(os.environ, {"BMA_DATA_DIR": str(data)}):
                self.assertEqual(resource_root(), bundle)
                self.assertEqual(data_root(), data)
                self.assertEqual(uploads_dir(), data / "backend" / "uploads")

    def test_installed_firefox_uses_bundled_driver_and_fresh_user_profile(self):
        from services.BMAService import BMAService

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            firefox = root / "firefox.exe"
            gecko = root / "geckodriver.exe"
            firefox.touch()
            gecko.touch()
            profile = root / "new-user-profile"
            environment = {"BMA_DESKTOP": "1", "BMA_FIREFOX_BINARY": str(firefox),
                           "BMA_GECKODRIVER": str(gecko), "BMA_FIREFOX_PROFILE": str(profile)}
            with patch.dict(os.environ, environment), \
                 patch("services.BMAService._InstalledFirefox") as browser, \
                 patch("services.BMAService._installed_profile_lock", Mock()) as lock:
                BMAService()._create_browser(headless=True)
                options = browser.call_args.kwargs["options"]
                self.assertEqual(options.binary_location, str(firefox))
                self.assertIn(str(profile), options.arguments)
                self.assertNotIn("-headless", options.arguments)
                trusted_uris = options.preferences["network.negotiate-auth.trusted-uris"]
                self.assertIn("michelingroup.sharepoint.com", trusted_uris)
                self.assertIn("login-fed.michelin.com", trusted_uris)
                self.assertEqual(browser.call_args.kwargs["service"].path, str(gecko))
                lock.acquire.assert_called_once_with(blocking=False)
                self.assertFalse((profile / "cookies.sqlite").exists())

    def test_installed_browser_never_falls_back_to_downloads(self):
        from services.BMAService import BMAService, BMAConfigurationError

        with tempfile.TemporaryDirectory() as temporary, \
             patch.dict(os.environ, {"BMA_DESKTOP": "1", "BMA_FIREFOX_BINARY": "",
                                     "BMA_GECKODRIVER": "", "BMA_FIREFOX_PROFILE": temporary}), \
             patch("services.BMAService.webdriver.Firefox") as browser:
            with self.assertRaises(BMAConfigurationError):
                BMAService()._create_browser()
            browser.assert_not_called()

    def test_closed_installed_firefox_does_not_permanently_lock_the_profile(self):
        from services.BMAService import BMAService

        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "bundled.exe"
            binary.touch()
            previous = Mock(window_handles=[])
            with patch.dict(os.environ, {"BMA_DESKTOP": "1", "BMA_FIREFOX_BINARY": str(binary),
                                         "BMA_GECKODRIVER": str(binary), "BMA_FIREFOX_PROFILE": temporary}), \
                 patch("services.BMAService._InstalledFirefox") as browser, \
                 patch("services.BMAService._installed_profile_lock") as lock:
                browser.active = previous
                lock.acquire.side_effect = [False, True]
                BMAService()._create_browser()
                previous.quit.assert_called_once_with()
                browser.assert_called_once()


if __name__ == "__main__":
    unittest.main()