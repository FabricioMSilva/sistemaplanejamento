import asyncio
import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException
from openpyxl import load_workbook
from selenium.common.exceptions import TimeoutException

import backend.models.database as database
from backend.models.workforce_identity import vincular_ativos
from backend.services.BMAService import BMAService, BMAServiceError
from backend.services.labor_planning import calcular_equipe
from backend.services.nf_workforce import _load_ronda_reference, coletar_ativos, coletar_ots_ronda
from backend.services.ronda_sharepoint_report import (
    atualizar_excel_ots_ronda, baixar_excel_ots_ronda, criar_excel_ots_ronda,
    enviar_excel_ots_ronda,
)
from backend.tests.test_labor_planning import cadastro, executante, plano
from backend.tests.test_mao_de_obra import profissional


class WorkforceIdentityTests(unittest.TestCase):
    def test_exact_names_ignore_case_accents_but_never_abbreviate(self):
        people = [{"orgid": "BR", "matricula": "E1", "nome": "João da Silva"}]
        exact = vincular_ativos([{"id": 1, "nome": "JOAO DA SILVA"}], people, {})
        self.assertEqual(len(exact["vinculados"]), 1)
        abbreviated = vincular_ativos([{"id": 1, "nome": "Joao Silva"}], people, {})
        self.assertEqual(len(abbreviated["pendentes"]), 1)

    def test_confirmed_mapping_wins_over_an_automatic_duplicate_name_match(self):
        person = {"orgid": "BR", "matricula": "E1", "nome": "Nelio Correia"}
        roster = [{"id": 1, "nome": "Nelio Correia"}, {"id": 2, "nome": "Nélio Correia"}]
        result = vincular_ativos(roster, [person], {"1": {"orgid": "BR", "matricula": "E1"}})
        self.assertEqual([row["id"] for row in result["vinculados"]], [1])
        self.assertEqual([row["id"] for row in result["pendentes"]], [2])

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

    def test_sharepoint_navigation_timeout_continues_with_loaded_page(self):
        driver = Mock()
        driver.current_url = "https://michelingroup.sharepoint.com/sites/NF-RES/Lists/ListaFuncionario/AllItems.aspx"
        driver.get.side_effect = TimeoutException("Navigation timed out after 60000 ms")
        driver.execute_async_script.return_value = {
            "data": {"value": [{"ID": 1, "Nome": "Pessoa", "Matr_x00ed_cula": "E1"}]},
        }

        rows = coletar_ativos(driver, 1)

        driver.get.assert_called_once_with("https://michelingroup.sharepoint.com/sites/NF-RES/Lists/ListaFuncionario/AllItems.aspx")
        self.assertEqual(rows, [{"id": 1, "nome": "Pessoa", "matricula": "E1"}])

    def test_round_list_resolves_json_alias_and_blocks_unknown_employee(self):
        driver = Mock()
        driver.current_url = "https://michelingroup.sharepoint.com/sites/NF-RES/Lists/AbrirOTRonda/AllItems.aspx"
        driver.execute_async_script.side_effect = [
            {"data": {"value": [
                {"Title": "Status", "InternalName": "Status", "TypeAsString": "Choice", "Hidden": False},
                {"Title": "Ronda", "InternalName": "Ronda", "TypeAsString": "Choice", "Hidden": False},
                {"Title": "Nome", "InternalName": "Nome", "TypeAsString": "User", "Hidden": False},
                {"Title": "Matricula", "InternalName": "Matricula", "TypeAsString": "Text", "Hidden": False},
                {"Title": "nOT", "InternalName": "nOT", "TypeAsString": "Text", "Hidden": False},
                {"Title": "Date", "InternalName": "Date", "TypeAsString": "DateTime", "Hidden": False},
                {"Title": "Horario", "InternalName": "Horario", "TypeAsString": "Choice", "Hidden": False},
                {"Title": "Equipe", "InternalName": "Equipe", "TypeAsString": "Text", "Hidden": False},
            ]}},
            {"data": {"value": [
                {"Id": 10, "Status": "Pendente", "Ronda": "Inspeção diária", "Matricula": "", "nOT": "RES123",
                 "Date": "2026-11-04T00:00:00Z", "Horario": "A", "Equipe": "NFE",
                 "Nome": {"Title": "Pessoa Alias"}},
                {"Id": 12, "Status": "Pendente", "Ronda": "Inspeção semanal", "Matricula": "X9", "nOT": "",
                 "Date": "2026-11-04T00:00:00Z", "Horario": "B", "Equipe": "NFE",
                 "Nome": {"Title": "Pessoa sem cadastro"}},
                {"Id": 11, "Status": "Concluída", "Ronda": "Inspeção semanal", "Matricula": "E1", "nOT": "RES124",
                 "Date": "2026-11-03T00:00:00Z", "Horario": "C", "Equipe": "NFE",
                 "Nome": {"Title": "Pessoa Ativa"}},
            ]}},
        ]
        workers = [{**profissional("E1", fullname="Pessoa Ativa"), "nome": "Pessoa Ativa", "matricula": "E1"}]

        reference = {
            "PESSOA ATIVA": [{"nome": "Pessoa Ativa", "matricula": "E1"}],
            "PESSOA ALIAS": [{"nome": "Pessoa Ativa", "matricula": "E1"}],
        }
        with patch("backend.services.nf_workforce._load_ronda_reference", return_value=reference):
            result = coletar_ots_ronda(driver, 1, workers)
        rows = result["pendentes"]

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(result["bloqueadas"]), 1)
        self.assertEqual(len(result["funcionarios"]), 2)
        self.assertEqual(rows[0]["ronda"], "Inspeção diária")
        self.assertEqual(rows[0]["numero_ot"], "RES123")
        self.assertEqual(rows[0]["executantes"], [
            {"nome": "Pessoa Alias", "matricula": "E1", "matricula_lista": None, "orgid": "BR",
             "vinculo": "confirmado", "fonte_matricula": "json"},
        ])
        self.assertEqual(result["bloqueadas"][0]["executantes"][0]["matricula"], None)
        self.assertEqual(result["bloqueadas"][0]["executantes"][0]["matricula_lista"], "X9")
        self.assertEqual(result["bloqueadas"][0]["bloqueios_matricula"], ["Pessoa sem cadastro"])
        self.assertEqual(result["pendentes"][0]["data"], "2026-11-04T00:00:00Z")
        self.assertEqual(result["pendentes"][0]["turno"], "A")
        self.assertEqual(result["pendentes"][0]["equipe"], "NFE")
        self.assertEqual(len(result["itens"]), 3)
        self.assertIn("Nome/Title", driver.execute_async_script.call_args_list[1].args[1])

    def test_round_collection_advances_microsoft_email_before_sharepoint_redirect(self):
        driver = Mock(current_url="https://login.microsoftonline.com/tenant/oauth2/authorize")
        auth_service = Mock()
        auth_service._advance_microsoft_email.side_effect = lambda browser: setattr(
            browser,
            "current_url",
            "https://michelingroup.sharepoint.com/sites/NF-RES/Lists/AbrirOTRonda/AllItems.aspx",
        ) or True

        def wait_until(condition):
            self.assertFalse(condition(driver))
            self.assertTrue(condition(driver))

        with (
            patch("backend.services.nf_workforce.BMAService", return_value=auth_service),
            patch("backend.services.nf_workforce._load_ronda_reference", return_value={}),
            patch("backend.services.nf_workforce.WebDriverWait") as wait,
            patch("backend.services.nf_workforce._sharepoint_json", side_effect=BMAServiceError("stop after login")),
        ):
            wait.return_value.until.side_effect = wait_until
            with self.assertRaisesRegex(BMAServiceError, "stop after login"):
                coletar_ots_ronda(driver, 10, [])

        auth_service._advance_microsoft_email.assert_called_once_with(driver)


