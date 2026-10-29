import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.keys import Keys
from api.pcm import (
    BmaOrderPlanRequest, BmaPageMonitorRequest, BmaPageSearchRequest,
)
from services.BMAService import BMAService, BMAServiceError
from services.bma_page_monitor import BmaPageMonitor, WOTRACK_URL


def planned_order(wonum):
    return {
        "siteid": "RES",
        "wonum": wonum,
        "planned_start": "2026-11-03T00:01:00",
        "planned_finish": "2026-11-03T23:59:00",
        "specialty": "180",
        "assignments": [{"dia": "2026-11-03", "laborcode": "E062942", "horas": 4}],
    }


class BmaPageMonitorTests(unittest.TestCase):
    def test_read_only_search_submits_number_without_opening_or_editing_order(self):
        monitor = BmaPageMonitor()
        with patch("services.bma_page_monitor.Thread") as thread:
            result = monitor.start_search("RES6707859")

        monitor_id = result["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        driver_service = Mock(timeout=30)
        driver_service._create_browser.return_value = driver
        order_filter = Mock()
        order_filter.send_keys.side_effect = lambda *args: session["stop"].set()
        fields = [{"tag": "input", "id": "quicksearch", "label": "Find Ordem de Trabalho"}]

        with patch("services.bma_page_monitor.BMAService", return_value=driver_service), \
             patch.object(monitor, "_visible_fields", return_value=fields), \
             patch.object(monitor, "_find_order_filter", return_value=order_filter), \
             patch.object(monitor, "_find_order_link") as find_order_link, \
             patch.object(monitor, "_process_order_queue") as process_order_queue, \
             patch("services.bma_page_monitor.sleep"):
            monitor._run_search_only(monitor_id, "RES6707859")

        self.assertEqual(thread.call_args.kwargs["target"], monitor._run_search_only)
        self.assertEqual(thread.call_args.kwargs["args"], (monitor_id, "RES6707859"))
        self.assertEqual(
            [call.args for call in order_filter.send_keys.call_args_list],
            [(Keys.CONTROL, "a"), ("RES6707859", Keys.ENTER)],
        )
        driver_service.clear_browser_cache_and_history.assert_not_called()
        find_order_link.assert_not_called()
        process_order_queue.assert_not_called()
        self.assertTrue(monitor.get(monitor_id)["inspection_only"])
        self.assertEqual(monitor.get(monitor_id)["mode"], "search_only")
        driver.quit.assert_called_once_with()

    def test_read_only_search_rejects_invalid_order_number(self):
        with self.assertRaises(BMAServiceError):
            BmaPageMonitor().start_search("RES 6707859")

    def test_open_order_starts_dedicated_read_only_worker(self):
        monitor = BmaPageMonitor()
        with patch("services.bma_page_monitor.Thread") as thread:
            result = monitor.start_open_order("res6707859")

        state = monitor.get(result["monitor_id"])
        self.assertEqual(state["mode"], "open_order")
        self.assertTrue(state["inspection_only"])
        self.assertEqual(state["selected_wonums"], ["RES6707859"])
        self.assertEqual(thread.call_args.kwargs["target"], monitor._run_open_order_only)

    def test_open_order_opens_result_without_processing_or_saving(self):
        monitor = BmaPageMonitor()
        with patch("services.bma_page_monitor.Thread"):
            monitor_id = monitor.start_open_order("RES6707859")["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        service = Mock(timeout=30)
        service._create_browser.return_value = driver
        order_filter = Mock()

        def open_order(*_args):
            session["stop"].set()

        with (
            patch("services.bma_page_monitor.BMAService", return_value=service),
            patch.object(monitor, "_visible_fields", return_value=[{"tag": "input", "id": "quicksearch"}]),
            patch.object(monitor, "_find_order_filter", return_value=order_filter),
            patch.object(monitor, "_open_order_result_in_maximo", side_effect=open_order) as open_result,
            patch.object(monitor, "_process_order_queue") as process_queue,
            patch("services.bma_page_monitor.sleep"),
        ):
            monitor._run_open_order_only(monitor_id, "RES6707859")

        open_result.assert_called_once_with(monitor_id, driver, "RES6707859")
        process_queue.assert_not_called()
        self.assertEqual(monitor.get(monitor_id)["progress"], 100)
        self.assertEqual(monitor.get(monitor_id)["opened_wonum"], "RES6707859")
        driver.quit.assert_called_once_with()

    def test_browser_cache_cleanup_removes_history_cookies_and_site_storage(self):
        with tempfile.TemporaryDirectory() as local_app_data:
            profile = Path(local_app_data) / "BMA_Automacao" / "FirefoxProfile"
            for directory in ("cache2", "startupCache", "thumbnails", "storage", "sessionstore-backups"):
                (profile / directory).mkdir(parents=True)
            for filename in (
                "places.sqlite", "places.sqlite-shm", "places.sqlite-wal",
                "cookies.sqlite", "cookies.sqlite-shm", "cookies.sqlite-wal",
                "storage.sqlite", "webappsstore.sqlite", "formhistory.sqlite",
                "sessionstore.jsonlz4",
            ):
                (profile / filename).touch()

            with patch.dict(os.environ, {"LOCALAPPDATA": local_app_data}):
                BMAService().clear_browser_cache_and_history()

            for directory in ("cache2", "startupCache", "thumbnails", "storage", "sessionstore-backups"):
                self.assertFalse((profile / directory).exists())
            self.assertFalse((profile / "places.sqlite").exists())
            self.assertFalse((profile / "cookies.sqlite").exists())
            self.assertFalse((profile / "cookies.sqlite-shm").exists())
            self.assertFalse((profile / "cookies.sqlite-wal").exists())
            self.assertFalse((profile / "sessionstore.jsonlz4").exists())

    def test_monitor_can_start_and_stop_without_exposing_field_values(self):
        monitor = BmaPageMonitor()
        thread = Mock()
        with patch("services.bma_page_monitor.Thread", return_value=thread):
            result = monitor.start([planned_order("RES6780264")])
            monitor_id = result["monitor_id"]
            self.assertEqual(monitor.get(monitor_id)["status"], "starting")
            self.assertEqual(monitor.get(monitor_id)["selected_wonums"], ["RES6780264"])
            self.assertEqual(monitor.stop(monitor_id)["status"], "stopping")
            replacement = monitor.start([planned_order("RES6780265")])
            self.assertEqual(monitor.get(monitor_id)["status"], "stopping")
            self.assertEqual(monitor.get(replacement["monitor_id"])["selected_wonums"], ["RES6780265"])
            self.assertEqual(thread.start.call_count, 2)

    def test_monitor_rejects_invalid_ot_numbers(self):
        with self.assertRaises(BMAServiceError):
            BmaPageMonitor().start([planned_order("RES6780264,RES67802192")])

    def test_monitor_accepts_multiple_orders_in_one_session(self):
        monitor = BmaPageMonitor()
        with patch("services.bma_page_monitor.Thread"):
            result = monitor.start([planned_order("RES6780264"), planned_order("RES67802192")])

        self.assertEqual(monitor.get(result["monitor_id"])["selected_wonums"], [
            "RES6780264", "RES67802192",
        ])

    def test_queue_verifies_each_order_before_opening_the_next(self):
        monitor = BmaPageMonitor()
        orders = [planned_order("RES6780264"), planned_order("RES67802192")]
        with patch("services.bma_page_monitor.Thread"):
            monitor_id = monitor.start(orders)["monitor_id"]
        events = []

        with (
            patch.object(monitor, "_open_order_in_maximo",
                         side_effect=lambda _monitor_id, _driver, wonum: events.append(("open", wonum))),
            patch.object(monitor, "_fill_general_dates",
                         side_effect=lambda _monitor_id, _driver, order: events.append(("dates", order["wonum"]))),
            patch.object(monitor, "_fill_assignments",
                         side_effect=lambda _monitor_id, _driver, order: events.append(("assignments", order["wonum"]))),
            patch.object(monitor, "_verify_saved_order",
                         side_effect=lambda _monitor_id, _driver, order: events.append(("verified", order["wonum"]))),
        ):
            self.assertTrue(monitor._process_order_queue(monitor_id, Mock(), orders))

        self.assertEqual(events, [
            ("dates", "RES6780264"), ("assignments", "RES6780264"), ("verified", "RES6780264"),
            ("open", "RES67802192"), ("dates", "RES67802192"),
            ("assignments", "RES67802192"), ("verified", "RES67802192"),
        ])
        self.assertEqual(monitor.get(monitor_id)["completed_wonums"], ["RES6780264", "RES67802192"])

    def test_monitor_accepts_valid_labor_when_bma_will_resolve_specialty_from_registration(self):
        order = planned_order("RES6780264")
        order["specialty"] = ""
        monitor = BmaPageMonitor()
        with patch("services.bma_page_monitor.Thread"):
            result = monitor.start([order])
        self.assertEqual(monitor.get(result["monitor_id"])["status"], "starting")

    def test_api_request_accepts_empty_specialty_for_bma_autocomplete(self):
        order = planned_order("RES6780264")
        order["specialty"] = ""
        self.assertEqual(BmaOrderPlanRequest(**order).specialty, "")

    def test_api_request_accepts_multiple_orders(self):
        request = BmaPageMonitorRequest(orders=[
            planned_order("RES6780264"), planned_order("RES67802192"),
        ])

        self.assertEqual(len(request.orders), 2)

    def test_order_filter_is_found_by_accessible_column_label(self):
        monitor = BmaPageMonitor()
        filter_input = Mock()
        filter_input.is_displayed.return_value = True
        filter_input.is_enabled.return_value = True
        driver = Mock()
        driver.find_elements.side_effect = [[], [filter_input], []]
        driver.execute_script.return_value = "Ordem de Trabalho"

        self.assertIs(monitor._find_order_filter(driver), filter_input)

    def test_order_filter_accepts_work_order_tracking_quicksearch(self):
        monitor = BmaPageMonitor()
        quicksearch = Mock(id="quicksearch")
        quicksearch.get_attribute.return_value = "quicksearch"
        quicksearch.is_displayed.return_value = True
        quicksearch.is_enabled.return_value = True
        driver = Mock()
        driver.find_elements.side_effect = [[quicksearch], [], []]
        driver.execute_script.return_value = "Find Ordem de Trabalho quicksearch"

        self.assertIs(monitor._find_order_filter(driver), quicksearch)

    def test_order_filter_matches_dom_id_not_selenium_remote_id(self):
        quicksearch = Mock(id="selenium-remote-element-id")
        quicksearch.get_attribute.return_value = "quicksearch"
        quicksearch.is_displayed.return_value = True
        quicksearch.is_enabled.return_value = True
        driver = Mock()
        driver.find_elements.side_effect = [[quicksearch], [], []]

        self.assertIs(BmaPageMonitor._find_order_filter(driver), quicksearch)
        driver.execute_script.assert_not_called()

    def test_order_filter_keeps_frame_context_when_quicksearch_is_inside_iframe(self):
        frame = object()
        quicksearch = Mock(id="quicksearch")
        quicksearch.get_attribute.return_value = "quicksearch"
        quicksearch.is_displayed.return_value = True
        quicksearch.is_enabled.return_value = True
        context = ["root"]
        driver = Mock()
        driver.switch_to.frame.side_effect = lambda _frame: context.__setitem__(0, "iframe")
        driver.switch_to.parent_frame.side_effect = lambda: context.__setitem__(0, "root")

        def find_elements(_by, selector):
            if selector == "iframe":
                return [frame] if context[0] == "root" else []
            if selector == "quicksearch":
                return [quicksearch] if context[0] == "iframe" else []
            return []

        driver.find_elements.side_effect = find_elements

        self.assertIs(BmaPageMonitor._find_order_filter(driver), quicksearch)
        self.assertEqual(context[0], "iframe")

    def test_order_filter_prefers_global_quicksearch_over_grid_column(self):
        monitor = BmaPageMonitor()
        global_find = Mock(id="quicksearch")
        column_filter = Mock(id="column-filter")
        global_find.get_attribute.return_value = "quicksearch"
        column_filter.get_attribute.return_value = "column-filter"
        global_find.is_displayed.return_value = True
        global_find.is_enabled.return_value = True
        column_filter.is_displayed.return_value = True
        column_filter.is_enabled.return_value = True
        driver = Mock()

        def find_elements(_by, selector):
            if selector == "quicksearch":
                return [global_find]
            if selector == "input.tablefilterfield":
                return [column_filter]
            return [column_filter]

        driver.find_elements.side_effect = find_elements

        self.assertIs(monitor._find_order_filter(driver), global_find)

    def test_order_filter_does_not_fall_back_to_grid_when_quicksearch_is_disabled(self):
        quicksearch = Mock(id="quicksearch")
        quicksearch.get_attribute.return_value = "quicksearch"
        quicksearch.is_displayed.return_value = True
        quicksearch.is_enabled.return_value = False
        column_filter = Mock(id="column-filter")
        column_filter.get_attribute.return_value = "column-filter"
        column_filter.is_displayed.return_value = True
        column_filter.is_enabled.return_value = True
        driver = Mock()

        def find_elements(_by, selector):
            if selector == "quicksearch":
                return [quicksearch]
            if selector == "input.tablefilterfield":
                return [column_filter]
            return []

        driver.find_elements.side_effect = find_elements

        self.assertIsNone(BmaPageMonitor._find_order_filter(driver))
        driver.execute_script.assert_not_called()

    def test_open_order_skips_result_link_when_quicksearch_opens_the_order(self):
        monitor = BmaPageMonitor()
        order_filter = Mock()
        driver = Mock()

        def wait_for_condition(_monitor_id, predicate, *_args, **_kwargs):
            return predicate()

        with (
            patch.object(monitor, "_find_order_filter", return_value=order_filter),
            patch.object(monitor, "_switch_to_manage_frame"),
            patch.object(monitor, "_current_order_number", return_value="RES6780264"),
            patch.object(monitor, "_find_order_link") as find_order_link,
            patch.object(monitor, "_wait_until", side_effect=wait_for_condition),
            patch.object(monitor, "_wait_for_order") as wait_for_order,
        ):
            monitor._open_order_in_maximo("monitor", driver, "RES6780264")

        find_order_link.assert_not_called()
        wait_for_order.assert_not_called()
        order_filter.click.assert_called_once_with()
        self.assertEqual(
            [call.args for call in order_filter.send_keys.call_args_list],
            [(Keys.CONTROL, "a"), ("RES6780264", Keys.ENTER)],
        )

    def test_current_order_number_is_found_inside_nested_iframe(self):
        monitor = BmaPageMonitor()
        frame = object()
        context = ["root"]
        driver = Mock()
        driver.switch_to.frame.side_effect = lambda _frame: context.__setitem__(0, "iframe")
        driver.switch_to.parent_frame.side_effect = lambda: context.__setitem__(0, "root")
        driver.find_elements.side_effect = lambda _by, selector: [frame] if selector == "iframe" and context[0] == "root" else []

        with patch.object(monitor, "_current_order_number",
                          side_effect=lambda _driver: "RES6780264" if context[0] == "iframe" else ""):
            self.assertEqual(monitor._current_order_number_in_frames(driver), "RES6780264")

        self.assertEqual(context[0], "root")

    def test_order_link_is_found_by_exact_ot_number(self):
        monitor = BmaPageMonitor()
        order_link = Mock()
        order_link.is_displayed.return_value = True
        order_link.is_enabled.return_value = True
        driver = Mock()
        driver.find_elements.return_value = [order_link]

        self.assertIs(monitor._find_order_link(driver, "RES6780264"), order_link)
        self.assertIn("normalize-space(.)='RES6780264'", driver.find_elements.call_args.args[1])

    def test_order_link_keeps_frame_context_when_match_is_inside_iframe(self):
        frame = object()
        order_link = Mock()
        order_link.is_displayed.return_value = True
        order_link.is_enabled.return_value = True
        context = ["root"]
        driver = Mock()
        driver.switch_to.frame.side_effect = lambda _frame: context.__setitem__(0, "iframe")
        driver.switch_to.parent_frame.side_effect = lambda: context.__setitem__(0, "root")

        def find_elements(_by, selector):
            if selector == "iframe":
                return [frame] if context[0] == "root" else []
            if "normalize-space(.)='RES6780264'" in selector and context[0] == "iframe":
                return [order_link]
            return []

        driver.find_elements.side_effect = find_elements

        self.assertIs(BmaPageMonitor._find_order_link(driver, "RES6780264"), order_link)
        self.assertEqual(context[0], "iframe")

    def test_single_selected_order_is_clicked_after_filter_submission(self):
        monitor = BmaPageMonitor()
        thread = Mock()
        with patch("services.bma_page_monitor.Thread", return_value=thread):
            monitor_id = monitor.start([planned_order("RES6780264")])["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        driver_service = Mock(timeout=30)
        driver_service._create_browser.return_value = driver
        filter_input = Mock()
        order_link = Mock()
        order_link.click.side_effect = session["stop"].set

        with patch("services.bma_page_monitor.BMAService", return_value=driver_service), \
             patch.object(monitor, "_visible_fields", return_value=[]), \
             patch.object(monitor, "_find_order_filter", return_value=filter_input), \
             patch.object(monitor, "_switch_to_manage_frame"), \
               patch.object(monitor, "_current_order_number", return_value=""), \
               patch.object(monitor, "_wait_for_order"), \
             patch.object(monitor, "_find_order_link", return_value=order_link) as find_link, \
             patch("services.bma_page_monitor.sleep"):
            monitor._run(monitor_id, ["RES6780264"])

        self.assertEqual(
            [call.args for call in filter_input.send_keys.call_args_list],
            [(Keys.CONTROL, "a"), ("RES6780264", Keys.ENTER)],
        )
        find_link.assert_called_once_with(driver, "RES6780264")
        order_link.click.assert_called_once_with()
        self.assertEqual(monitor.get(monitor_id)["opened_wonum"], "RES6780264")

    def test_manage_shell_expands_work_orders_group_to_open_tracker(self):
        monitor = BmaPageMonitor()
        menu = Mock()
        menu.is_displayed.return_value = True
        menu.is_enabled.return_value = True
        work_orders = Mock()
        work_orders.is_displayed.return_value = True
        work_orders.is_enabled.return_value = True
        app = Mock()
        app.is_displayed.return_value = True
        app.is_enabled.return_value = True
        driver = Mock()
        driver.find_elements.side_effect = [[], [menu], [], [], [work_orders], [app]]

        self.assertTrue(monitor._open_work_order_app(driver))
        menu.click.assert_called_once_with()
        work_orders.click.assert_called_once_with()
        app.click.assert_called_once_with()

    def test_manage_shell_opens_tracker_from_recent_applications(self):
        monitor = BmaPageMonitor()
        recent_apps = Mock()
        recent_apps.is_displayed.return_value = True
        recent_apps.is_enabled.return_value = True
        app = Mock()
        app.is_displayed.return_value = True
        app.is_enabled.return_value = True
        driver = Mock()
        driver.find_elements.side_effect = [[], [], [recent_apps], [app]]

        self.assertTrue(monitor._open_work_order_app(driver))
        recent_apps.click.assert_called_once_with()
        app.click.assert_called_once_with()

    def test_login_button_lookup_uses_exact_label_not_ldap_alternative(self):
        monitor = BmaPageMonitor()
        login_button = Mock(text="Efetuar login")
        login_button.get_attribute.return_value = ""
        login_button.is_displayed.return_value = True
        login_button.is_enabled.return_value = True
        driver = Mock()
        driver.find_elements.return_value = [login_button]

        self.assertIs(monitor._find_login_button(driver), login_button)

        ldap_button = Mock(text="Efetue login com LDAP")
        ldap_button.get_attribute.return_value = ""
        ldap_driver = Mock()
        ldap_driver.find_elements.return_value = [ldap_button]
        self.assertIsNone(monitor._find_login_button(ldap_driver))

    def test_monitor_filters_one_selected_number_and_opens_its_match(self):
        monitor = BmaPageMonitor()
        thread = Mock()
        with patch("services.bma_page_monitor.Thread", return_value=thread):
            monitor_id = monitor.start([planned_order("RES6780264")])["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        driver_service = Mock(timeout=30)
        driver_service._create_browser.return_value = driver
        filter_input = Mock()
        order_link = Mock()
        order_link.click.side_effect = session["stop"].set

        with patch("services.bma_page_monitor.BMAService", return_value=driver_service), \
             patch.object(monitor, "_visible_fields", return_value=[]), \
             patch.object(monitor, "_find_order_filter", return_value=filter_input), \
             patch.object(monitor, "_switch_to_manage_frame"), \
             patch.object(monitor, "_current_order_number", return_value=""), \
             patch.object(monitor, "_wait_for_order"), \
             patch.object(monitor, "_find_order_link", return_value=order_link) as find_link, \
             patch("services.bma_page_monitor.sleep"):
            monitor._run(monitor_id, ["RES6780264", "RES67802192"])

        driver_service._create_browser.assert_called_once_with(page_load_strategy="eager", headless=False)
        filter_input.click.assert_called_once_with()
        self.assertEqual(
            [call.args for call in filter_input.send_keys.call_args_list],
            [(Keys.CONTROL, "a"), ("RES6780264", Keys.ENTER)],
        )
        find_link.assert_called_once_with(driver, "RES6780264")
        order_link.click.assert_called_once_with()
        self.assertEqual(monitor.get(monitor_id)["opened_wonum"], "RES6780264")
        self.assertEqual(monitor.get(monitor_id)["page_url"], "https://maximo.example/wotrack#/main")
        self.assertEqual(monitor.get(monitor_id)["page_title"], "Rastrear Ordem de Trabalho")

    def test_initial_quicksearch_opening_order_directly_starts_queue(self):
        monitor = BmaPageMonitor()
        thread = Mock()
        with patch("services.bma_page_monitor.Thread", return_value=thread):
            monitor_id = monitor.start([planned_order("RES6780264")])["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        driver_service = Mock(timeout=30)
        driver_service._create_browser.return_value = driver
        filter_input = Mock()

        with patch("services.bma_page_monitor.BMAService", return_value=driver_service), \
             patch.object(monitor, "_visible_fields", return_value=[]), \
             patch.object(monitor, "_find_order_filter", return_value=filter_input), \
             patch.object(monitor, "_switch_to_manage_frame"), \
             patch.object(monitor, "_current_order_number", return_value="RES6780264"), \
             patch.object(monitor, "_wait_for_order") as wait_for_order, \
             patch.object(monitor, "_find_order_link") as find_link, \
             patch.object(monitor, "_process_order_queue", return_value=True) as process_queue, \
             patch("services.bma_page_monitor.sleep"):
            monitor._run(monitor_id, ["RES6780264"])

        wait_for_order.assert_called_once_with(monitor_id, driver, "RES6780264")
        find_link.assert_not_called()
        process_queue.assert_called_once_with(monitor_id, driver, session["orders"])
        self.assertEqual(monitor.get(monitor_id)["status"], "completed")

    def test_monitor_reports_interaction_error_after_finding_quicksearch(self):
        monitor = BmaPageMonitor()
        thread = Mock()
        with patch("services.bma_page_monitor.Thread", return_value=thread):
            monitor_id = monitor.start([planned_order("RES6780264")])["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        driver_service = Mock(timeout=30)
        driver_service._create_browser.return_value = driver
        filter_input = Mock()
        filter_input.click.side_effect = WebDriverException("element not interactable")
        fields = [{"tag": "input", "id": "quicksearch", "label": "Find Ordem de Trabalho"}]

        with patch("services.bma_page_monitor.BMAService", return_value=driver_service), \
             patch.object(monitor, "_visible_fields", return_value=fields), \
             patch.object(monitor, "_find_order_filter", return_value=filter_input), \
             patch.object(monitor, "_update", wraps=monitor._update) as update, \
             patch("services.bma_page_monitor.sleep", side_effect=session["stop"].set):
            monitor._run(monitor_id, ["RES6780264"])

        messages = [call.kwargs.get("message", "") for call in update.call_args_list]
        self.assertTrue(any(
            "Campo de filtro localizado" in message and "element not interactable" in message
            for message in messages
        ))

    def test_monitor_waits_past_30_seconds_without_restarting_until_tracking_opens(self):
        monitor = BmaPageMonitor()
        thread = Mock()
        with patch("services.bma_page_monitor.Thread", return_value=thread):
            monitor_id = monitor.start([planned_order("RES6780264")])["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        driver_service = Mock(timeout=30)
        driver_service._create_browser.return_value = driver
        filter_input = Mock()
        order_link = Mock()
        order_link.click.side_effect = session["stop"].set
        fields = [{"tag": "input", "id": "quicksearch", "label": "Find Ordem de Trabalho"}]
        clock = [0]

        def advance_clock(_seconds):
            clock[0] += 31

        with patch("services.bma_page_monitor.BMAService", return_value=driver_service), \
             patch.object(monitor, "_visible_fields", side_effect=[[], [], fields]), \
             patch.object(monitor, "_find_order_filter", side_effect=[None, None, filter_input]), \
             patch.object(monitor, "_find_order_link", return_value=order_link), \
             patch.object(monitor, "_switch_to_manage_frame"), \
             patch.object(monitor, "_current_order_number", return_value=""), \
             patch.object(monitor, "_wait_for_order"), \
             patch.object(monitor, "_open_work_order_app", return_value=False), \
             patch("services.bma_page_monitor.monotonic", side_effect=lambda: clock[0]), \
             patch("services.bma_page_monitor.sleep", side_effect=advance_clock):
            monitor._run(monitor_id, ["RES6780264"])

        self.assertEqual(driver_service._create_browser.call_count, 1)
        self.assertEqual(driver_service.clear_browser_cache_and_history.call_count, 1)
        self.assertEqual(driver.get.call_count, 2)
        driver.get.assert_called_with(WOTRACK_URL)
        service_calls = [call[0] for call in driver_service.mock_calls]
        self.assertLess(
            service_calls.index("clear_browser_cache_and_history"),
            service_calls.index("_create_browser"),
        )
        driver.quit.assert_called_once_with()
        self.assertEqual(monitor.get(monitor_id)["opened_wonum"], "RES6780264")

    def test_first_tracking_input_prevents_restart_while_filter_is_pending(self):
        monitor = BmaPageMonitor()
        thread = Mock()
        with patch("services.bma_page_monitor.Thread", return_value=thread):
            monitor_id = monitor.start([planned_order("RES6780264")])["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        driver_service = Mock(timeout=30)
        driver_service._create_browser.return_value = driver
        fields = [{"tag": "input", "id": "quicksearch", "label": "Find Ordem de Trabalho"}]
        clock = [0]
        sleep_count = [0]

        def advance_until_monitor_stops(_seconds):
            sleep_count[0] += 1
            clock[0] = 31
            if sleep_count[0] == 2:
                session["stop"].set()

        with patch("services.bma_page_monitor.BMAService", return_value=driver_service), \
               patch.object(monitor, "_visible_fields", return_value=fields), \
             patch.object(monitor, "_find_order_filter", return_value=None), \
             patch("services.bma_page_monitor.monotonic", side_effect=lambda: clock[0]), \
             patch("services.bma_page_monitor.sleep", side_effect=advance_until_monitor_stops):
            monitor._run(monitor_id, ["RES6780264"])

        driver_service._create_browser.assert_called_once_with(page_load_strategy="eager", headless=False)
        driver_service.clear_browser_cache_and_history.assert_called_once_with()
        self.assertEqual(monitor.get(monitor_id)["status"], "stopped")
        self.assertEqual(sleep_count[0], 2)

    def test_tracking_title_without_first_input_keeps_waiting_on_same_browser(self):
        monitor = BmaPageMonitor()
        thread = Mock()
        with patch("services.bma_page_monitor.Thread", return_value=thread):
            monitor_id = monitor.start([planned_order("RES6780264")])["monitor_id"]
        session = monitor._sessions[monitor_id]
        driver = Mock()
        driver.current_url = "https://maximo.example/wotrack#/main"
        driver.title = "Rastrear Ordem de Trabalho"
        driver_service = Mock(timeout=30)
        driver_service._create_browser.return_value = driver
        clock = [0]
        sleep_count = [0]

        def advance_clock(_seconds):
            sleep_count[0] += 1
            clock[0] = 31
            if sleep_count[0] == 2:
                session["stop"].set()

        with patch("services.bma_page_monitor.BMAService", return_value=driver_service), \
             patch.object(monitor, "_visible_fields", return_value=[]), \
             patch.object(monitor, "_find_order_filter", return_value=None), \
             patch.object(monitor, "_open_work_order_app", return_value=False), \
             patch("services.bma_page_monitor.monotonic", side_effect=lambda: clock[0]), \
             patch("services.bma_page_monitor.sleep", side_effect=advance_clock):
            monitor._run(monitor_id, ["RES6780264"])

        self.assertEqual(driver_service._create_browser.call_count, 1)
        driver_service.clear_browser_cache_and_history.assert_called_once_with()
        driver.quit.assert_called_once_with()

    def test_visible_field_scan_does_not_request_or_return_input_values(self):
        fields = [{"tag": "input", "id": "quicksearch", "name": "", "label": "Find Ordem de Trabalho",
               "type": "text", "disabled": False, "frame": "principal"}]
        driver = Mock()
        driver.execute_script.return_value = fields
        driver.find_elements.return_value = []

        result = BmaPageMonitor._visible_fields(driver)

        self.assertEqual(result, fields)
        script = driver.execute_script.call_args.args[0]
        self.assertIn("querySelectorAll('input, textarea, select, button')", script)
        self.assertIn("split(/\\s+/).filter(Boolean)", script)
        self.assertNotIn("element.value", script)
        self.assertNotIn("value: ", script)

    def test_visible_field_scan_descends_into_iframes(self):
        frame_handle = object()
        root_fields = [{"tag": "input", "id": "root", "name": "", "label": "Root",
                        "type": "text", "disabled": False}]
        child_fields = [{"tag": "input", "id": "quicksearch", "name": "", "label": "Find Ordem de Trabalho",
                         "type": "text", "disabled": False}]
        driver = Mock()
        driver.execute_script.side_effect = [root_fields, child_fields]
        driver.find_elements.side_effect = [[frame_handle], []]

        result = BmaPageMonitor._visible_fields(driver)

        self.assertEqual([field["frame"] for field in result], ["principal", "principal/iframe[0]"])
        driver.switch_to.frame.assert_called_once_with(frame_handle)
        driver.switch_to.parent_frame.assert_called_once()


if __name__ == "__main__":
    unittest.main()