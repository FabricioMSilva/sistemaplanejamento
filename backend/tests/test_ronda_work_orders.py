from __future__ import annotations

import unittest
from unittest.mock import patch

from services import ronda_bma
from services.ronda_work_orders import prepare_ronda_orders


class RondaWorkOrderPreparationTests(unittest.TestCase):
    def test_value_reads_disabled_generated_order_number(self):
        driver = unittest.mock.Mock()
        control = unittest.mock.Mock()
        control.is_displayed.return_value = True
        control.is_enabled.return_value = False
        control.get_attribute.return_value = "RES6835687"
        def search(_driver, _by, selector, predicate, *, require_enabled=True):
            if "aria-readonly" in selector:
                self.assertFalse(require_enabled)
                self.assertTrue(predicate(control))
                return [control]
            return []

        with patch.object(ronda_bma, "_find_all", side_effect=search) as find_all:
            self.assertEqual(ronda_bma._value(driver, "Ordem de Trabalho"), "RES6835687")
            self.assertIsNone(ronda_bma._find_control(driver, "Ordem de Trabalho"))

        self.assertEqual(control.get_attribute.call_count, 1)
        self.assertTrue(any("aria-readonly" in call.args[2] for call in find_all.call_args_list))

    def test_find_control_keeps_matching_frame_active_for_interaction(self):
        driver = unittest.mock.Mock()
        control = unittest.mock.Mock()
        driver.execute_script.return_value = "Ordem de Trabalho description"

        def find_in_frame(_driver, _by, _selector, predicate, *, require_enabled=True):
            self.assertTrue(require_enabled)
            return control if predicate(control) else None

        with patch.object(ronda_bma.BMAService, "_find_matching_in_frames", side_effect=find_in_frame):
            result = ronda_bma._find_control(driver, "Ordem de Trabalho description")

        self.assertIs(result, control)
        driver.switch_to.default_content.assert_called_once_with()
        self.assertIn("previousElementSibling", driver.execute_script.call_args.args[0])

    def test_maximo_ui_load_gate_rejects_loading_page(self):
        driver = unittest.mock.Mock()
        driver.execute_script.side_effect = [False, True]

        self.assertFalse(ronda_bma.maximo_ui_loaded(driver))
        self.assertTrue(ronda_bma.maximo_ui_loaded(driver))

    def test_quick_report_toolbar_uses_native_click_after_page_load(self):
        driver = unittest.mock.Mock()
        driver.execute_script.return_value = True
        button = unittest.mock.Mock()

        with (
            patch.object(ronda_bma, "_find", side_effect=lambda _driver, _by, _selector, predicate: button if predicate(button) else None),
            patch.object(ronda_bma, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda predicate: predicate(driver)
            ronda_bma._click(driver, ronda_bma.By.CSS_SELECTOR, "#toolactions_INSERT-tbb_anchor", "Nova OT")

        button.click.assert_called_once_with()
        driver.execute_script.assert_called_once()

    def test_hidden_form_error_is_reported_as_quick_report_not_ready(self):
        driver = unittest.mock.Mock()
        button = unittest.mock.Mock()
        button.click.side_effect = ronda_bma.WebDriverException("The Hidden Form is missing!")

        with (
            patch.object(ronda_bma, "_find", return_value=button),
            patch.object(ronda_bma, "WebDriverWait") as wait,
        ):
            wait.return_value.until.return_value = button
            with self.assertRaisesRegex(ronda_bma.BMAServiceError, "formulário interno do Maximo"):
                ronda_bma._click(driver, ronda_bma.By.CSS_SELECTOR, "#toolactions_INSERT-tbb_anchor", "Nova OT")

    def test_open_new_order_distinguishes_click_from_missing_res(self):
        driver = unittest.mock.Mock()
        with (
            patch.object(ronda_bma, "_find_control", return_value=None),
            patch.object(ronda_bma, "_click") as click,
            patch.object(ronda_bma, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = ronda_bma.TimeoutException()
            with self.assertRaisesRegex(ronda_bma.BMAServiceError, r"Duas tentativas no \+ do Quick Report"):
                ronda_bma._open_new_order(driver)
        self.assertEqual(click.call_count, 2)
        click.assert_called_with(
            driver, ronda_bma.By.CSS_SELECTOR, "#toolactions_INSERT-tbb_anchor", "Nova Ordem de trabalho",
        )

        with (
            patch.object(ronda_bma, "_find_control", return_value=None),
            patch.object(ronda_bma, "_click"),
            patch.object(ronda_bma, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = [True, ronda_bma.TimeoutException()]
            with self.assertRaisesRegex(ronda_bma.BMAServiceError, "não gerou o número RES"):
                ronda_bma._open_new_order(driver)

    def test_open_new_order_retries_plus_only_when_form_is_absent(self):
        driver = unittest.mock.Mock()
        with (
            patch.object(ronda_bma, "_find_control", side_effect=[None, None]),
            patch.object(ronda_bma, "_click") as click,
            patch.object(ronda_bma, "WebDriverWait") as wait,
            patch.object(ronda_bma, "_value", return_value="RES1234567"),
        ):
            wait.return_value.until.side_effect = [ronda_bma.TimeoutException(), True, True]
            self.assertEqual(ronda_bma._open_new_order(driver), "RES1234567")

        self.assertEqual(click.call_count, 2)

    def test_add_labor_row_clicks_plus_for_requested_executant_row(self):
        driver = unittest.mock.Mock()
        with (
            patch.object(ronda_bma, "_find_control", side_effect=[None, unittest.mock.Mock()]) as find_control,
            patch.object(ronda_bma, "_click") as click,
            patch.object(ronda_bma, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda predicate: predicate(driver)
            ronda_bma._add_labor_row(driver, 1)

        self.assertEqual(find_control.call_args_list, [
            unittest.mock.call(driver, "Mão de obra", 1),
            unittest.mock.call(driver, "Mão de obra", 1),
        ])
        click.assert_called_once_with(
            driver, ronda_bma.By.CSS_SELECTOR,
            "button[id$='_bg_button_addrow-pb'],a[id$='_bg_button_addrow-pb_addrow_a'],"
            "button[title='Nova linha'],button[title='New Row'],img[id$='_addrow']",
            "Nova linha de mão de obra",
        )

    def test_quick_report_checkpoints_number_save_and_comp_in_order(self):
        order = {
            "ronda": "Análise química", "labor": [{"laborcode": "E123"}, {"laborcode": "E456"}],
            "work_type": "OTHER", "equipment_status": "OPERATING",
            "equipment": "403006100", "location": "OFICINA-NFE",
            "description_longdescription": "Descrição de teste", "start_date": "04/11/2026",
            "start_time": "16:00", "end_date": "04/11/2026", "end_time": "23:00", "hours": 7,
        }
        driver = object()
        events = []
        with (
            patch.object(ronda_bma, "_open_new_order", return_value="RES1234567"),
            patch.object(ronda_bma, "_set") as set_field,
            patch.object(ronda_bma, "_set_long_description"),
            patch.object(ronda_bma, "_verify_fields") as verify_fields,
            patch.object(ronda_bma, "_save") as save_order,
            patch.object(ronda_bma, "_add_labor_row") as add_labor_row,
            patch.object(ronda_bma, "_complete_workflow") as complete_workflow,
        ):
            number = ronda_bma.create_ronda_work_order(
                driver, order,
                on_number=lambda value: events.append(("numero", value)),
                on_saved=lambda value: events.append(("salva", value)),
                on_completed=lambda value: events.append(("COMP", value)),
            )

        self.assertEqual(number, "RES1234567")
        self.assertEqual(events, [
            ("numero", "RES1234567"),
            ("salva", "RES1234567"),
            ("COMP", "RES1234567"),
        ])
        set_field.assert_any_call(driver, "Ordem de Trabalho description", "SITE-NFE-Análise química")
        set_field.assert_any_call(driver, "Equipamento", "403006100")
        set_field.assert_any_call(driver, "Tipo de trabalho", "T")
        set_field.assert_any_call(driver, "Status do Equipamento", "NA")
        set_field.assert_any_call(driver, "Mão de obra", "E123", 0)
        set_field.assert_any_call(driver, "Mão de obra", "E456", 1)
        set_field.assert_any_call(driver, "Data de início", "04/11/2026", 0)
        set_field.assert_any_call(driver, "Hora de início", "16:00", 0)
        set_field.assert_any_call(driver, "End Date", "04/11/2026", 0)
        set_field.assert_any_call(driver, "Hora de término", "23:00", 0)
        self.assertEqual(add_labor_row.call_args_list, [
            unittest.mock.call(driver, 0), unittest.mock.call(driver, 1),
        ])
        expected_fields = verify_fields.call_args.args[1]
        self.assertIn(("Equipamento", "403006100", 0), expected_fields)
        self.assertIn(("Mão de obra", "E456", 1), expected_fields)
        save_order.assert_called_once_with(driver, "RES1234567")
        complete_workflow.assert_called_once_with(driver)

    def test_set_uses_requested_commit_key(self):
        driver = unittest.mock.Mock()
        control = unittest.mock.Mock()
        control.get_attribute.return_value = "403006100"

        with (
            patch.object(ronda_bma, "_find_control", return_value=control),
            patch.object(ronda_bma, "_find", return_value=None),
            patch.object(ronda_bma, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda condition: condition(driver)
            ronda_bma._set(driver, "Equipamento", "403006100", after_key=ronda_bma.Keys.TAB)

        control.send_keys.assert_any_call(ronda_bma.Keys.TAB)
        control.get_attribute.assert_not_called()

    def test_confirms_matching_work_type_change_dialog(self):
        driver = unittest.mock.Mock()
        class SwitchTo:
            @property
            def alert(self):
                raise ronda_bma.NoAlertPresentException()

        driver.switch_to = SwitchTo()
        button = unittest.mock.Mock()
        button.text = "Sim"
        driver.execute_script.return_value = (
            "Mensagem do Sistema BMXZZ0036W - Tem certeza de que deseja alterar o tipo de ordem de trabalho?"
        )

        with (
            patch.object(
                ronda_bma, "_find",
                side_effect=lambda _driver, _by, _selector, predicate: button if predicate(button) else None,
            ),
            patch.object(ronda_bma, "WebDriverWait") as wait,
        ):
            wait.return_value.until.side_effect = lambda predicate: predicate(driver)
            ronda_bma._confirm_work_type_change(driver)

        button.click.assert_called_once_with()

    def test_equipment_value_with_description_is_confirmed(self):
        driver = unittest.mock.Mock()
        with patch.object(ronda_bma, "_value", return_value="403006100 - Bomba"):
            self.assertTrue(ronda_bma._value_confirmed(driver, "Equipamento", "403006100", 0))

    def test_set_waits_until_maximo_loading_overlay_is_gone(self):
        driver = unittest.mock.Mock()
        control = unittest.mock.Mock()
        overlay = unittest.mock.Mock()
        overlay.is_displayed.return_value = True

        with (
            patch.object(ronda_bma, "_find", side_effect=[overlay, None]),
            patch.object(ronda_bma, "_find_control", return_value=control),
            patch.object(ronda_bma, "WebDriverWait") as wait,
        ):
            def wait_until(condition):
                result = condition(driver)
                return condition(driver) if result is False else result

            wait.return_value.until.side_effect = wait_until
            ronda_bma._set(driver, "Equipamento", "403006100", after_key=ronda_bma.Keys.ENTER)

        control.click.assert_called_once_with()
        self.assertEqual(wait.return_value.until.call_count, 1)

    def test_analysis_round_builds_quick_report_payload_from_saved_fields(self):
        item = {
            "id": 71,
            "ronda": "ANALISE QUIMICA NF",
            "data": "2026-11-04",
            "turno": "A",
            "equipe": "NFE",
            "executantes": [{"nome": "Pessoa Teste", "matricula": "E123"}],
        }

        result = prepare_ronda_orders([item])

        self.assertEqual(result["waiting"], [])
        self.assertEqual(len(result["orders"]), 1)
        order = result["orders"][0]
        self.assertEqual(order["sharepoint_ids"], [71])
        self.assertEqual(order["labor"], [{"laborcode": "E123"}])
        self.assertEqual(order["start_date"], "04/11/2026")
        self.assertEqual(order["start_time"], "00:00")
        self.assertEqual(order["end_date"], "04/11/2026")
        self.assertEqual(order["end_time"], "07:00")
        self.assertEqual(order["hours"], 7)
        self.assertIn("Pessoa Teste", order["description_longdescription"])
        self.assertIn("00:00 às 07:00", order["description_longdescription"])
        self.assertNotIn("00:00 às 08:00", order["description_longdescription"])

    def test_meter_round_rejects_shift_b_and_accepts_a_or_c(self):
        base = {
            "id": 80,
            "ronda": "RONDA MEDIDORES NFE",
            "data": "2026-11-04",
            "equipe": "NFE",
            "executantes": [{"nome": "Pessoa Teste", "matricula": "E123"}],
        }

        with self.assertRaisesRegex(ValueError, "turno inválido"):
            prepare_ronda_orders([{**base, "turno": "B"}])

        for shift in ("A", "C"):
            with self.subTest(shift=shift):
                result = prepare_ronda_orders([{**base, "turno": shift}])
                self.assertEqual(len(result["orders"]), 1)

    def test_round_waits_when_rule_requires_two_runs_per_shift(self):
        rules = {
            "turnos": {"A": {"inicio": "00:00", "fim": "08:00"}},
            "maximo": {"equipamento": "403006100"},
            "rondas": {
                "tanques": {
                    "nome": "Ronda dos tanques operacionais",
                    "aliases": [],
                    "turnos": ["A"],
                    "duracao_minutos": 60,
                    "execucoes_por_turno": 2,
                    "enviar_apos_execucao": 2,
                    "descricao_longa_template": ["{executante} {data} {turno}"],
                },
            },
        }
        item = {
            "id": 81, "ronda": "Ronda dos tanques operacionais", "data": "2026-11-04",
            "turno": "A", "equipe": "NFE", "executantes": [{"nome": "Pessoa", "matricula": "E1"}],
        }

        result = prepare_ronda_orders([item], rules=rules)

        self.assertEqual(result["orders"], [])
        self.assertEqual(result["waiting"][0]["itens"], [81])
        self.assertEqual(result["waiting"][0]["necessarias"], 2)


if __name__ == "__main__":
    unittest.main()
