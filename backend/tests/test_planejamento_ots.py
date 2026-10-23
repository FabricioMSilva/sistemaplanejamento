import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import backend.models.database as database
from backend.services.BMAService import BMAService, BMAServiceError


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class OrdemTrabalhoDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        db_path = Path(self.tempdir.name) / "test.db"
        path_patch = patch.object(database, "DB_PATH", db_path)
        path_patch.start()
        self.addCleanup(path_patch.stop)
        database.init_db()

    def test_sync_run_persists_stage_events_and_failure(self):
        database.criar_sincronizacao("job-1", ["RES-TC-NF"])
        database.atualizar_sincronizacao(
            "job-1",
            status="running",
            etapa="autenticacao",
            mensagem="Aguardando login/MFA no Firefox.",
            pagina=0,
            ots=0,
        )
        database.atualizar_sincronizacao(
            "job-1",
            status="failed",
            etapa="erro",
            mensagem="O Relatório rápido não abriu.",
            nivel="error",
            erro="TimeoutException: login não concluído",
        )

        run = database.obter_ultima_sincronizacao()
        self.assertEqual(run["job_id"], "job-1")
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["setores"], ["RES-TC-NF"])
        self.assertEqual(len(run["eventos"]), 3)
        self.assertEqual(run["eventos"][-1]["nivel"], "error")

    def test_upsert_preserves_all_fields_and_filters_by_status(self):
        records = [
            {
                "siteid": "RES",
                "wonum": "1001",
                "status": "WSCH",
                "maintenanceshop": "RES-TC-NF",
                "description": "Inspeção preventiva",
                "customfield": "preservado",
                "sneconstraint": "2026-10-31T23:00:00-04:00",
                "children": [{"wonum": "RES1004", "parent": "1001", "istask": True}],
                "wplabor": [{"craft": "270", "quantity": 1, "laborhrs": 40, "orgid": "BR"}],
            },
            {
                "siteid": "RES",
                "wonum": "1002",
                "status": "WAPPR",
                "maintenanceshop": "RES-TC-NF",
                "description": "Reparo",
            },
            {
                "siteid": "RES",
                "wonum": "1003",
                "status": "PREPARED",
                "maintenanceshop": "RES-TC-NC-ELE",
                "description": "Inspeção elétrica",
            },
        ]

        selected_sectors = ["RES-TC-NF", "RES-TC-NC-ELE"]
        self.assertEqual(database.upsert_ordens_trabalho(records, selected_sectors), 3)
        all_orders = database.listar_ordens_trabalho(selected_sectors)
        planned_orders = database.listar_ordens_trabalho(["RES-TC-NF"], ["WSCH"])

        self.assertEqual(len(all_orders), 3)
        self.assertEqual(len(planned_orders), 1)
        self.assertEqual(planned_orders[0]["dados"]["customfield"], "preservado")
        self.assertEqual(planned_orders[0]["dados"]["sneconstraint"], "2026-10-31T23:00:00-04:00")
        self.assertEqual(planned_orders[0]["dados"]["children"][0]["wonum"], "RES1004")
        self.assertEqual(planned_orders[0]["dados"]["wplabor"], records[0]["wplabor"])

        records[0]["status"] = "INPRG"
        database.upsert_ordens_trabalho(records[:1], ["RES-TC-NF"])
        updated_orders = database.listar_ordens_trabalho(["RES-TC-NF"], ["INPRG"])
        self.assertEqual(len(updated_orders), 1)
        self.assertEqual(updated_orders[0]["wonum"], "1001")

    def test_rejects_orders_from_another_sector(self):
        record = {
            "siteid": "RES",
            "wonum": "2001",
            "maintenanceshop": "RES-TC-GMAT",
        }
        with self.assertRaises(ValueError):
            database.upsert_ordens_trabalho([record], ["RES-TC-NF"])


