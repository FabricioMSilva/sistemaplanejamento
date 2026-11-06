import unittest
import unittest.mock
from unittest.mock import Mock, patch

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By

from services.BMAService import BMAServiceError
from services.bma_page_monitor import BmaPageMonitor
from services.bma_planning_reader import (
    PREPARED_STATUS_OPTION, FalhaGravacao, LeituraInterrompida, MatriculaNaoConfirmada,
    OtNaoEncontrada, SessaoBmaExpirada,
    obter_ots_do_cronograma, resultado_ot,
)


def order(wonum, worktype):
    return {"siteid": "RES", "wonum": wonum, "dados": {"worktype": worktype}}


def labor_autocomplete_input(driver, suggestion):
    value = {"text": ""}
    events = []
    field = Mock()
    field.parent = driver
    field.get_attribute.side_effect = lambda name: value["text"] if name == "value" else None

    def send_keys(*keys):
        events.append(keys)
        if keys == (Keys.CONTROL, "a"):
            value["text"] = ""
        elif keys == (Keys.ENTER,):
            value["text"] = suggestion or ""
        elif keys != (Keys.TAB,):
            value["text"] = "".join(keys)

    field.send_keys.side_effect = send_keys
    return field, value, events


PLAN = {
    "ordens": [order("RES1", "I"), order("RES2", "S"), order("RES3", "E")],
    "pessoas": [{"id": "p1", "nome": "Ana", "matricula": "e1"}, {"id": "p2", "nome": "Bia", "matricula": "E2"}],
    "blocos": [
        {"dia": "2026-11-04", "ot": "RES:RES2", "executantes": ["p1"], "horas": 2},
        {"dia": "2026-11-05", "ot": "RES:RES1", "executantes": ["p1", "p2"], "horas": 2},
        {"dia": "2026-11-03", "ot": "RES:RES1", "executantes": ["p1"], "horas": 4},
        {"dia": "2026-11-03", "ot": "RES:RES3", "executantes": ["p1"], "horas": 1},
    ],
    "posicionamentos": [],
}


