import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException

import backend.models.database as database
from backend.models.workforce_identity import vincular_ativos
from backend.services.BMAService import BMAService, BMAServiceError
from backend.services.labor_planning import calcular_equipe
from backend.services.nf_workforce import coletar_ativos
from backend.tests.test_labor_planning import cadastro, executante, plano
from backend.tests.test_mao_de_obra import profissional


class WorkforceIdentityTests(unittest.TestCase):
    def test_exact_names_ignore_case_accents_but_never_abbreviate(self):
        people = [{"orgid": "BR", "matricula": "E1", "nome": "João da Silva"}]
        exact = vincular_ativos([{"id": 1, "nome": "JOAO DA SILVA"}], people, {})
        self.assertEqual(len(exact["vinculados"]), 1)
        abbreviated = vincular_ativos([{"id": 1, "nome": "Joao Silva"}], people, {})
        self.assertEqual(len(abbreviated["pendentes"]), 1)

    def test_duplicate_names_or_multiple_roster_rows_do_not_link(self):
        person = {"orgid": "BR", "matricula": "E1", "nome": "Joao Silva"}
        roster = [{"id": 1, "nome": "Joao Silva"}]
        self.assertEqual(vincular_ativos(roster, [person, {**person, "matricula": "E2"}], {})["vinculados"], [])
        self.assertEqual(vincular_ativos(roster + [{**roster[0], "id": 2}], [person], {})["vinculados"], [])

    def test_matricula_or_confirmed_mapping_preserves_bma_identity(self):
        people = [{"orgid": "BR", "matricula": "E1", "personid": "P1", "nome": "Nome completo"}]
        for row, mappings in (
            ({"id": 1, "nome": "Abreviado", "matricula": "e1"}, {}),
            ({"id": 1, "nome": "Abreviado"}, {"1": {"orgid": "BR", "matricula": "E1"}}),
        ):
            self.assertEqual(vincular_ativos([row], people, mappings)["vinculados"][0]["matricula_bma"], "E1")
        self.assertEqual(vincular_ativos([row], [], mappings)["vinculados"], [])

    def test_sharepoint_pagination_and_invalid_responses(self):
        driver = Mock()
        driver.current_url = "https://michelingroup.sharepoint.com/sites/NF-RES/Lists/ListaFuncionario/AllItems.aspx"
        driver.execute_async_script.side_effect = [
            {"data": {"value": [{"ID": 1, "Nome": "Pessoa"}], "odata.nextLink": "?page=2"}},
            {"data": {"value": [{"ID": 2, "Nome": "Outra"}]}},
        ]
        self.assertEqual(len(coletar_ativos(driver, 1)), 2)
        for payload in ({"data": {"value": []}}, {"error": "HTTP 401"},
                        {"data": {"value": [{"ID": 1, "Nome": ""}]}},
                        {"data": {"value": [{"ID": 1, "Nome": "Pessoa"}], "odata.nextLink": "https://other.example/items"}}):
            driver.execute_async_script.side_effect = None
            driver.execute_async_script.return_value = payload
            with self.subTest(payload=payload), self.assertRaises(BMAServiceError):
                coletar_ativos(driver, 1)

    def test_dedicated_refresh_never_collects_orders_and_propagates_sp_failure(self):
        service = BMAService()
        with (patch.object(service, "_create_browser") as browser,
              patch.object(service, "_wait_for_work_tracking"),
              patch.object(service, "_collect_labor", return_value=[profissional()]),
              patch("backend.services.nf_workforce.coletar_ativos", side_effect=BMAServiceError("SP failed"))):
            with self.assertRaisesRegex(BMAServiceError, "SP failed"):
                service.atualizar_mao_de_obra(True)
            browser.return_value.quit.assert_called_once()


class WorkforcePersistenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        change = patch.object(database, "DB_PATH", Path(temp.name) / "test.db")
        change.start()
        self.addCleanup(change.stop)
        database.init_db()

    def test_nf_requires_roster_then_filters_dismissed_and_unmatched(self):
        sectors = ["RES-TC-NF"]
        labor = [profissional(fullname="Ativo"), profissional("OLD", fullname="Demitido"),
                 profissional("NFE", fullname="Nome completo", worklocation="NFE", maintenanceshop="RES-OTHER")]
        database.salvar_planejamento([], sectors, labor)
        self.assertEqual(database.listar_mao_de_obra(sectors)["total"], 0)
        database.salvar_planejamento([], sectors, labor, roster=[{"id": 1, "nome": "Ativo"}, {"id": 2, "nome": "Nome"}])
        self.assertEqual(database.listar_mao_de_obra(sectors)["total"], 1)
        database.salvar_vinculo_nf(sectors, 2, "BR", "NFE")
        result = database.listar_mao_de_obra(sectors)
        self.assertEqual({p["matricula"] for p in result["profissionais"]}, {"TEST1", "NFE"})
        self.assertEqual(result["verificacao_nf"]["pendentes"], 0)
        with self.assertRaises(ValueError):
            database.salvar_vinculo_nf(sectors, 2, "BR", "TEST1")
        # Disappearance from SharePoint invalidates even previously confirmed mappings.
        database.salvar_planejamento([], sectors, labor, roster=[{"id": 1, "nome": "Ativo"}])
        self.assertEqual(database.listar_mao_de_obra(sectors)["total"], 1)
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM nf_vinculos").fetchone()[0], 0)

    def test_invalid_roster_rolls_back_the_new_bma_snapshot(self):
        database.salvar_planejamento([], ["RES-TC-NF"], [profissional()],
                                   roster=[{"id": 1, "nome": "Profissional de teste"}])
        before = database.listar_mao_de_obra(["RES-TC-NF"])
        for roster in ([], [{"id": 1, "nome": "One"}, {"id": 1, "nome": "Two"}]):
            with self.subTest(roster=roster), self.assertRaises(ValueError):
                database.salvar_planejamento([], ["RES-TC-NF"], [profissional("NEW")], roster=roster)
        self.assertEqual(database.listar_mao_de_obra(["RES-TC-NF"]), before)

    def test_mixed_sectors_preserve_non_nf_candidates(self):
        database.salvar_planejamento([], ["RES-TC-NF"], [
            profissional(), profissional("NC", maintenanceshop="RES-TC-NC"),
        ], roster=[{"id": 1, "nome": "Outra pessoa"}])
        result = database.listar_mao_de_obra(["RES-TC-NF", "RES-TC-NC"])
        self.assertEqual([p["matricula"] for p in result["profissionais"]], ["NC"])

    def test_nf_crosses_all_res_without_maintenance_sector_or_worklocation_filter(self):
        sectors = ["RES-TC-NF"]
        database.salvar_planejamento([], sectors, [
            profissional("OUT", fullname="Pessoa de outro setor", maintenanceshop="RES-OTHER", worklocation="OUTRO"),
            profissional("NO", fullname="Fora da lista", maintenanceshop="RES-TC-NF"),
            profissional("ABBR", fullname="Outro Nome Completo", maintenanceshop="", worklocation=""),
        ], roster=[{"id": 1, "nome": "Pessoa de outro setor"}, {"id": 2, "nome": "Outro Nome"}])
        self.assertEqual(len(database.conferencia_nf(sectors)["candidatos"]), 3)
        database.salvar_vinculo_nf(sectors, 2, "BR", "ABBR")
        result = database.listar_mao_de_obra(sectors)
        self.assertEqual({p["matricula"] for p in result["profissionais"]}, {"OUT", "ABBR"})
        plan = plano(executantes=[executante("OUT", capacidade="dias_8h", dias_disponiveis=["2026-11-02"])])
        self.assertEqual(calcular_equipe(plan, result)["total_horas"], 8)

    def test_history_retains_exactly_ten_per_normalized_sector_group(self):
        for index in range(12):
            data = plano(planejador=f"Planner {index}").model_dump(mode="json")
            database.salvar_equipe(data)
        rows = database.listar_historico(["res-tc-nf"])
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["planejamento"]["planejador"], "Planner 11")
        self.assertEqual(rows[-1]["planejamento"]["planejador"], "Planner 2")
        self.assertEqual(database.listar_historico(["RES-TC-NC"]), [])
        database.init_db()
        self.assertEqual(len(database.listar_historico(["RES-TC-NF"])), 10)

    def test_defaults_are_isolated_by_planner_and_sector(self):
        data = plano(planejador="Planner").model_dump(mode="json")
        database.equipe_padrao(data["setores"], " Planner ", data)
        self.assertEqual(database.equipe_padrao(["res-tc-nf"], "PLANNER"), data)
        self.assertIsNone(database.equipe_padrao(["RES-TC-NF"], "OTHER"))
        self.assertIsNone(database.equipe_padrao(["RES-TC-NC"], "Planner"))
        self.assertEqual(database.listar_historico(data["setores"]), [])