class BMAOSLCTests(unittest.TestCase):
    def test_select_includes_preparation_fields_without_wildcard(self):
        query = parse_qs(urlparse(BMAService._initial_query_url(["RES-TC-NF"])).query)
        fields = set(query["oslc.select"][0].split(","))
        self.assertTrue({
            "description_longdescription", "sneconstraint", "fnlconstraint",
            "pmduedate", "pmnextduedate", "pmnum", "jpnum", "route", "crew",
            "parent", "haschildren", "estlabhrs", "estdur", "istask",
        }.issubset(fields))
        self.assertNotIn("*", fields)
        self.assertIn("wplabor{wplaborid,craft,orgid,quantity,laborhrs,skilllevel}", query["oslc.select"][0])

    def test_planned_labor_is_paginated_and_invalid_pages_abort(self):
        service = BMAService()
        row = {"wplaborid": 1, "craft": "270", "quantity": 1, "laborhrs": 40}
        record = {"wplabor": [row], "wplabor_collectionref": {"nextPage": {"href": "/maximo/oslc/os/mxwo/1/wplabor?pageno=2"}}}
        with patch.object(service, "_fetch_payload", return_value={"member": [{**row, "wplaborid": 2, "craft": "180"}]}):
            service._complete_planned_labor(unittest.mock.Mock(), record)
        self.assertEqual([r["craft"] for r in record["wplabor"]], ["270", "180"])
        for record in ({"wplabor": "invalid"}, {"wplabor": [None]},
                       {"wplabor": [], "wplabor_collectionref": {"nextPage": "https://other.example/data"}}):
            with self.subTest(record=record), self.assertRaises(BMAServiceError):
                service._complete_planned_labor(unittest.mock.Mock(), record)

    def test_collects_paginated_children_including_tasks_and_closed_orders(self):
        service = BMAService()
        records = [
            {"wonum": "RES1", "haschildren": True},
            {"wonum": "RES2", "haschildren": False},
        ]
        child = {"wonum": "RES3", "parent": "RES1", "siteid": "RES",
                 "istask": True, "status": "CLOSE", "description_longdescription": "Instruções"}
        pages = [
            {"member": [child], "responseInfo": {"nextPage": {"href": "oslc/os/mxwo?pageno=2"}}},
            {"member": [child, {**child, "wonum": "RES4"}]},
        ]
        with patch.object(service, "_fetch_payload", side_effect=pages) as fetch:
            service._collect_children(unittest.mock.Mock(), records)
        self.assertEqual([child["wonum"] for child in records[0]["children"]], ["RES3", "RES4"])
        self.assertEqual(records[0]["children"][0]["description_longdescription"], "Instruções")
        self.assertEqual(records[1]["children"], [])
        where = parse_qs(urlparse(fetch.call_args_list[0].args[1]).query)["oslc.where"][0]
        self.assertIn('parent in ["RES1"]', where)
        self.assertNotIn("istask", where)
        self.assertNotIn("status", where)

    def test_child_errors_abort_collection(self):
        service = BMAService()
        records = [{"wonum": "RES1", "haschildren": True}]
        for payload in (
            {"member": "invalid"},
            {"member": [{"parent": "RES2", "wonum": "RES3", "siteid": "RES"}]},
            {"member": [], "nextPage": "https://other.example/maximo/oslc/os/mxwo"},
        ):
            with self.subTest(payload=payload), patch.object(service, "_fetch_payload", return_value=payload):
                with self.assertRaises(BMAServiceError):
                    service._collect_children(unittest.mock.Mock(), records)

    def test_children_queries_are_batched(self):
        service = BMAService()
        records = [{"wonum": f"RES{i}", "haschildren": True} for i in range(41)]
        with patch.object(service, "_fetch_payload", return_value={"member": []}) as fetch:
            service._collect_children(unittest.mock.Mock(), records)
        self.assertEqual(fetch.call_count, 2)
        first_where = parse_qs(urlparse(fetch.call_args_list[0].args[1]).query)["oslc.where"][0]
        second_where = parse_qs(urlparse(fetch.call_args_list[1].args[1]).query)["oslc.where"][0]
        self.assertIn('"RES39"', first_where)
        self.assertNotIn('"RES40"', first_where)
        self.assertIn('"RES40"', second_where)

    def test_children_are_preserved_when_syncing_parent(self):
        service = BMAService()
        record = {"siteid": "RES", "wonum": "RES1", "status": "PREPARED",
                  "maintenanceshop": "RES-TC-NF", "haschildren": True,
                  "wplabor": [{"craft": "270", "quantity": 1, "laborhrs": 40}]}
        child = {"siteid": "RES", "wonum": "RES2", "parent": "RES1", "istask": True}
        with (
            patch.object(service, "_create_browser") as browser,
            patch.object(service, "_wait_for_quickrep"),
            patch.object(service, "_fetch_payload", side_effect=[
                {"member": [record]}, {"member": [child]},
            ]),
        ):
            records = service.listar_ots_por_setor(["RES-TC-NF"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["children"], [child])
        self.assertEqual(records[0]["wplabor"][0]["craft"], "270")
        browser.return_value.quit.assert_called_once()

    def test_where_uses_multiple_sectors_and_excludes_terminal_statuses(self):
        where = parse_qs(urlparse(BMAService._initial_query_url([
            "RES-TC-NF",
            "RES-TC-NC-ELE",
            "RES-TC-NC-REP",
        ])).query)["oslc.where"][0]

        self.assertIn('maintenanceshop in ["RES-TC-NF","RES-TC-NC-ELE","RES-TC-NC-REP"]', where)
        for status in ("CAN", "CLOSE", "COMP", "HISTEDIT"):
            self.assertIn(f'status!="{status}"', where)
        self.assertNotIn("(", where)

    def test_opens_quickrep_and_fetches_all_pages_within_the_authenticated_browser(self):
        driver = unittest.mock.Mock()
        driver.execute_async_script = unittest.mock.Mock()
        pages = [
            {
                "member": [{
                    "siteid": "RES",
                    "wonum": "RES1001",
                    "status": "PREPARED",
                    "maintenanceshop": "RES-TC-NF",
                    "woclass": "WORKORDER",
                    "historyflag": False,
                    "istask": False,
                }],
                "responseInfo": {"nextPage": {"href": "oslc/os/mxwo?pageno=2&lean=1"}},
            },
            {
                "member": [{
                    "siteid": "RES",
                    "wonum": "RES1002",
                    "status": "WAPPR",
                    "maintenanceshop": "RES-TC-NC-ELE",
                    "woclass": "WORKORDER",
                    "historyflag": False,
                    "istask": False,
                }],
                "responseInfo": {},
            },
        ]
        service = BMAService()

        with (
            patch.object(service, "_create_browser", return_value=driver),
            patch.object(service, "_wait_for_quickrep") as wait_for_quickrep,
            patch.object(service, "_fetch_payload", side_effect=pages) as fetch_page,
        ):
            records = service.listar_ots_por_setor([
                "RES-TC-NF",
                "RES-TC-NC-ELE",
                "RES-TC-NC-REP",
            ])

        self.assertEqual([record["wonum"] for record in records], ["RES1001", "RES1002"])
        driver.get.assert_called_once_with(service.quickrep_url)
        wait_for_quickrep.assert_called_once_with(driver, None)
        first_url = fetch_page.call_args_list[0].args[1]
        query = parse_qs(urlparse(first_url).query)
        self.assertIn('"RES-TC-NF"', query["oslc.where"][0])
        self.assertIn('"RES-TC-NC-ELE"', query["oslc.where"][0])
        self.assertIn('"RES-TC-NC-REP"', query["oslc.where"][0])
        self.assertNotIn('status="', query["oslc.where"][0])
        driver.quit.assert_called_once_with()

    def test_filters_results_to_north_site_shop_and_non_task_orders(self):
        service = BMAService()
        self.assertTrue(service._matches_scope({
            "siteid": "RES",
            "wonum": "RES1",
            "status": "PREPARED",
            "maintenanceshop": "RES-TC-NF",
            "woclass": "WORKORDER",
            "historyflag": False,
            "istask": False,
        }, ["RES-TC-NF", "RES-TC-NC-ELE"]))
        self.assertFalse(service._matches_scope({
            "siteid": "RES",
            "wonum": "RES2",
            "status": "PREPARED",
            "maintenanceshop": "RES-TC-NS2",
            "woclass": "WORKORDER",
            "historyflag": False,
            "istask": False,
        }, ["RES-TC-NF", "RES-TC-NC-ELE"]))
        self.assertFalse(service._matches_scope({
            "siteid": "RES",
            "wonum": "RES3",
            "status": "PREPARED",
            "maintenanceshop": "RES-TC-NF",
            "woclass": "WORKORDER",
            "historyflag": True,
            "istask": False,
        }, ["RES-TC-NF", "RES-TC-NC-ELE"]))

    def test_rejects_pagination_to_another_origin(self):
        service = BMAService()
        origin = urlparse(service.quickrep_url)
        with self.assertRaises(BMAServiceError):
            service._normalize_next_page(
                "/maximo/oslc/os/mxwo?cursor=1",
                "https://other.example/maximo/oslc/os/mxwo?cursor=2",
                origin,
            )


if __name__ == "__main__":
    unittest.main()