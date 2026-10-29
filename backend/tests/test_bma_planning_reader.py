import unittest
import unittest.mock
from unittest.mock import Mock, patch

from services.bma_page_monitor import BmaPageMonitor
from services.bma_planning_reader import (
    FalhaGravacao, OtNaoEncontrada, SessaoBmaExpirada, obter_ots_do_cronograma, resultado_ot,
)


def order(wonum, worktype):
    return {"siteid": "RES", "wonum": wonum, "dados": {"worktype": worktype}}


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

    def test_orders_already_planned_in_bma_are_skipped(self):
        historico = [{"numero_ot": "RES1", "situacao": "planejada"}, {"numero_ot": "RES2", "situacao": "erro"}]
        with patch("services.bma_planning_reader.get_plan", return_value=PLAN), \
             patch("services.bma_planning_reader.listar_situacao_envios_bma", return_value=historico), \
             patch("services.bma_planning_reader.Thread") as thread:
            resultado = self.monitor.enviar_planejamento("plano")

        self.assertEqual(resultado["total"], 2)
        self.assertEqual([ot["numero_ot"] for ot in thread.call_args.kwargs["args"][1]], ["RES3", "RES2"])

    def test_schedule_returns_pm_orders_with_planning_per_registration(self):
        self.assertEqual([ot["numero_ot"] for ot in self.ots], ["RES1", "RES3", "RES2"])
        self.assertEqual([ot["tipo"] for ot in self.ots], ["I", "E", "S"])
        self.assertEqual(self.ots[0]["planejamento"], {
            "inicio": "2026-11-03", "fim": "2026-11-05", "sem_matricula": [],
            "atribuicoes": [{"laborcode": "E1", "dia": "2026-11-03"}, {"laborcode": "E2", "dia": "2026-11-05"}],
        })

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
        campos = {"Início planejado": "03/11/2026 00:01", "Final planejado": "05/11/2026 10:00"}
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

    def test_divergent_dates_and_registration_are_replaced_by_plan(self):
        campos = {"Início planejado": "02/11/2026 16:17", "Final planejado": "06/11/2026 16:17"}
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
             patch.object(self.monitor, "extrair_dados_planejamento_ot", return_value=resultado_ot("RES1")):
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[0])

        gravar.assert_called_once()
        preencher.assert_called_once_with(self.monitor_id, unittest.mock.ANY, 1, {"laborcode": "E2", "dia": "2026-11-05"},
                                          matricula=True)
        self.assertEqual(resultado["situacao_consulta"], "planejada")
        self.assertIn("matrícula X9 substituída por E2", resultado["erro"])

    def test_labor_quantity_mismatch_goes_to_planner_without_saving(self):
        grade = {"prefixo": "m1", "colunas": {}, "linhas": [{"quantidade": "2"}]}
        with patch.object(self.monitor, "pesquisar_ot"), \
             patch.object(self.monitor, "_ler_aba_ordem", return_value={"Início planejado": "", "Final planejado": ""}), \
             patch.object(self.monitor, "_ler_grade_aba", return_value=grade), \
             patch.object(self.monitor, "_fill_general_dates") as gravar:
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[2])

        self.assertEqual(resultado["situacao_consulta"], "pendente_planejador")
        self.assertIn("exige 2 pessoa(s) e o cronograma tem 1", resultado["erro"])
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

    def test_corrective_wfsch_overwrites_dates_and_routes_workflow(self):
        campos = {"Início planejado": "29/10/2026 09:05", "Final planejado": "29/10/2026 09:05", "Status da OT": "WFSCH"}
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
             patch.object(self.monitor, "_rotear_workflow_prepared") as rotear, \
             patch.object(self.monitor, "extrair_dados_planejamento_ot", return_value=resultado_ot("RES3")):
            resultado = self.monitor.planejar_ot(self.monitor_id, Mock(), self.ots[1])

        self.assertEqual(resultado["situacao_consulta"], "planejada")
        gravar.assert_called_once()
        preencher.assert_called_once_with(self.monitor_id, unittest.mock.ANY, 0, {"laborcode": "E1", "dia": "2026-11-03"},
                                          matricula=False)
        rotear.assert_called_once()


if __name__ == "__main__":
    unittest.main()