class BmaPlanningReaderTests(unittest.TestCase):
    def setUp(self):
        self.monitor = BmaPageMonitor()
        with patch("services.bma_planning_reader.get_plan", return_value=PLAN), \
             patch("services.bma_planning_reader.listar_situacao_envios_bma", return_value=[]), \
             patch("services.bma_planning_reader.Thread"):
            self.monitor_id = self.monitor.enviar_planejamento("plano")["monitor_id"]
        with patch("services.bma_planning_reader.get_plan", return_value=PLAN):
            self.ots = obter_ots_do_cronograma("plano")

    def test_assignment_input_targets_dom_textboxes_for_five_rows(self):
        driver = Mock()
        fields = [Mock() for _ in range(5)]
        for field in fields:
            field.is_displayed.return_value = True
            field.is_enabled.return_value = True
        grade = {"prefixo": "m679a95d", "colunas": {"mao de obra": 5}, "linhas": [{} for _ in range(5)]}

        with patch.object(self.monitor, "_switch_to_manage_frame"), \
             patch.object(self.monitor, "_ler_grade", return_value=grade):
            for row, field in enumerate(fields):
                driver.find_elements.return_value = [field]
                result = self.monitor._input_atribuicao(driver, row, "mao de obra")
                driver.find_elements.assert_called_with(
                    By.ID, f"m679a95d_tdrow_[C:5]_txt-tb[R:{row}]",
                )
                self.assertIs(result, field)

    def test_five_laborers_are_filled_in_distinct_assignment_rows(self):
        assignments = [{"laborcode": f"E{index}", "dia": "2026-11-03"} for index in range(1, 6)]
        ot = {
            **self.ots[0],
            "planejamento": {
                **self.ots[0]["planejamento"], "atribuicoes": assignments, "sem_matricula": [],
            },
        }
        preparation = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "5"}]}
        assignment_grid = {"prefixo": "m2", "colunas": {}, "linhas": [
            {"mao de obra": "", "inicio planejado": ""} for _ in range(5)
        ]}
        campos = {"Início planejado": "", "Final planejado": "", "Status da OT": "PREPARED"}

        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparation, assignment_grid, assignment_grid]), \
             patch.object(self.monitor, "_fill_general_dates"), \
             patch.object(self.monitor, "_aguardar_salvamento"), \
             patch.object(self.monitor, "_preencher_atribuicao") as preencher, \
             patch.object(self.monitor, "_salvar_e_aguardar"), \
             patch.object(self.monitor, "_conferir_atribuicoes"), \
             patch.object(self.monitor, "extrair_dados_planejamento_ot",
                          return_value=resultado_ot("RES1", status="PREPARED")):
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), ot)

        self.assertEqual([call.args[2] for call in preencher.call_args_list], [0, 1, 2, 3, 4])
        self.assertEqual([call.args[3]["laborcode"] for call in preencher.call_args_list],
                         ["E1", "E2", "E3", "E4", "E5"])
        self.assertEqual(resultado["situacao_consulta"], "planejada")

    def test_more_than_five_laborers_is_rejected_before_writing(self):
        assignments = [{"laborcode": f"E{index}", "dia": "2026-11-03"} for index in range(1, 7)]
        ot = {
            **self.ots[0],
            "planejamento": {
                **self.ots[0]["planejamento"], "atribuicoes": assignments, "sem_matricula": [],
            },
        }
        preparation = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "6"}]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value={"Início planejado": "", "Final planejado": ""}), \
             patch.object(self.monitor, "_ler_grade_aba", return_value=preparation), \
             patch.object(self.monitor, "_fill_general_dates") as gravar:
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), ot)

        self.assertEqual(resultado["situacao_consulta"], "pendente_planejador")
        self.assertIn("acima do limite automatizado de 5", resultado["erro"])
        gravar.assert_not_called()

    def test_orders_already_planned_in_bma_are_skipped(self):
        historico = [{"numero_ot": "RES1", "situacao": "planejada"}, {"numero_ot": "RES2", "situacao": "erro"}]
        with patch("services.bma_planning_reader.get_plan", return_value=PLAN), \
             patch("services.bma_planning_reader.listar_situacao_envios_bma", return_value=historico), \
             patch("services.bma_planning_reader.Thread") as thread:
            resultado = self.monitor.enviar_planejamento("plano")

        self.assertEqual(resultado["total"], 2)
        self.assertEqual([ot["numero_ot"] for ot in thread.call_args.kwargs["args"][1]], ["RES3", "RES2"])

    def test_reverse_import_starts_read_only_monitor(self):
        candidate_orders = [{"siteid": "RES", "wonum": "RES1"}]
        plan = {"status": "rascunho", "setores": ["RES-TC-NF"], "inicio": "2026-11-01", "fim": "2026-11-30"}
        with patch("services.bma_planning_reader.get_plan", return_value=plan), \
             patch("services.bma_planning_reader.BMAService") as bma_service, \
             patch("services.bma_planning_reader.Thread") as thread:
            result = self.monitor.importar_planejamento_bma("plano")

        state = self.monitor.get(result["monitor_id"])
        self.assertEqual(result["total"], 0)
        self.assertEqual(state["mode"], "planning_import")
        self.assertTrue(state["inspection_only"])
        self.assertEqual(thread.call_args.kwargs["target"], self.monitor._executar_importacao_planejamento_bma)
        self.assertEqual(thread.call_args.kwargs["args"][2:5], (plan["setores"], plan["inicio"], plan["fim"]))
        bma_service.assert_not_called()

    def test_reverse_import_collects_without_applying_to_local_plan(self):
        monitor = BmaPageMonitor()
        with patch("services.bma_page_monitor.Thread"):
            monitor_id, _ = monitor._nova_sessao_bma({
                "mode": "planning_import", "inspection_only": True, "plan_id": "plano",
                "queue_total": 0, "selected_wonums": [], "importadas": [], "import_applied": False,
            }, reutilizar=False)
        driver = Mock()
        read_result = resultado_ot("RES1", dados_adicionais={"atribuicoes": []})
        fresh_order = {
            "siteid": "RES", "wonum": "RES1", "maintenanceshop": "RES-TC-NF",
            "status": "INPRG", "schedstart": "2026-11-04T08:00:00-03:00",
            "schedfinish": "2026-11-04T12:00:00-03:00", "estdur": "4",
        }

        with patch.object(monitor, "iniciar_firefox_bma", return_value=(driver, False)), \
             patch.object(monitor, "acessar_rastreamento_ordem") as access, \
             patch.object(monitor, "pesquisar_ot") as search, \
             patch.object(monitor, "extrair_dados_planejamento_ot", return_value=read_result), \
             patch("services.bma_planning_reader.BMAService") as bma_service, \
             patch("services.bma_planning_reader.import_bma_schedule") as apply_import, \
             patch.object(monitor, "_save_current_order") as save_order, \
             patch.object(monitor, "_fill_general_dates") as fill_dates, \
             patch.object(monitor, "_close_browser"):
            bma_service.return_value.coletar_ots_programadas.return_value = [fresh_order]
            monitor._executar_importacao_planejamento_bma(
                monitor_id, "plano", ["RES-TC-NF"], "2026-11-01", "2026-11-30",
            )

        state = monitor.get(monitor_id)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["importadas"], [])
        self.assertFalse(state["import_applied"])
        self.assertEqual(len(state["resultados"]), 1)
        self.assertIn("Colocar no cronograma", state["message"])
        access.assert_called_once()
        bma_service.return_value.coletar_ots_programadas.assert_called_once()
        search.assert_called_once_with(monitor_id, driver, "RES1")
        self.assertEqual(read_result["status"], "INPRG")
        self.assertEqual(read_result["inicio_planejado"], "2026-11-04T08:00:00-03:00")
        self.assertEqual(read_result["termino_planejado"], "2026-11-04T12:00:00-03:00")
        self.assertEqual(read_result["duracao_planejada"], "4")
        self.assertIs(read_result["ordem_bma"], fresh_order)
        apply_import.assert_not_called()
        save_order.assert_not_called()
        fill_dates.assert_not_called()

    def test_planning_send_opens_visible_firefox_by_default_and_keeps_it_open(self):
        monitor = BmaPageMonitor()
        with patch("services.bma_page_monitor.Thread"):
            monitor_id, _ = monitor._nova_sessao_bma({
                "mode": "planning_send", "inspection_only": False, "plan_id": "plano",
                "selected_wonums": ["RES1"], "queue_total": 1,
            }, reutilizar=False)
        driver = Mock()
        result = resultado_ot("RES1", situacao_consulta="planejada")

        with patch.dict("os.environ") as environment, \
             patch.object(monitor, "iniciar_firefox_bma", return_value=(driver, False)) as start_browser, \
             patch.object(monitor, "acessar_rastreamento_ordem"), \
             patch.object(monitor, "processar_ots_do_cronograma", return_value=[result]), \
             patch.object(monitor, "_close_browser") as close_browser:
            environment.pop("BMA_ENVIO_VISIVEL", None)
            monitor._executar_leitura_planejamento(monitor_id, [{"numero_ot": "RES1"}])

        start_browser.assert_called_once_with(monitor_id, None, headless=False)
        close_browser.assert_not_called()
        self.assertIs(monitor._sessions[monitor_id]["driver"], driver)

    def test_apply_collected_import_updates_local_schedule_once(self):
        monitor = BmaPageMonitor()
        results = [resultado_ot("RES1", dados_adicionais={"atribuicoes": []})]
        with patch.object(monitor, "_nova_sessao_bma", wraps=monitor._nova_sessao_bma):
            monitor_id, _ = monitor._nova_sessao_bma({
                "mode": "planning_import", "plan_id": "plano", "status": "completed",
                "resultados": results, "import_applied": False,
            }, reutilizar=False)
        import_result = {"plano": {"revisao": 2}, "importadas": ["RES1"], "avisos": []}

        with patch("services.bma_planning_reader.import_bma_schedule", return_value=import_result) as apply_import:
            state = monitor.aplicar_importacao_planejamento_bma(monitor_id, "plano")
            repeated = monitor.aplicar_importacao_planejamento_bma(monitor_id, "plano")

        self.assertTrue(state["import_applied"])
        self.assertEqual(state["importadas"], ["RES1"])
        self.assertEqual(state["plan_revision"], 2)
        self.assertEqual(repeated["importadas"], ["RES1"])
        apply_import.assert_called_once_with("plano", results)

    def test_apply_collected_import_rejects_a_read_that_is_still_running(self):
        monitor = BmaPageMonitor()
        monitor_id, _ = monitor._nova_sessao_bma({
            "mode": "planning_import", "plan_id": "plano", "status": "monitoring",
            "resultados": [], "import_applied": False,
        }, reutilizar=False)

        with self.assertRaisesRegex(BMAServiceError, "Aguarde a coleta"):
            monitor.aplicar_importacao_planejamento_bma(monitor_id, "plano")

    def test_schedule_returns_pm_orders_with_planning_per_registration(self):
        self.assertEqual([ot["numero_ot"] for ot in self.ots], ["RES1", "RES3", "RES2"])
        self.assertEqual([ot["tipo"] for ot in self.ots], ["I", "E", "S"])
        self.assertEqual(self.ots[0]["planejamento"], {
            "inicio": "2026-11-03", "fim": "2026-11-05", "sem_matricula": [],
            "atribuicoes": [{"laborcode": "E1", "dia": "2026-11-03"}, {"laborcode": "E2", "dia": "2026-11-05"}],
        })

    def test_labor_registration_is_typed_without_opening_a_lookup(self):
        driver = Mock()
        driver.execute_script.return_value = True
        field, value, events = labor_autocomplete_input(
            driver, "B114376 - CLEITON MARCOS CREPALDE DOS SANTOS",
        )

        def wait_for_condition(_driver, predicate, _timeout, message, error=BMAServiceError):
            result = predicate(driver)
            if not result:
                raise error(message)
            return result

        with patch.object(self.monitor, "_input_atribuicao", return_value=field), \
             patch.object(self.monitor, "_verificar_leitura"), \
               patch.object(BmaPageMonitor, "_wait_maximo_idle"), \
             patch.object(self.monitor, "_aguardar", side_effect=wait_for_condition):
            self.monitor._preencher_celula(
                self.monitor_id, driver, 1, "mao de obra", "B114376",
                lambda text: text.upper().startswith("B114376"),
            )

        self.assertNotIn((Keys.ENTER,), events)
        self.assertIn((Keys.TAB,), events)
        self.assertTrue(value["text"].upper().startswith("B114376"))

    def test_labor_registration_retries_until_confirmed_for_each_row(self):
        for row in range(3):
            with self.subTest(row=row):
                driver = Mock()
                field = Mock()
                values = iter(("", "", "B111132"))

                def wait_for_condition(_driver, predicate, _timeout, message, error=BMAServiceError):
                    result = predicate(_driver)
                    if not result:
                        raise error(message)
                    return result

                with patch.object(self.monitor, "_input_atribuicao", return_value=field), \
                     patch.object(self.monitor, "_input_value", side_effect=lambda _field: next(values)), \
                     patch.object(self.monitor, "_verificar_leitura"), \
                     patch.object(self.monitor, "_replace_input") as replace, \
                     patch.object(self.monitor, "_aguardar", side_effect=wait_for_condition):
                    self.monitor._preencher_celula(
                        self.monitor_id, driver, row, "mao de obra", "B111132",
                        lambda text: text.upper().startswith("B111132"),
                    )

                self.assertEqual(replace.call_count, 3)

    def test_labor_registration_retry_stops_when_interrupted(self):
        driver = Mock()
        field = Mock()
        with patch.object(self.monitor, "_input_atribuicao", return_value=field), \
             patch.object(self.monitor, "_verificar_leitura", side_effect=[None, LeituraInterrompida("parado")]), \
             patch.object(self.monitor, "_replace_input") as replace, \
             patch.object(self.monitor, "_aguardar", side_effect=[field, MatriculaNaoConfirmada("não confirmada")]):
            with self.assertRaises(LeituraInterrompida):
                self.monitor._preencher_celula(
                    self.monitor_id, driver, 1, "mao de obra", "B111132", lambda text: bool(text),
                )

        replace.assert_called_once()

    def test_assignment_grid_adds_rows_until_all_laborers_have_a_row(self):
        driver = Mock()
        add_row = Mock()
        add_row.is_displayed.return_value = True
        add_row.is_enabled.return_value = True
        driver.find_elements.return_value = [add_row]
        grids = [(Mock(), {}, [(Mock(), Mock()) for _ in range(count)]) for count in range(1, 6)]
        result_grid = {"prefixo": "m1", "colunas": {}, "linhas": [{} for _ in range(5)]}
        wait_for_rows = lambda current, condition, timeout, message: condition(current)

        with (
            patch.object(self.monitor, "_verificar_leitura"),
            patch.object(self.monitor, "_switch_to_manage_frame"),
            patch.object(self.monitor, "_click_tab"),
            patch.object(self.monitor, "_find_assignment_grid", side_effect=grids),
            patch.object(self.monitor, "_ler_grade", return_value=result_grid),
            patch.object(self.monitor, "_click_when_idle") as click,
            patch.object(self.monitor, "_aguardar", side_effect=wait_for_rows),
        ):
            grade = self.monitor._garantir_linhas_atribuicao(self.monitor_id, driver, "RES1", 5)

        self.assertEqual(len(grade["linhas"]), 5)
        self.assertEqual(click.call_count, 4)

    def test_save_confirmation_is_handled_while_waiting_for_bma_save(self):
        driver = Mock()
        driver._bma_messages = []
        yes = Mock()
        driver.execute_script.side_effect = [{
            "code": "BMXAA2300I",
            "text": "Deseja salvar as mudanças antes de continuar? Cancelar Não Sim",
            "yes": yes,
        }, None]
        save_button = Mock()
        save_button.get_attribute.side_effect = lambda name: "true" if name == "disabled" else None
        driver.find_element.return_value = save_button

        def wait_for_save(_driver, predicate, _timeout, message):
            for _ in range(2):
                if predicate(driver):
                    return True
            raise BMAServiceError(message)

        with patch("services.bma_planning_reader.BMAService", return_value=Mock(timeout=1)), \
             patch.object(self.monitor, "_verificar_leitura"), \
             patch.object(self.monitor, "_switch_to_manage_frame"), \
             patch.object(self.monitor, "_aguardar", side_effect=wait_for_save):
            self.monitor._aguardar_salvamento(self.monitor_id, driver, "atribuições da OT RES6782151")

        yes.click.assert_called_once_with()
        self.assertEqual(driver._bma_messages, ["BMXAA2300I respondida com Sim"])
        driver.find_element.assert_called_once()

    def test_order_results_are_saved_and_processing_continues(self):
        def planejar(_monitor_id, _driver, ot):
            if ot["numero_ot"] == "RES1":
                raise OtNaoEncontrada("OT RES1 não encontrada em Rastrear Ordem de Trabalho.")
            return resultado_ot("RES2", situacao_consulta="pendente_planejador", erro="Quantidade divergente.")

        with patch.object(self.monitor, "planejar_ot", side_effect=planejar), \
             patch.object(self.monitor, "_salvar_captura", return_value=None), \
             patch("services.bma_planning_reader.registrar_envio_bma") as historico:
            resultados = self.monitor.processar_ots_do_cronograma(self.monitor_id, Mock(), self.ots[:3:2])

        self.assertEqual([r["situacao_consulta"] for r in resultados], ["nao_encontrada", "pendente_planejador"])
        state = self.monitor.get(self.monitor_id)
        self.assertEqual((state["processadas"], state["pendentes"], state["com_erro"]), (2, 1, 1))
        self.assertEqual(historico.call_count, 2)
        self.assertEqual(historico.call_args.args[:2], (self.monitor_id, "plano"))

    def test_labor_shortage_retries_only_after_schedule_assignments_change(self):
        original = {
            "numero_ot": "RES3", "cronograma": {},
            "planejamento": {"atribuicoes": [{"laborcode": "E1"}]},
        }
        updated = {
            "numero_ot": "RES3", "cronograma": {}, "planejamento": {"atribuicoes": [
                {"laborcode": "E1"}, {"laborcode": "E2"},
            ]},
        }
        shortage = resultado_ot("RES3", situacao_consulta="pendente_planejador", erro="Quantidade divergente.",
                                requisitos_mao_de_obra=[{"especialidade": "300", "quantidade": 2}])
        planned = resultado_ot("RES3", situacao_consulta="planejada")
        with patch.object(self.monitor, "planejar_ot", side_effect=[shortage, planned]) as planejar, \
             patch("services.bma_planning_reader.obter_ots_do_cronograma", return_value=[updated]), \
             patch("services.bma_planning_reader.registrar_envio_bma") as historico:
            resultados = self.monitor.processar_ots_do_cronograma(self.monitor_id, Mock(), [original])

        self.assertEqual([item["situacao_consulta"] for item in resultados], ["planejada"])
        self.assertEqual(planejar.call_args_list[1].args[2], updated)
        self.assertEqual(historico.call_count, 2)

    def test_labor_shortage_is_not_retried_without_new_assignment(self):
        original = {
            "numero_ot": "RES3", "cronograma": {},
            "planejamento": {"atribuicoes": [{"laborcode": "E1"}]},
        }
        shortage = resultado_ot("RES3", situacao_consulta="pendente_planejador", erro="Quantidade divergente.",
                                requisitos_mao_de_obra=[{"especialidade": "300", "quantidade": 2}])
        with patch.object(self.monitor, "planejar_ot", return_value=shortage) as planejar, \
             patch("services.bma_planning_reader.obter_ots_do_cronograma", return_value=[original]):
            resultados = self.monitor.processar_ots_do_cronograma(self.monitor_id, Mock(), [original])

        self.assertEqual(resultados[0]["situacao_consulta"], "pendente_planejador")
        planejar.assert_called_once()

    def test_write_failure_is_recorded_and_queue_continues_after_recovery(self):
        with patch.object(self.monitor, "planejar_ot",
                          side_effect=[FalhaGravacao("OT RES1: falha ao gravar"), resultado_ot("RES3", situacao_consulta="planejada")]), \
             patch.object(self.monitor, "_salvar_captura", return_value=None), \
             patch.object(self.monitor, "acessar_rastreamento_ordem") as recuperar, \
             patch("services.bma_planning_reader.registrar_envio_bma") as historico:
            resultados = self.monitor.processar_ots_do_cronograma(self.monitor_id, Mock(), self.ots[:2])

        self.assertEqual([r["situacao_consulta"] for r in resultados], ["erro", "planejada"])
        recuperar.assert_called_once()
        self.assertEqual(historico.call_count, 2)

    def test_expired_session_reauthenticates_and_retries_same_order(self):
        with patch.object(self.monitor, "planejar_ot",
                          side_effect=[SessaoBmaExpirada("expirou"), resultado_ot("RES1", situacao_consulta="planejada")]), \
             patch.object(self.monitor, "acessar_rastreamento_ordem") as acessar, \
             patch("services.bma_planning_reader.registrar_envio_bma"):
            resultados = self.monitor.processar_ots_do_cronograma(self.monitor_id, Mock(), self.ots[:1])

        acessar.assert_called_once()
        self.assertEqual(resultados[0]["situacao_consulta"], "planejada")

    def test_order_already_matching_plan_is_not_changed(self):
        campos = {
            "Início planejado": "03/11/2026 00:01", "Final planejado": "05/11/2026 23:59",
            "Status da OT": "PREPARED",
        }
        preparacao = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "2"}]}
        atribuicoes = {"prefixo": "m2", "colunas": {}, "linhas": [
            {"mao de obra": "E2", "inicio planejado": "05/11/2026 00:01"},
            {"mao de obra": "E1", "inicio planejado": "03/11/2026 00:01"},
        ]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparacao, atribuicoes]), \
             patch.object(self.monitor, "_fill_general_dates") as gravar:
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[0])

        self.assertEqual(resultado["situacao_consulta"], "ja_planejada")
        gravar.assert_not_called()

    def test_in_progress_order_with_dates_and_executor_is_not_rewritten(self):
        campos = {
            "Início planejado": "03/11/2026 00:01", "Final planejado": "05/11/2026 23:59",
            "Status da OT": "INPRG",
        }
        atribuicoes = {"prefixo": "m1", "colunas": {}, "linhas": [
            {"mao de obra": "E1", "inicio planejado": "03/11/2026 00:01"},
        ]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_ler_grade_aba", return_value=atribuicoes), \
             patch.object(self.monitor, "_fill_general_dates") as gravar, \
             patch.object(self.monitor, "_preencher_atribuicao") as preencher:
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[0])

        self.assertEqual(resultado["situacao_consulta"], "ja_planejada")
        self.assertEqual(resultado["status"], "INPRG")
        gravar.assert_not_called()
        preencher.assert_not_called()

    def test_divergent_dates_and_registration_are_replaced_by_plan(self):
        campos = {
            "Início planejado": "02/11/2026 16:17", "Final planejado": "06/11/2026 16:17",
            "Status da OT": "PREPARED",
        }
        preparacao = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "2"}]}
        atribuicoes = {"prefixo": "m2", "colunas": {}, "linhas": [
            {"mao de obra": "E1", "inicio planejado": "03/11/2026 00:01"},
            {"mao de obra": "X9", "inicio planejado": ""},
        ]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparacao, atribuicoes, atribuicoes]), \
             patch.object(self.monitor, "_fill_general_dates") as gravar, \
             patch.object(self.monitor, "_aguardar_salvamento"), \
             patch.object(self.monitor, "_preencher_atribuicao") as preencher, \
             patch.object(self.monitor, "_salvar_e_aguardar"), \
             patch.object(self.monitor, "_conferir_atribuicoes"), \
             patch.object(self.monitor, "extrair_dados_planejamento_ot",
                          return_value=resultado_ot("RES1", status="PREPARED")):
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[0])

        gravar.assert_called_once()
        preencher.assert_called_once_with(self.monitor_id, unittest.mock.ANY, 1, {"laborcode": "E2", "dia": "2026-11-05"},
                                          matricula=True)
        self.assertEqual(resultado["situacao_consulta"], "planejada")
        self.assertIn("matrícula X9 substituída por E2", resultado["erro"])

    def test_existing_dates_and_crew_are_not_rewritten(self):
        campos = {
            "Início planejado": "03/11/2026 00:01", "Final planejado": "03/11/2026 04:01",
            "Status da OT": "PREPARED",
        }
        preparacao = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "2"}]}
        atribuicoes = {"prefixo": "m2", "colunas": {}, "linhas": [
            {"mao de obra": "E1", "inicio planejado": "03/11/2026 00:01"},
            {"mao de obra": "E2", "inicio planejado": "05/11/2026 00:01"},
        ]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparacao, atribuicoes, atribuicoes]), \
             patch.object(self.monitor, "_fill_general_dates") as gravar, \
             patch.object(self.monitor, "_aguardar_salvamento"), \
             patch.object(self.monitor, "_conferir_atribuicoes"), \
             patch.object(self.monitor, "extrair_dados_planejamento_ot",
                          return_value=resultado_ot("RES1", status="PREPARED")):
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[0])

        gravar.assert_not_called()
        self.assertEqual(resultado["situacao_consulta"], "ja_planejada")

    def test_non_prepared_final_status_is_not_marked_as_planned(self):
        campos = {
            "Início planejado": "", "Final planejado": "",
            "Status da OT": "PREPARED",
        }
        preparacao = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "2"}]}
        atribuicoes = {"prefixo": "m2", "colunas": {}, "linhas": [
            {"mao de obra": "E1", "inicio planejado": "03/11/2026 00:01"},
            {"mao de obra": "E2", "inicio planejado": "05/11/2026 00:01"},
        ]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparacao, atribuicoes]), \
             patch.object(self.monitor, "_fill_general_dates"), \
             patch.object(self.monitor, "_aguardar_salvamento"), \
             patch.object(self.monitor, "_conferir_atribuicoes"), \
             patch.object(self.monitor, "extrair_dados_planejamento_ot",
                          return_value=resultado_ot("RES1", status="WAPPR")):
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[0])

        self.assertEqual(resultado["situacao_consulta"], "pendente_planejador")
        self.assertIn("status final WAPPR não é PREPARED", resultado["erro"])

    def test_labor_quantity_mismatch_goes_to_planner_without_saving(self):
        grade = {"prefixo": "m1", "colunas": {}, "linhas": [{
            "especialidade": "300", "quantidade": "2", "horas normais": "5,83",
        }]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value={"Início planejado": "", "Final planejado": ""}), \
             patch.object(self.monitor, "_ler_grade_aba", return_value=grade), \
             patch.object(self.monitor, "_fill_general_dates") as gravar:
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[2])

        self.assertEqual(resultado["situacao_consulta"], "pendente_planejador")
        self.assertIn("exige 2 pessoa(s) e o cronograma tem 1", resultado["erro"])
        self.assertEqual(resultado["requisitos_mao_de_obra"], [{
            "especialidade": "300", "orgid": "", "quantidade": 2, "horas_normais": "5,83",
        }])
        gravar.assert_not_called()

    def test_assignment_row_mismatch_keeps_preparation_requirements(self):
        preparation = {"prefixo": "m1", "colunas": {}, "linhas": [{
            "especialidade": "300", "quantidade": "1", "horas normais": "5,83",
        }]}
        assignment = {"prefixo": "m2", "colunas": {}, "linhas": []}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value={"Início planejado": "", "Final planejado": ""}), \
             patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparation, assignment]), \
             patch.object(self.monitor, "_garantir_linhas_atribuicao", side_effect=BMAServiceError("botão New Row ausente")) as add_row, \
             patch.object(self.monitor, "_fill_general_dates") as gravar:
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[2])

        self.assertEqual(resultado["situacao_consulta"], "pendente_planejador")
        self.assertIn("botão New Row ausente", resultado["erro"])
        self.assertEqual(resultado["requisitos_mao_de_obra"], [{
            "especialidade": "300", "orgid": "", "quantidade": 1, "horas_normais": "5,83",
        }])
        add_row.assert_called_once()
        gravar.assert_not_called()

    def test_corrective_with_other_status_is_not_changed(self):
        campos = {"Início planejado": "", "Final planejado": "", "Status da OT": "APPR"}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_fill_general_dates") as gravar:
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[1])

        self.assertEqual(resultado["situacao_consulta"], "pendente_planejador")
        self.assertIn("APPR", resultado["erro"])
        gravar.assert_not_called()

    def test_completed_pm_is_not_rewritten(self):
        campos = {"Início planejado": "", "Final planejado": "", "Status da OT": "COMP"}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_fill_general_dates") as gravar:
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[1])

        self.assertEqual(resultado["situacao_consulta"], "pendente_planejador")
        self.assertEqual(resultado["status"], "COMP")
        self.assertIn("não será alterada", resultado["erro"])
        gravar.assert_not_called()

    def test_planning_date_comes_from_planned_start_not_execution_window(self):
        campos = {
            "Início planejado": "03/11/2026 00:01",
            "Final planejado": "03/11/2026 03:01",
            "Não iniciar antes de": "01/11/2026 11:00",
            "Terminar antes de": "03/11/2026 11:00",
        }
        with patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_aguardar", return_value=("ok", [])):
            resultado = self.monitor.extrair_dados_planejamento_ot(self.monitor_id, Mock(), "RES1")

        self.assertEqual(resultado["data_planejada"], "03/11/2026")
        self.assertEqual(resultado["janela_execucao"], "01/11/2026 11:00 a 03/11/2026 11:00")

    def test_corrective_wfsch_overwrites_dates_and_routes_workflow(self):
        campos = {"Início planejado": "", "Final planejado": "", "Status da OT": "WFSCH"}
        preparacao = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "1"}]}
        atribuicoes = {"prefixo": "m2", "colunas": {}, "linhas": [{"mao de obra": "E1"}]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
             patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparacao, atribuicoes, atribuicoes]), \
             patch.object(self.monitor, "_fill_general_dates") as gravar, \
             patch.object(self.monitor, "_aguardar_salvamento"), \
             patch.object(self.monitor, "_preencher_atribuicao") as preencher, \
             patch.object(self.monitor, "_salvar_e_aguardar"), \
             patch.object(self.monitor, "_conferir_atribuicoes"), \
             patch.object(self.monitor, "_alterar_status_prepared") as rotear, \
             patch.object(self.monitor, "extrair_dados_planejamento_ot",
                          return_value=resultado_ot("RES3", status="PREPARED")):
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[1])

        self.assertEqual(resultado["situacao_consulta"], "planejada")
        gravar.assert_called_once()
        preencher.assert_called_once_with(self.monitor_id, unittest.mock.ANY, 0, {"laborcode": "E1", "dia": "2026-11-03"},
                                          matricula=False)
        rotear.assert_called_once()

    def test_preventive_wfsch_and_wsch_are_routed_to_prepared(self):
        preparacao = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "2"}]}
        atribuicoes = {"prefixo": "m2", "colunas": {}, "linhas": [
            {"mao de obra": "E1", "inicio planejado": "03/11/2026 00:01"},
            {"mao de obra": "E2", "inicio planejado": "05/11/2026 00:01"},
        ]}
        for status in ("WFSCH", "WSCH"):
            with self.subTest(status=status):
                campos = {
                    "Início planejado": "",
                    "Final planejado": "",
                    "Status da OT": status,
                }
                with patch.object(self.monitor, "pesquisar_ot"), \
                     patch.object(self.monitor, "_ler_aba_ordem", return_value=campos), \
                     patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparacao, atribuicoes]), \
                     patch.object(self.monitor, "_fill_general_dates"), \
                     patch.object(self.monitor, "_aguardar_salvamento"), \
                     patch.object(self.monitor, "_preencher_atribuicao") as preencher, \
                     patch.object(self.monitor, "_conferir_atribuicoes"), \
                     patch.object(self.monitor, "_alterar_status_prepared") as rotear, \
                     patch.object(self.monitor, "extrair_dados_planejamento_ot",
                                  return_value=resultado_ot("RES1", status="PREPARED")):
                    resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[0])

                self.assertEqual(resultado["situacao_consulta"], "planejada")
                self.assertEqual(resultado["status"], "PREPARED")
                preencher.assert_not_called()
                rotear.assert_called_once_with(self.monitor_id, unittest.mock.ANY, "RES1")

    def test_complete_order_is_planned_without_status_change(self):
        preparacao = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "2"}]}
        atribuicoes = {"prefixo": "m2", "colunas": {}, "linhas": [
            {"mao de obra": "E1", "inicio planejado": ""},
            {"mao de obra": "E2", "inicio planejado": ""},
        ]}
        for status in ("PREPARED", "WFSCH", "WSCH"):
            with self.subTest(status=status), \
                 patch.object(self.monitor, "pesquisar_ot"), \
                 patch.object(self.monitor, "_ler_aba_ordem", return_value={
                     "Início planejado": "03/11/2026 10:00",
                     "Final planejado": "05/11/2026 12:00", "Status da OT": status,
                 }), \
                 patch.object(self.monitor, "_ler_grade_aba", side_effect=[preparacao, atribuicoes]), \
                 patch.object(self.monitor, "_fill_general_dates") as gravar, \
                 patch.object(self.monitor, "_preencher_atribuicao") as preencher, \
                 patch.object(self.monitor, "_alterar_status_prepared") as alterar:
                resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[0])

            self.assertEqual(resultado["situacao_consulta"], "ja_planejada")
            self.assertEqual(resultado["status"], status)
            gravar.assert_not_called()
            preencher.assert_not_called()
            alterar.assert_not_called()

    def test_prepared_status_menu_confirms_dialog_and_checks_result(self):
        driver = Mock()
        status_action, confirm = Mock(), Mock()
        status_action.is_displayed.return_value = True
        status_action.is_enabled.return_value = True
        confirm.is_displayed.return_value = True
        confirm.text = "OK"
        driver.find_elements.side_effect = ([status_action], [confirm])
        fields = iter(({"Novo status": "Prepared"}, {"Status da OT": "PREPARED"}))

        def wait_for_condition(_driver, condition, _timeout, message):
            result = condition(_driver)
            if not result:
                raise BMAServiceError(message)
            return result

        with patch.object(self.monitor, "_verificar_leitura"), \
             patch.object(self.monitor, "_switch_to_manage_frame"), \
             patch.object(self.monitor, "_ler_campos_rotulados", side_effect=lambda _driver: next(fields)), \
             patch.object(self.monitor, "_click_when_idle") as click, \
             patch.object(self.monitor, "_aguardar", side_effect=wait_for_condition):
            self.monitor._alterar_status_prepared(self.monitor_id, driver, "RES1")

        self.assertEqual(driver.find_elements.call_args_list[0].args, (By.CSS_SELECTOR, PREPARED_STATUS_OPTION))
        self.assertEqual(driver.find_elements.call_args_list[1].args, (By.XPATH, "//*[@role='button' or self::button]"))
        self.assertEqual(click.call_args_list, [unittest.mock.call(driver, status_action), unittest.mock.call(driver, confirm)])


if __name__ == "__main__":
    unittest.main()