class RondaReferenceTests(unittest.TestCase):
    def test_reference_falls_back_to_packaged_roster_when_user_copy_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "user-data"
            resource_dir = Path(temp_dir) / "resources"
            packaged_file = resource_dir / "database" / "data" / "funcionario.json"
            packaged_file.parent.mkdir(parents=True)
            packaged_file.write_text(json.dumps([{
                "Nome": "Funcionária Empacotada",
                "NomesAlternativos": ["Nome Alternativo"],
                "Matricula": "B107346",
            }]), encoding="utf-8")

            with (
                patch("backend.services.nf_workforce.data_root", return_value=data_dir),
                patch("backend.services.nf_workforce.resource_root", return_value=resource_dir),
            ):
                reference = _load_ronda_reference()

        self.assertEqual(reference["FUNCIONARIA EMPACOTADA"][0]["matricula"], "B107346")
        self.assertEqual(reference["NOME ALTERNATIVO"][0]["matricula"], "B107346")

    def test_reference_indexes_primary_and_alternative_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "funcionario.json"
            path.write_text(json.dumps([{
                "Nome": "Nome Completo",
                "NomesAlternativos": ["Nome Alternativo"],
                "Matricula": "B123456",
            }]), encoding="utf-8")

            reference = _load_ronda_reference(path)

        self.assertEqual(reference["NOME COMPLETO"][0]["matricula"], "B123456")
        self.assertEqual(reference["NOME ALTERNATIVO"][0]["matricula"], "B123456")

    def test_reference_reports_employee_without_registration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "funcionario.json"
            path.write_text(json.dumps([{"Nome": "Sem Matrícula", "Matricula": ""}]), encoding="utf-8")

            with self.assertRaisesRegex(BMAServiceError, "Sem Matrícula"):
                _load_ronda_reference(path)


