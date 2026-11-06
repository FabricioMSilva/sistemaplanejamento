from __future__ import annotations

import unittest
from unittest.mock import patch

from services import ronda_quick_report


class RondaQuickReportTests(unittest.TestCase):
    def test_acknowledges_required_fields_dialog_and_resumes(self):
        driver = unittest.mock.Mock()

        class SwitchTo:
            @property
            def alert(self):
                raise ronda_quick_report.NoAlertPresentException()

        driver.switch_to = SwitchTo()
        ok_button = unittest.mock.Mock()
        ok_button.text = "OK"
        driver.execute_script.return_value = (
            "BMXAA7998E - Você não inseriu um valor nos seguintes campos obrigatórios: "
            "Refere-se a; Status do Equipamento"
        )
        candidates = [ok_button, None]

        def find(_driver, _by, _selector, predicate):
            candidate = candidates[0]
            if candidate is None or not predicate(candidate):
                return None
            candidates.pop(0)
            return candidate

        with (
            patch.object(ronda_quick_report, "_find", side_effect=find),
            patch.object(ronda_quick_report, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda condition: condition(driver)
            dismissed = ronda_quick_report._dismiss_required_fields_message(driver)

        self.assertTrue(dismissed)
        ok_button.click.assert_called_once_with()

    def test_insert_button_waits_for_visible_icon_then_activates_anchor_once(self):
        driver = unittest.mock.Mock()
        anchor = unittest.mock.Mock()
        anchor.is_displayed.return_value = True
        anchor.is_enabled.return_value = True
        anchor.get_attribute.return_value = None
        icon = unittest.mock.Mock()
        icon.is_displayed.return_value = True
        anchor.find_elements.return_value = [icon]

        with (
            patch.object(
                ronda_quick_report,
                "_find",
                side_effect=lambda _driver, _by, _selector, predicate: anchor if predicate(anchor) else None,
            ) as find,
            patch.object(ronda_quick_report, "maximo_ui_loaded", return_value=True),
            patch.object(ronda_quick_report, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda condition: condition(driver)
            ronda_quick_report._click_new_order(driver, timeout=1)

        anchor.find_elements.assert_called_once_with(ronda_quick_report.By.ID, "toolactions_INSERT-tbb_image")
        driver.execute_script.assert_called_once_with(
            "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", anchor,
        )
        self.assertIn("a#toolactions_INSERT-tbb_anchor", find.call_args.args[2])

    def test_adds_labor_row_with_dom_click_and_waits_for_field(self):
        driver = unittest.mock.Mock()
        add_button = unittest.mock.Mock()
        add_button.is_displayed.return_value = True
        add_button.is_enabled.return_value = True
        add_button.text = "New Row"
        add_icon = unittest.mock.Mock()
        add_button.find_elements.return_value = [add_icon]

        def find_add_row(_driver, _by, _selector, predicate):
            return add_button if predicate(add_button) else None

        with (
            patch.object(ronda_quick_report, "_find_control", side_effect=[None, unittest.mock.Mock()]),
            patch.object(ronda_quick_report, "_find", side_effect=find_add_row) as find,
            patch.object(ronda_quick_report, "_loading_overlay") as loading_overlay,
            patch.object(ronda_quick_report, "maximo_ui_loaded", return_value=True),
            patch.object(ronda_quick_report, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda condition: condition(driver)
            ronda_quick_report._add_labor_row(driver, 0)

        self.assertEqual(find.call_args.args[2], "a[id$='_bg_button_addrow-pb_addrow_a']")
        loading_overlay.assert_not_called()
        add_button.find_elements.assert_called_once_with(
            ronda_quick_report.By.CSS_SELECTOR, "img[id$='_addrow']",
        )
        add_button.click.assert_called_once_with()

    def test_work_type_confirmation_uses_no_and_returns_to_the_flow(self):
        driver = unittest.mock.Mock()
        no_button = unittest.mock.Mock()
        no_button.text = "Não"

        class SwitchTo:
            @property
            def alert(self):
                raise ronda_quick_report.NoAlertPresentException()

        driver.switch_to = SwitchTo()
        driver.execute_script.return_value = (
            "BMXZZ0036W - Tem certeza de que deseja alterar o tipo de ordem de trabalho?"
        )

        def find_confirmation(_driver, _by, _selector, predicate):
            return no_button if predicate(no_button) else None

        with (
            patch.object(ronda_quick_report, "_find", side_effect=find_confirmation),
            patch.object(ronda_quick_report, "_value", return_value="T"),
            patch.object(ronda_quick_report, "_value_matches", return_value=True),
            patch.object(ronda_quick_report, "maximo_ui_loaded", return_value=True),
            patch.object(ronda_quick_report, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda condition: condition(driver)
            ronda_quick_report._confirm_work_type_change(driver)

        no_button.click.assert_called_once_with()

    def test_complete_workflow_clicks_ok_after_option_is_already_selected(self):
        driver = unittest.mock.Mock()
        route_button = unittest.mock.Mock()
        route_button.is_displayed.return_value = True
        route_button.is_enabled.return_value = True
        dialog = unittest.mock.Mock()
        dialog.is_displayed.return_value = True
        option = unittest.mock.Mock()
        option.is_displayed.return_value = True
        option.is_selected.return_value = True
        ok_button = unittest.mock.Mock()
        ok_button.is_displayed.return_value = True
        ok_button.is_enabled.return_value = True
        candidates = {
            "a[title='Rotear Workflow']": route_button,
            "#inputwf-hb": dialog,
            "//input[@type='radio'] | //*[@role='radio']": option,
            "button[title='OK']": ok_button,
        }

        def find(_driver, _by, selector, predicate):
            candidate = candidates[selector]
            return candidate if predicate(candidate) else None

        driver.execute_script.return_value = "Completar a Ordem de Trabalho"
        with (
            patch.object(ronda_quick_report, "_find", side_effect=find) as find,
            patch.object(ronda_quick_report, "_find_all", side_effect=AssertionError("unexpected frame traversal")),
            patch.object(ronda_quick_report, "_value", return_value="COMP"),
            patch.object(ronda_quick_report, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda condition: condition(driver)
            ronda_quick_report._complete_workflow(driver, timeout=1)

        route_button.click.assert_called_once_with()
        option.click.assert_not_called()
        ok_button.click.assert_called_once_with()
        self.assertIn("button[title='OK']", [call.args[2] for call in find.call_args_list])

    def test_fill_sets_input_value_without_keyboard_navigation(self):
        driver = unittest.mock.Mock()
        control = unittest.mock.Mock()

        with (
            patch.object(ronda_quick_report, "_dismiss_required_fields_message", return_value=False),
            patch.object(ronda_quick_report, "_loading_overlay", return_value=None),
            patch.object(ronda_quick_report, "_find_control", return_value=control),
            patch.object(ronda_quick_report, "_value_matches", return_value=True),
            patch.object(ronda_quick_report, "maximo_ui_loaded", return_value=True),
            patch.object(ronda_quick_report, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda condition: condition(driver)
            ronda_quick_report._fill(driver, "Equipamento", "EQ123")

        driver.execute_script.assert_called_once()
        script = driver.execute_script.call_args.args[0]
        self.assertIn("document.createEvent('HTMLEvents')", script)
        self.assertIn("maximoWindow.sendEvent('change', element.id, value)", script)
        self.assertEqual(driver.execute_script.call_args.args[1:], (control, "EQ123"))
        control.send_keys.assert_not_called()

    def test_ronda_quick_report_fields_follow_the_explicit_sequence(self):
        steps = []
        order = {
            "ronda": "Ronda",
            "equipment": "EQ123",
            "location": "LOC1",
            "refers_to": "3 AVAIL",
            "description_longdescription": "Long description",
            "start_date": "05/11/2026",
            "start_time": "08:00",
            "end_date": "05/11/2026",
            "end_time": "12:00",
            "hours": 4,
        }

        def record_fill(_driver, label, value, index=0, *, skip_if_matches=False):
            steps.append(("fill", label, value, index))

        with (
            patch.object(ronda_quick_report, "_fill", side_effect=record_fill),
            patch.object(
                ronda_quick_report, "_set_long_description",
                side_effect=lambda _driver, text: steps.append(("long_description", text)),
            ),
            patch.object(
                ronda_quick_report, "_add_labor_row",
                side_effect=lambda _driver, index: steps.append(("add_labor_row", index)),
            ),
            patch.object(
                ronda_quick_report, "_confirm_work_type_change",
                side_effect=lambda _driver: steps.append(("confirm_work_type",)),
            ),
        ):
            expected = ronda_quick_report.fill_ronda_quick_report_fields(
                unittest.mock.Mock(), order, [{"laborcode": "E123"}],
            )

        self.assertEqual(steps, [
            ("fill", "Ordem de Trabalho description", "SITE-NFE-Ronda", 0),
            ("long_description", "Long description"),
            ("fill", "Equipamento", "EQ123", 0),
            ("fill", "Local", "LOC1", 0),
            ("fill", "Refere-se a", "3 AVAIL", 0),
            ("fill", "Status do Equipamento", "NA", 0),
            ("fill", "Tipo de trabalho", "T", 0),
            ("confirm_work_type",),
            ("add_labor_row", 0),
            ("fill", "Mão de obra", "E123", 0),
            ("fill", "Data de início", "05/11/2026", 0),
            ("fill", "Hora de início", "08:00", 0),
            ("fill", "End Date", "05/11/2026", 0),
            ("fill", "Hora de término", "12:00", 0),
            ("fill", "Horas normais", "4:00", 0),
        ])
        self.assertEqual([label for label, _value, _index in expected], [
            "Ordem de Trabalho description", "Equipamento", "Local", "Refere-se a",
            "Status do Equipamento", "Tipo de trabalho", "Mão de obra", "Data de início",
            "Hora de início", "End Date", "Hora de término", "Horas normais",
        ])


if __name__ == "__main__":
    unittest.main()