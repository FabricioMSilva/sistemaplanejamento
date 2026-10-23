import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import backend.models.database as database
from backend.services.BMAService import BMAService, BMAServiceError


def profissional(code="TEST1", **values):
    return {
        "laborcode": code, "orgid": "BR", "worksite": "RES", "status": "ACTIVE",
        "fullname": "Profissional de teste", "maintenanceshop": "RES-TC-NF",
        "worklocation": "TC",
        "laborcraftrate": [{"craft": "210", "defaultcraft": True}],
        **values,
    }


class LaborDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        db_patch = patch.object(database, "DB_PATH", Path(self.directory.name) / "test.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_db()

    def test_fixed_catalog_contains_every_organization_and_is_idempotent(self):
        database.init_db()
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM especialidades").fetchone()[0], 273)
        self.assertEqual(len(database.listar_especialidades("BR")), 54)
        crafts = {r["codigo"]: r["descricao"] for r in database.listar_especialidades("BR")}
        self.assertEqual(crafts["210"], "Eletricista")
        self.assertEqual(crafts["120"], "Motorista")
        us = {r["codigo"]: r["descricao"] for r in database.listar_especialidades("US")}
        self.assertEqual(us["120"], "Motor Maintainer")

    def test_never_synced_is_distinct_from_empty_snapshot(self):
        self.assertIsNone(database.listar_mao_de_obra()["sincronizado_em"])
        database.salvar_planejamento([], ["RES-TC-NF"], [])
        self.assertIsNotNone(database.listar_mao_de_obra()["sincronizado_em"])
        self.assertEqual(database.listar_mao_de_obra()["total"], 0)

    def test_replaces_snapshot_removing_people_no_longer_active(self):
        database.salvar_planejamento([], ["RES-TC-NF"], [profissional(), profissional("TEST2")])
        database.salvar_planejamento([], ["RES-TC-NF"], [profissional("TEST2", fullname="Atualizado")])
        result = database.listar_mao_de_obra()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["profissionais"][0]["nome"], "Atualizado")
        self.assertEqual(result["profissionais"][0]["especialidades"][0]["descricao"], "Eletricista")

    def test_unknown_craft_is_not_mislabelled(self):
        database.salvar_planejamento([], ["RES-TC-NF"], [
            profissional(laborcraftrate=[{"craft": "UNKNOWN"}]),
        ])
        result = database.listar_mao_de_obra()["profissionais"][0]["especialidades"][0]
        self.assertIsNone(result["descricao"])
        self.assertEqual(result["codigo"], "UNKNOWN")

    def test_filters_by_exact_selected_sectors_not_prefix(self):
        database.salvar_planejamento([], ["RES-TC-NF"], [
            profissional("NF"), profissional("NC", maintenanceshop="RES-TC-NC"),
            profissional("SUB", maintenanceshop="RES-TC-NF-SUB"),
            profissional("EMPTY", maintenanceshop="", worklocation=""),
            profissional("NFE", maintenanceshop="RES-MATRM-NR2", worklocation="NFE"),
            profissional("NEAR", maintenanceshop="RES-MATRM-NR2", worklocation="NFE-AREA"),
        ])
        # Sector selection is tested independently of the separate NF active-roster check.
        result = database.listar_mao_de_obra(["res-tc-nf"], filtrar_nf=False)
        self.assertEqual({person["matricula"] for person in result["profissionais"]}, {"NF", "NFE"})
        nfe = next(person for person in result["profissionais"] if person["matricula"] == "NFE")
        self.assertEqual(nfe["local_trabalho"], "NFE")
        self.assertIsNotNone(result["sincronizado_em"])
        both = database.listar_mao_de_obra(["RES-TC-NF", "RES-TC-NC"], filtrar_nf=False)
        self.assertEqual(both["total"], 3)
        self.assertEqual(database.listar_mao_de_obra(["RES-UNKNOWN"])["total"], 1)
        with self.assertRaises(ValueError):
            database.listar_mao_de_obra([])

    def test_invalid_snapshot_preserves_previous_data(self):
        database.salvar_planejamento([], ["RES-TC-NF"], [profissional()])
        for labor in (
            [profissional(status="INACTIVE")], [profissional(worksite="OTHER")],
            [profissional(), profissional()],
        ):
            with self.subTest(labor=labor), self.assertRaises(ValueError):
                database.salvar_planejamento([], ["RES-TC-NF"], labor)
        self.assertEqual(database.listar_mao_de_obra()["total"], 1)

    def test_database_failure_rolls_back_orders_and_labor(self):
        database.salvar_planejamento([], ["RES-TC-NF"], [profissional()])
        with database.get_connection() as conn:
            conn.execute("""CREATE TRIGGER reject_labor BEFORE INSERT ON mao_de_obra
                            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        order = {"wonum": "RES1", "siteid": "RES", "maintenanceshop": "RES-TC-NF"}
        with self.assertRaises(sqlite3.IntegrityError):
            database.salvar_planejamento([order], ["RES-TC-NF"], [profissional("TEST2")])
        self.assertEqual(database.listar_ordens_trabalho(["RES-TC-NF"]), [])
        self.assertEqual(database.listar_mao_de_obra()["profissionais"][0]["matricula"], "TEST1")


class LaborCollectionTests(unittest.TestCase):
    def test_pagination_scope_and_no_unnecessary_personal_fields(self):
        service = BMAService()
        pages = [
            {"member": [profissional()], "responseInfo": {"nextPage": {"href": "oslc/os/mxlabor?pageno=2"}}},
            {"member": [profissional(), profissional("TEST2")]},
        ]
        with patch.object(service, "_fetch_payload", side_effect=pages) as fetch:
            people = service._collect_labor(Mock())
        self.assertEqual(len(people), 2)
        query = parse_qs(urlsplit(fetch.call_args_list[0].args[1]).query)
        self.assertEqual(query["oslc.where"], ['worksite="RES" and status="ACTIVE"'])
        self.assertNotIn("*", query["oslc.select"][0])
        self.assertNotIn("email", query["oslc.select"][0])
        self.assertIn("laborcraftrate{craft,skilllevel,defaultcraft}", query["oslc.select"][0])
        self.assertIn("worklocation", query["oslc.select"][0])

    def test_invalid_or_incomplete_responses_fail(self):
        service = BMAService()
        for payload in (
            {"member": None}, {"member": [profissional(worksite="OTHER")]},
            {"member": [profissional(status="INACTIVE")]},
            {"member": [profissional(laborcode="")]},
            {"member": [], "nextPage": "https://other.example/maximo/oslc/os/mxlabor"},
        ):
            with self.subTest(payload=payload), patch.object(service, "_fetch_payload", return_value=payload):
                with self.assertRaises(BMAServiceError):
                    service._collect_labor(Mock())
        with patch("backend.services.BMAService.PAGE_SIZE", 1), patch.object(
            service, "_fetch_payload", return_value={"member": [profissional()]},
        ):
            with self.assertRaises(BMAServiceError):
                service._collect_labor(Mock())

    def test_combined_sync_uses_same_browser_and_propagates_labor_failure(self):
        service = BMAService()
        for failure in (False, True):
            with (
                self.subTest(failure=failure),
                patch.object(service, "_create_browser") as browser,
                patch.object(service, "_wait_for_quickrep"),
                patch.object(service, "_fetch_payload", return_value={"member": []}),
                patch.object(
                    service, "_collect_labor",
                    **({"side_effect": BMAServiceError("Falha")} if failure else {"return_value": [profissional()]}),
                ) as labor,
            ):
                if failure:
                    with self.assertRaises(BMAServiceError):
                        service.coletar_planejamento(["RES-TC-NF"])
                else:
                    records, people = service.coletar_planejamento(["RES-TC-NF"])
                    self.assertEqual(records, [])
                    self.assertEqual(people, [profissional()])
                labor.assert_called_once_with(browser.return_value, None)
                browser.return_value.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