class WorkforceAvailabilityTests(unittest.TestCase):
    def test_current_eight_hour_rule_for_every_journey(self):
        for journey, team in (("adm", None), ("equipe", 1), ("16-00", None)):
            plan = plano(inicio="2026-11-03", fim="2026-11-03", executantes=[executante(
                jornada=journey, equipe=team, capacidade="dias_8h", dias_disponiveis=["2026-11-03"],
            )])
            result = calcular_equipe(plan, cadastro())
            self.assertEqual(result["total_horas"], 8)
            self.assertEqual(result["executantes"][0]["dias"], 1)
        with self.assertRaises(ValueError):
            plano(executantes=[executante(capacidade="dias_8h", dias_disponiveis=["2026-11-03"], ajuste_horas=8)])

    def test_available_days_always_count_six_hours_including_weekends_and_specials(self):
        for journey, team in (("adm", None), ("equipe", 1), ("16-00", None)):
            plan = plano(executantes=[executante(jornada=journey, equipe=team,
                capacidade="dias_6h", dias_disponiveis=["2026-11-01", "2026-11-03", "2026-11-05"])])
            result = calcular_equipe(plan, cadastro())
            self.assertEqual(result["total_horas"], 18)
            self.assertEqual(result["executantes"][0]["dias"], 3)
        plan = plano(inicio="2027-01-02", fim="2027-01-03", executantes=[
            executante(jornada="equipe", equipe=2, capacidade="dias_6h", dias_disponiveis=["2027-01-02"]),
        ])
        self.assertEqual(calcular_equipe(plan, cadastro())["total_horas"], 6)
        plan = plano(executantes=[executante(capacidade="dias_6h", dias_disponiveis=[])])
        self.assertEqual(calcular_equipe(plan, cadastro())["total_horas"], 0)

    def test_available_days_reject_unknown_duplicates_outside_period_and_manual_hours(self):
        for change in (
            {"dias_disponiveis": None}, {"dias_disponiveis": ["2026-11-02", "2026-11-02"]},
            {"dias_disponiveis": ["2026-11-09"]}, {"dias_disponiveis": ["2026-02-30"]},
            {"ajuste_horas": 1}, {"ausencias": ["2026-11-02"]},
            {"ajustes_datas": {"2026-11-03": 8}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                values = {"capacidade": "dias_6h", "dias_disponiveis": ["2026-11-02"], **change}
                plano(executantes=[executante(**values)])

    def test_absences_remove_workdays_not_rest_and_override_specials(self):
        plan = plano(executantes=[executante(ausencias=["2026-11-02", "2026-11-08"])])
        result = calcular_equipe(plan, cadastro())
        self.assertEqual(result["total_horas"], 24)
        self.assertEqual(result["executantes"][0]["dias"], 4)
        plan = plano(executantes=[executante(jornada="equipe", equipe=1,
                     ausencias=["2026-11-03", "2026-11-05"], ajustes_datas={})])
        self.assertEqual(calcular_equipe(plan, cadastro())["total_horas"], 32)
        plan = plano(executantes=[executante(jornada="08-16", inicio_ciclo="2026-11-01",
                                            ausencias=["2026-11-02", "2026-11-07"])])
        self.assertEqual(calcular_equipe(plan, cadastro())["total_horas"], 40)

    def test_invalid_absence_dates_duplicates_and_outside_period_rejected(self):
        for days in (["2026-11-02", "2026-11-02"], ["2026-10-31"], ["2026-02-30"]):
            with self.subTest(days=days), self.assertRaises(ValueError):
                plano(executantes=[executante(ausencias=days)])


class WorkforceApiTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        self.addCleanup(lambda: sys.path.remove(str(Path(__file__).resolve().parents[1])))
        from api import routes
        import models.database as api_database
        self.routes = routes
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        change = patch.object(api_database, "DB_PATH", Path(temp.name) / "test.db")
        change.start()
        self.addCleanup(change.stop)
        api_database.init_db()
        self.db = api_database
    def refresh(self):
        tasks = BackgroundTasks()
        result = self.routes.atualizar_mao_de_obra(
            self.routes.SincronizarOtsPayload(setores=["RES-TC-NF"]), tasks,
        )
        asyncio.run(tasks())
        return result

    def test_ots_sync_does_not_refresh_labor(self):
        self.db.criar_sincronizacao("ots", ["RES-TC-NF"])
        with (patch.object(self.routes.bma_service, "listar_ots_por_setor", return_value=[]) as collect,
              patch.object(self.routes.bma_service, "atualizar_mao_de_obra") as labor):
            self.routes._executar_sincronizacao("ots", ["RES-TC-NF"])
            collect.assert_called_once()
            labor.assert_not_called()
        self.assertIsNone(self.db.listar_mao_de_obra()["sincronizado_em"])

    def test_manual_refresh_success_failure_and_conflict(self):
        with patch.object(self.routes.bma_service, "atualizar_mao_de_obra", return_value=(
            [profissional()], [{"id": 1, "nome": "Profissional de teste"}],
        )):
            response = self.refresh()
        self.assertEqual(self.db.obter_sincronizacao(response["job_id"])["status"], "completed")
        self.assertEqual(self.db.listar_mao_de_obra(["RES-TC-NF"])["total"], 1)
        self.assertIsNone(self.db.obter_ultima_sincronizacao())
        with patch.object(self.routes.bma_service, "atualizar_mao_de_obra", side_effect=BMAServiceError("SP down")):
            failed = self.refresh()
        self.assertEqual(self.db.obter_sincronizacao(failed["job_id"])["status"], "failed")
        self.assertEqual(self.db.listar_mao_de_obra(["RES-TC-NF"])["total"], 1)
        self.routes.labor_refresh_lock.acquire()
        try:
            with self.assertRaises(HTTPException) as conflict:
                self.refresh()
            self.assertEqual(conflict.exception.status_code, 409)
        finally:
            self.routes.labor_refresh_lock.release()

    def test_save_revalidates_active_roster_and_templates_clear_period_values(self):
        self.db.salvar_planejamento([], ["RES-TC-NF"], [profissional()],
                                   roster=[{"id": 1, "nome": "Profissional de teste"}])
        data = plano(planejador="Planner", executantes=[executante(
            ausencias=["2026-11-02"], ajuste_horas=-1,
        )]).model_dump(mode="json")
        result = self.routes.gravar_equipe(self.routes.PlanejamentoEquipe.model_validate(data))
        self.assertEqual(result["resumo"]["total_horas"], 23)
        self.assertEqual(len(self.db.listar_historico(data["setores"])), 1)
        response = self.routes.gravar_padrao(self.routes.PlanejamentoEquipe.model_validate(data))
        self.assertEqual(response["executantes"][0]["ausencias"], [])
        self.assertEqual(response["executantes"][0]["ajuste_horas"], 0)
        data["planejador"] = ""
        with self.assertRaises(HTTPException) as missing_name:
            self.routes.gravar_equipe(self.routes.PlanejamentoEquipe.model_validate(data))
        self.assertEqual(missing_name.exception.status_code, 400)
        data["planejador"] = "Planner"
        self.db.salvar_planejamento([], data["setores"], [profissional()],
                                   roster=[{"id": 2, "nome": "Outra pessoa"}])
        with self.assertRaises(HTTPException) as inactive:
            self.routes.gravar_equipe(self.routes.PlanejamentoEquipe.model_validate(data))
        self.assertEqual(inactive.exception.status_code, 400)

    def test_six_hour_days_save_history_and_default_without_dates(self):
        self.db.salvar_planejamento([], ["RES-TC-NF"], [profissional()],
                                   roster=[{"id": 1, "nome": "Profissional de teste"}])
        payload = self.routes.PlanejamentoEquipe.model_validate({
            "setores": ["RES-TC-NF"], "inicio": "2026-11-01", "fim": "2026-11-08",
            "planejador": "Planner", "executantes": [executante(
                jornada="equipe", equipe=1, capacidade="dias_6h",
                dias_disponiveis=["2026-11-01", "2026-11-03", "2026-11-07"],
            )],
        })
        result = self.routes.gravar_equipe(payload)
        self.assertEqual(result["resumo"]["total_horas"], 18)
        saved = self.db.obter_equipe(["RES-TC-NF"])
        self.assertEqual(saved["executantes"][0]["dias_disponiveis"],
                         ["2026-11-01", "2026-11-03", "2026-11-07"])
        self.assertEqual(self.db.listar_historico(["RES-TC-NF"])[0]["planejamento"], saved)
        template = self.routes.gravar_padrao(payload)
        self.assertEqual(template["executantes"][0]["capacidade"], "dias_6h")
        self.assertIsNone(template["executantes"][0]["dias_disponiveis"])


if __name__ == "__main__":
    unittest.main()