class RondaSharePointReportTests(unittest.TestCase):
    def test_excel_maps_ot_sharepoint_row_and_people_and_omits_uncreated_rows(self):
        content, count = criar_excel_ots_ronda([
            {"id": 71, "numero_ot_criada": "RES1234567", "ronda": "Análise química",
             "status": "PENDENTE", "data": "2026-11-04", "turno": "A", "equipe": "NFE",
             "executantes": [{"nome": "Pessoa Um", "matricula": "B107346"}],
             "criacao_status": "criada", "criacao_em": "2026-11-05T12:00:00+00:00"},
            {"id": 72, "numero_ot_criada": None, "numero_ot": "", "executantes": []},
        ])

        sheet = load_workbook(BytesIO(content), data_only=True).active
        self.assertEqual(count, 1)
        self.assertEqual(sheet.title, "OTS de Rondas")
        self.assertEqual(sheet.max_row, 2)
        self.assertEqual(sheet.cell(2, 1).value, 71)
        self.assertEqual(sheet.cell(2, 2).value, "RES1234567")
        self.assertEqual(sheet.cell(2, 8).value, "Pessoa Um")
        self.assertEqual(sheet.cell(2, 9).value, "B107346")
        self.assertIn("dadosOT", sheet.tables)

    def test_merge_excel_appends_only_missing_rows_and_preserves_table_and_history(self):
        original = {
            "id": 71, "numero_ot_criada": "RES1234567", "ronda": "Ronda original",
            "status": "CONCLUIDO", "data": "2026-11-04", "turno": "A", "equipe": "NFE",
            "executantes": [{"nome": "Pessoa Um", "matricula": "B107346"}],
            "criacao_status": "criada", "criacao_em": "2026-11-05T12:00:00+00:00",
        }
        changed = {**original, "ronda": "Ronda corrigida"}
        added_item = {**original, "id": 72, "numero_ot_criada": "RES7654321", "ronda": "Ronda nova"}
        initial_content, _ = criar_excel_ots_ronda([original])
        initial_sheet = load_workbook(BytesIO(initial_content), data_only=True).active
        initial_table = load_workbook(BytesIO(initial_content)).active.tables["dadosOT"]
        original_row = [initial_sheet.cell(2, column).value for column in range(1, 12)]

        merged_content, added_count, created_file = atualizar_excel_ots_ronda(
            initial_content, [original, changed, added_item],
        )

        workbook = load_workbook(BytesIO(merged_content), data_only=True)
        sheet = workbook.active
        table = load_workbook(BytesIO(merged_content)).active.tables["dadosOT"]
        self.assertEqual(added_count, 2)
        self.assertFalse(created_file)
        self.assertEqual(sheet.max_row, 4)
        self.assertEqual([sheet.cell(2, column).value for column in range(1, 12)], original_row)
        self.assertEqual(sheet.cell(3, 3).value, "Ronda corrigida")
        self.assertEqual(sheet.cell(4, 1).value, 72)
        self.assertEqual(table.displayName, "dadosOT")
        self.assertEqual(table.tableStyleInfo.name, initial_table.tableStyleInfo.name)
        self.assertEqual(table.ref, "A1:K4")

        unchanged_content, unchanged_count, was_created = atualizar_excel_ots_ronda(
            merged_content, [original, changed, added_item],
        )
        self.assertEqual(unchanged_count, 0)
        self.assertFalse(was_created)
        self.assertEqual(unchanged_content, merged_content)

        old_snapshot, _ = criar_excel_ots_ronda([{
            "id": 80, "numero_ot": "RES7654321", "criacao_status": "pendente",
        }])
        old_sheet = load_workbook(BytesIO(old_snapshot), data_only=True).active
        self.assertEqual(old_sheet.cell(2, 10).value, "numero_existente")

    def test_sharepoint_upload_uses_fixed_file_name_and_overwrites(self):
        driver = Mock()
        driver.execute_async_script.return_value = {"fileName": "OTS de Rondas.xlsx"}

        result = enviar_excel_ots_ronda(driver, b"workbook-bytes")

        script, site, upload_url, encoded, file_name = driver.execute_async_script.call_args.args
        self.assertEqual(result, "OTS de Rondas.xlsx")
        self.assertIn("/Documentos%20Compartilhados/DigitalNFE/Arquivos%20de%20dados%20MPQ')/Files/add", upload_url)
        self.assertIn("Files/add(url='OTS%20de%20Rondas.xlsx',overwrite=true)", upload_url)
        self.assertEqual(file_name, "OTS de Rondas.xlsx")
        self.assertTrue(encoded)
        self.assertIn("X-RequestDigest", script)

    def test_sharepoint_download_distinguishes_existing_file_from_missing_file(self):
        driver = Mock()
        driver.execute_async_script.return_value = {"exists": True, "base64": "eHl6"}

        self.assertEqual(baixar_excel_ots_ronda(driver), b"xyz")
        script, download_url = driver.execute_async_script.call_args.args
        self.assertIn("GetFileByServerRelativeUrl", download_url)
        self.assertIn("OTS%20de%20Rondas.xlsx", download_url)
        self.assertIn("response.status === 404", script)

        driver.execute_async_script.return_value = {"exists": False}
        self.assertIsNone(baixar_excel_ots_ronda(driver))

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

    def test_round_sharepoint_snapshot_persists_creation_fields_and_replaces_atomically(self):
        items = [
            {"id": 10, "status": "PENDENTE", "ronda": "Ronda A", "data": "2026-11-04",
             "turno": "A", "equipe": "NFE", "executantes": [{"nome": "Pessoa", "matricula": "E1"}],
             "bloqueios_matricula": [], "sharepoint_raw": {"Date": "2026-11-04"}},
            {"id": 11, "status": "PENDENTE", "ronda": "Ronda B", "data": "2026-11-04",
             "turno": "B", "equipe": "NFE", "executantes": [{"nome": "Sem cadastro", "matricula": None}],
             "bloqueios_matricula": ["Sem cadastro"], "sharepoint_raw": {"Date": "2026-11-04"}},
        ]

        self.assertEqual(database.salvar_itens_ronda_sharepoint(items), 2)
        saved = database.listar_itens_ronda_sharepoint()
        self.assertEqual([item["sharepoint_raw"] for item in saved], [item["sharepoint_raw"] for item in items])
        self.assertEqual([item["criacao_status"] for item in saved], ["pendente", "pendente"])
        eligible = database.listar_itens_ronda_para_criacao()
        self.assertEqual([item["id"] for item in eligible], [10])
        self.assertEqual(eligible[0]["data"], items[0]["data"])
        self.assertEqual(database.resumo_ronda_sharepoint()["aptas"], 1)
        self.assertEqual(database.resumo_ronda_sharepoint()["bloqueadas"], 1)

        database.iniciar_criacao_ronda([10])
        database.registrar_numero_ot_ronda([10], "RES1234567")
        generated = database.listar_itens_ronda_sharepoint()[0]
        self.assertEqual(generated["criacao_status"], "numero_gerado")
        self.assertEqual(generated["numero_ot_criada"], "RES1234567")
        database.marcar_ot_ronda_salva([10], "RES1234567")
        saved = database.listar_itens_ronda_sharepoint()[0]
        self.assertEqual(saved["criacao_status"], "salva")
        self.assertEqual(database.listar_itens_ronda_para_criacao(), [])
        database.falhar_criacao_ronda([10], "Workflow não confirmou COMP")
        interrupted = database.listar_itens_ronda_sharepoint()[0]
        self.assertEqual(interrupted["criacao_status"], "salva")
        self.assertEqual(interrupted["numero_ot_criada"], "RES1234567")
        database.registrar_ot_ronda_criada([10], "RES1234567")
        database.salvar_itens_ronda_sharepoint(items)
        refreshed = database.listar_itens_ronda_sharepoint()[0]
        self.assertEqual(refreshed["criacao_status"], "criada")
        self.assertEqual(refreshed["numero_ot_criada"], "RES1234567")
        self.assertEqual(database.listar_itens_ronda_para_criacao(), [])
        self.assertEqual(database.resumo_ronda_sharepoint()["criadas"], 1)

        replacement = [{**items[0], "id": 12, "ronda": "Ronda C"}]
        self.assertEqual(database.salvar_itens_ronda_sharepoint(replacement), 1)
        self.assertEqual(database.listar_itens_ronda_sharepoint()[0]["id"], 12)

    def test_round_eligibility_uses_sharepoint_number_status_and_registration(self):
        items = [
            {"id": 20, "status": "PENDENTE", "ronda": "Ronda A",
             "executantes": [{"nome": "Pessoa", "matricula": "E1"}], "bloqueios_matricula": []},
            {"id": 21, "status": "PENDENTE", "ronda": "Ronda A", "numero_ot": "RES1234567",
             "executantes": [{"nome": "Pessoa", "matricula": "E1"}], "bloqueios_matricula": []},
            {"id": 22, "status": "PENDENTE", "ronda": "Ronda A",
             "executantes": [{"nome": "Sem cadastro", "matricula": None}], "bloqueios_matricula": ["Sem cadastro"]},
            {"id": 23, "status": "CONCLUIDO", "ronda": "Ronda A",
             "executantes": [{"nome": "Pessoa", "matricula": "E1"}], "bloqueios_matricula": []},
            {"id": 24, "status": "PENDENTE", "ronda": "Ronda A",
             "executantes": [{"nome": "Pessoa", "matricula": "E1"}], "bloqueios_matricula": [],
             "sharepoint_raw": {"nOT": "RES7654321"}},
        ]

        database.salvar_itens_ronda_sharepoint(items)
        saved = {item["id"]: item for item in database.listar_itens_ronda_sharepoint()}
        self.assertTrue(saved[20]["apta_criacao"])
        self.assertFalse(saved[21]["apta_criacao"])
        self.assertFalse(saved[22]["apta_criacao"])
        self.assertFalse(saved[23]["apta_criacao"])
        self.assertFalse(saved[24]["apta_criacao"])
        self.assertEqual([item["id"] for item in database.listar_itens_ronda_para_criacao()], [20])
        self.assertEqual(database.resumo_ronda_sharepoint()["aptas"], 1)
        self.assertEqual(saved[21]["criacao_status"], "numero_existente")
        self.assertEqual(saved[21]["numero_ot_criada"], "RES1234567")
        self.assertEqual(saved[24]["criacao_status"], "numero_existente")
        self.assertEqual(saved[24]["numero_ot_criada"], "RES7654321")

        database.iniciar_criacao_ronda([20])
        database.falhar_criacao_ronda([20], "Falha anterior de automação")
        self.assertEqual([item["id"] for item in database.listar_itens_ronda_para_criacao()], [20])
        self.assertEqual(database.resumo_ronda_sharepoint()["aptas"], 1)

    def test_init_db_corrects_legacy_pending_record_with_sharepoint_ot_number(self):
        item = {
            "id": 80, "status": "CONCLUIDO", "ronda": "Ronda A", "numero_ot": "RES7654321",
            "executantes": [{"nome": "Pessoa", "matricula": "E1"}], "bloqueios_matricula": [],
            "sharepoint_raw": {"nOT": "RES7654321"},
        }
        database.salvar_itens_ronda_sharepoint([item])
        with database.get_connection() as conn:
            conn.execute(
                """UPDATE ronda_sharepoint_items
                   SET apta_criacao=1, criacao_status='pendente', numero_ot=NULL
                   WHERE sharepoint_id=80"""
            )

        database.init_db()
        database.init_db()

        existing = database.listar_itens_ronda_sharepoint()[0]
        self.assertEqual(existing["criacao_status"], "numero_existente")
        self.assertEqual(existing["numero_ot_criada"], "RES7654321")
        self.assertFalse(existing["apta_criacao"])
        self.assertEqual(database.listar_itens_ronda_para_criacao(), [])

    def test_ronda_employees_are_upserted_for_future_use_without_duplicates(self):
        rows = [
            {"nome": "Pessoa Ativa", "matricula_lista": "E1", "matricula_bma": "E1", "orgid": "BR", "vinculo": "confirmado"},
            {"nome": "Pessoa sem cadastro", "matricula_lista": "X9", "matricula_bma": "", "orgid": "", "vinculo": "sem_vinculo"},
        ]
        self.assertEqual(database.salvar_funcionarios_ronda(rows), 2)
        self.assertEqual(database.salvar_funcionarios_ronda([{**rows[0], "nome": "  PESSOA ATIVA "}]), 1)

        saved = database.listar_funcionarios_ronda()

        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["nome"], "PESSOA ATIVA")
        self.assertEqual(saved[1]["matricula_lista"], "X9")
        self.assertEqual(saved[1]["vinculo"], "sem_vinculo")

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

    def test_named_teams_are_unlimited_sector_scoped_and_update_current_atomically(self):
        data = plano(planejador="Planner 1").model_dump(mode="json")
        saved = database.salvar_equipe_nomeada(data, "  Equipe   A  ")
        self.assertEqual(saved["nome"], "Equipe A")
        self.assertEqual(database.obter_equipe(data["setores"]), data)
        self.assertEqual(len(database.listar_historico(data["setores"])), 1)

        updated = {**data, "planejador": "Planner 2"}
        database.salvar_equipe_nomeada(updated, "equipe a")
        rows = database.listar_equipes_salvas(["res-tc-nf"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nome"], "equipe a")
        self.assertEqual(rows[0]["planejamento"]["planejador"], "Planner 2")
        self.assertEqual(len(database.listar_historico(data["setores"])), 2)

        other = {**updated, "setores": ["RES-TC-NC"]}
        database.salvar_equipe_nomeada(other, "Equipe A", persistir_atual=False)
        self.assertEqual(len(database.listar_equipes_salvas(["RES-TC-NC"])), 1)
        self.assertIsNone(database.obter_equipe(["RES-TC-NC"]))
        self.assertEqual(len(database.listar_equipes_salvas(data["setores"])), 1)

    def test_named_team_rejects_empty_or_overlong_names(self):
        data = plano().model_dump(mode="json")
        for name in ("  ", "x" * 81):
            with self.subTest(name=name), self.assertRaises(ValueError):
                database.salvar_equipe_nomeada(data, name)

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

    def test_ots_sync_passes_known_orders_and_updates_their_bma_status(self):
        self.db.criar_sincronizacao("ots-status", ["RES-TC-NF"])
        existing = {
            "siteid": "RES", "wonum": "RES1001", "status": "PREPARED",
            "maintenanceshop": "RES-TC-NF", "description": "Limpeza programada",
        }
        terminal = {**existing, "status": "COMP"}
        self.db.upsert_ordens_trabalho([existing], ["RES-TC-NF"])

        with patch.object(self.routes.bma_service, "listar_ots_por_setor", return_value=[terminal]) as collect:
            self.routes._executar_sincronizacao("ots-status", ["RES-TC-NF"])

        known_orders = collect.call_args.kwargs["existing_orders"]
        self.assertEqual([order["wonum"] for order in known_orders], ["RES1001"])
        refreshed = self.db.listar_ordens_trabalho(["RES-TC-NF"])[0]
        self.assertEqual(refreshed["status"], "COMP")
        self.assertEqual(refreshed["dados"]["description"], "Limpeza programada")
        self.assertEqual(self.db.listar_alteracoes_ordens_trabalho(["RES-TC-NF"])[0]["alteracoes"]["status"], {
            "anterior": "PREPARED", "novo": "COMP",
        })

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

    def test_named_team_api_saves_current_team_or_template_only(self):
        self.db.salvar_planejamento([], ["RES-TC-NF"], [profissional()],
                                   roster=[{"id": 1, "nome": "Profissional de teste"}])
        data = plano(planejador="Planner", executantes=[executante(
            ausencias=["2026-11-02"], ajuste_horas=-1,
        )]).model_dump(mode="json")
        result = self.routes.gravar_equipe_nomeada(self.routes.EquipeNomeadaPayload(
            nome="Equipe principal", planejamento=data,
        ))
        self.assertEqual(result["nome"], "Equipe principal")
        self.assertEqual(self.db.obter_equipe(data["setores"]), data)
        self.assertEqual(self.db.listar_equipes_salvas(data["setores"])[0]["planejamento"], data)

        template = {**data, "planejador": "Outro planejador"}
        self.routes.gravar_equipe_nomeada(self.routes.EquipeNomeadaPayload(
            nome="Modelo futuro", planejamento=template, persistir_atual=False,
        ))
        self.assertEqual(self.db.obter_equipe(data["setores"]), data)
        self.assertEqual(len(self.db.listar_equipes_salvas(data["setores"])), 2)

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
