import copy
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from models import database
from services import pcm_planning as pcm


def order(number, kind="S", **fields):
    return {"siteid": "RES", "wonum": number, "status": "PREPARED",
            "maintenanceshop": "RES-PCMTEST", "sincronizado_em": "2026-10-23T12:00:00Z",
            "dados": {"worktype": kind, "description": "PM3 teste", "targstartdate": "2026-10-26",
                      "lead": "", **fields}}


def team():
    return {"setores": ["RES-PCMTEST"], "inicio": "2026-10-26", "fim": "2026-10-27",
            "planejador": "Planejador teste", "executantes": [
                {"orgid": "BR", "matricula": key, "funcao": "180", "jornada": "adm",
                 "capacidade": "dias_8h", "dias_disponiveis": ["2026-10-26", "2026-10-27"]}
                for key in ("TEST1", "TEST2")]}


def labor():
    return {"profissionais": [{"orgid": "BR", "matricula": key, "nome": f"Pessoa {key}",
                              "setor": "RES-PCMTEST", "especialidades": [{"codigo": "180", "descricao": "Mecanica"}]}
                             for key in ("TEST1", "TEST2")]}


def prepared(duration=10, people=2, priority=3):
    return pcm.Requirement(duracao=duration, pessoas=people, orgid="BR", funcao="180",
                           liberada=True, prioridade=priority).model_dump()


def change(doc, **kwargs):
    return pcm.PlanChange(**{
        "revisao": doc["revisao"], "requisitos": doc["requisitos"], "blocos": doc["blocos"],
        "indisponibilidades": doc["indisponibilidades"], "posicionamentos": doc.get("posicionamentos", []),
        "horas_extras": doc.get("horas_extras", []),
        "motivo": "Teste revisao", **kwargs})


class PcmPlanningTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db_patch = patch.object(database, "DB_PATH", Path(temp.name) / "isolated.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_db()
        self.orders = [order("PM1"), order("E1", "E", targstartdate=""), order("OUT", targstartdate="2026-11-19")]
        self.orders[0]["dados"]["sneconstraint"] = "2026-10-26"
        for name, value in (("obter_equipe", team()), ("listar_mao_de_obra", labor()),
                            ("listar_ordens_trabalho", self.orders)):
            mock = patch.object(pcm, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def create(self):
        return pcm.create_plan(["RES-PCMTEST"])

    def test_requirement_persists_cloud_defer_flag(self):
        requirement = pcm.Requirement.model_validate({"na_nuvem": True})

        self.assertTrue(requirement.na_nuvem)
        self.assertTrue(requirement.model_dump()["na_nuvem"])

    def test_validate_plan_allows_work_after_bma_finish_constraint(self):
        doc = self.create()
        key = "RES:PM1"
        doc["ordens"][0]["dados"]["sneconstraint"] = doc["inicio"]
        doc["ordens"][0]["dados"]["fnlconstraint"] = doc["inicio"]
        doc["requisitos"][key].update(duracao=1, pessoas=1)
        doc["blocos"] = [{
            "id": "late-block", "ot": key, "dia": doc["fim"], "inicio": 0,
            "horas": 1, "executantes": [doc["pessoas"][0]["id"]],
        }]

        pcm.validate_plan(doc)

    def test_legacy_planner_registration_is_displayed_with_name(self):
        people = [{"matricula": "B111132", "nome": "Nome do Planejador"}]
        self.assertEqual(
            pcm._planner_display_name("B111132", people),
            "B111132 - Nome do Planejador",
        )
        self.assertEqual(pcm._planner_display_name("OUTRA-MATRICULA", people), "OUTRA-MATRICULA")

    def test_create_is_idempotent_and_corrective_has_no_date_filter(self):
        doc = self.create()
        self.assertEqual([o["wonum"] for o in doc["ordens"]], ["PM1", "E1"])
        self.assertEqual(self.create()["id"], doc["id"])
        self.assertEqual(len(pcm.list_plans()), 1)
        self.assertTrue(pcm.get_pdf(doc["id"], 1).startswith(b"%PDF"))

    def test_add_orders_only_accepts_current_wsch_and_prepared_database_orders(self):
        candidate = order("PM-AVAILABLE", targstartdate="", estdur="3")
        candidate["status"] = "WSCH"
        closed = order("PM-CLOSED", targstartdate="")
        closed["status"] = "COMP"
        wfsch = order("PM-WFSCH", targstartdate="")
        wfsch["status"] = "WFSCH"
        non_pm_type = order("PM-NON-PM-TYPE", kind="A", targstartdate="")
        self.orders.extend([candidate, closed, wfsch, non_pm_type])
        doc = self.create()

        added = pcm.add_orders_to_plan(doc["id"], pcm.AddOrders(
            revisao=doc["revisao"], ordens=["RES:PM-AVAILABLE"],
        ))

        self.assertEqual(added["revisao"], doc["revisao"] + 1)
        self.assertIn("RES:PM-AVAILABLE", added["requisitos"])
        self.assertEqual(added["requisitos"]["RES:PM-AVAILABLE"]["duracao"], 3)
        self.assertTrue(next(order for order in added["ordens"] if order["wonum"] == "PM-AVAILABLE")["planejamento_adicionado"])
        with self.assertRaisesRegex(ValueError, "status WSCH, PREPARED ou WFSCH"):
            pcm.add_orders_to_plan(added["id"], pcm.AddOrders(
                revisao=added["revisao"], ordens=["RES:PM-CLOSED"],
            ))
        with self.assertRaisesRegex(ValueError, "WFSCH só pode voltar"):
            pcm.add_orders_to_plan(added["id"], pcm.AddOrders(
                revisao=added["revisao"], ordens=["RES:PM-WFSCH"],
            ))
        with self.assertRaisesRegex(ValueError, "não estão mais no banco"):
            pcm.add_orders_to_plan(added["id"], pcm.AddOrders(
                revisao=added["revisao"], ordens=["RES:PM-NON-PM-TYPE"],
            ))

    def test_add_orders_restores_wfsch_only_when_cloud_deferred(self):
        self.orders[0]["status"] = "WFSCH"
        doc = self.create()
        requirements = {**doc["requisitos"], "RES:PM1": {**doc["requisitos"]["RES:PM1"], "na_nuvem": True}}
        deferred = pcm.save_plan(doc["id"], change(doc, requisitos=requirements))

        restored = pcm.add_orders_to_plan(deferred["id"], pcm.AddOrders(
            revisao=deferred["revisao"], ordens=["RES:PM1"],
        ))

        self.assertFalse(restored["requisitos"]["RES:PM1"]["na_nuvem"])

    def test_refresh_plan_orders_uses_latest_bma_status_without_losing_requirements(self):
        doc = self.create()
        requirements = copy.deepcopy(doc["requisitos"])
        self.orders[0]["status"] = "COMP"

        result = pcm.refresh_plan_orders(doc["id"], pcm.RefreshPlanOrders(revisao=doc["revisao"]))

        refreshed = result["plano"]
        self.assertEqual(result["atualizadas"], len(doc["ordens"]))
        self.assertEqual(refreshed["revisao"], doc["revisao"] + 1)
        self.assertEqual(next(order["status"] for order in refreshed["ordens"] if order["wonum"] == "PM1"), "COMP")
        self.assertEqual(refreshed["requisitos"], requirements)

    def test_person_pdf_renders_only_activities_assigned_to_that_person(self):
        doc = self.create()
        people = doc["pessoas"][:2]
        keys = ["RES:PM1", "RES:E1"]
        requirements = {key: {**doc["requisitos"][key], "duracao": 1, "pessoas": 1} for key in keys}
        blocks = [
            {"id": "person-pm", "ot": keys[0], "dia": doc["inicio"], "inicio": 0, "horas": 1,
             "executantes": [people[0]["id"]]},
            {"id": "person-corrective", "ot": keys[1], "dia": doc["inicio"], "inicio": 0, "horas": 1,
             "executantes": [people[1]["id"]]},
        ]
        saved = pcm.save_plan(doc["id"], change(doc, requisitos=requirements, blocos=blocks))

        pdf = pcm.get_person_pdf(saved["id"], saved["revisao"], people[0]["id"])

        self.assertTrue(pdf.startswith(b"%PDF"))
        with self.assertRaisesRegex(LookupError, "nao encontrado"):
            pcm.get_person_pdf(saved["id"], saved["revisao"], "BR:UNASSIGNED")

    def test_add_orders_restores_cloud_deferred_order_without_duplication(self):
        doc = self.create()
        requirements = {**doc["requisitos"], "RES:PM1": {**doc["requisitos"]["RES:PM1"], "na_nuvem": True}}
        deferred = pcm.save_plan(doc["id"], change(doc, requisitos=requirements))

        restored = pcm.add_orders_to_plan(deferred["id"], pcm.AddOrders(
            revisao=deferred["revisao"], ordens=["RES:PM1"],
        ))

        self.assertEqual(sum(order["wonum"] == "PM1" for order in restored["ordens"]), 1)
        self.assertFalse(restored["requisitos"]["RES:PM1"]["na_nuvem"])

    def test_preventive_orders_with_lead_or_scheduled_start_are_not_eligible(self):
        legacy = order("PM-LEGACY")
        del legacy["dados"]["lead"]
        self.orders.extend([
            order("PM-LEAD", lead="B114376"),
            order("PM-SCHEDULED", schedstart="2026-10-28T08:00:00-03:00"),
            legacy,
        ])
        eligible = pcm.eligible(["RES-PCMTEST"], "2026-10-26", "2026-10-27")
        self.assertEqual([item["wonum"] for item in eligible], ["PM1", "E1"])
        self.assertTrue(pcm.has_existing_planning_info(legacy))

    def test_preventive_eligibility_uses_not_before_date_before_schedule_end(self):
        self.orders.extend([
            order("PM-BEFORE-END", targstartdate="2026-11-20", sneconstraint="2026-11-12T10:00:00-03:00"),
            order("PM-ON-END", sneconstraint="2026-11-13"),
            order("PM-AFTER-END", sneconstraint="2026-11-20"),
            order("PM-NO-CONSTRAINT", sneconstraint=""),
        ])

        eligible = {item["wonum"] for item in pcm.eligible(["RES-PCMTEST"], "2026-11-09", "2026-11-13")}

        self.assertIn("PM-BEFORE-END", eligible)
        self.assertNotIn("PM-ON-END", eligible)
        self.assertNotIn("PM-AFTER-END", eligible)
        self.assertNotIn("PM-NO-CONSTRAINT", eligible)

    def test_import_bma_schedule_groups_assignments_and_does_not_duplicate_local_blocks(self):
        scheduled = order("PM-BMA", schedstart="2026-10-26T08:00:00-03:00",
                          schedfinish="2026-10-27T10:30:00-03:00")
        self.orders.append(scheduled)
        doc = self.create()
        fresh_order = {
            "siteid": "RES", "wonum": "PM-BMA", "status": "APPR",
            "maintenanceshop": "RES-PCMTEST", "worktype": "E", "description": "Descrição atual do BMA",
            "schedstart": "2026-10-26T08:00:00-03:00", "schedfinish": "2026-10-27T10:30:00-03:00",
        }

        result = pcm.import_bma_schedule(doc["id"], [{
            "siteid": "RES", "numero_ot": "PM-BMA", "situacao_consulta": "sucesso",
            "ordem_bma": fresh_order,
            "dados_adicionais": {"atribuicoes": [
                {"laborcode": "TEST1", "inicio": "26/10/2026 08:00", "horas": "4:00"},
                {"laborcode": "TEST2", "inicio": "26/10/2026 08:00", "horas": "4:00"},
                {"laborcode": "TEST1", "inicio": "27/10/2026 08:00", "horas": "2:30"},
                {"laborcode": "TEST2", "inicio": "27/10/2026 08:00", "horas": "2:30"},
            ]},
        }])

        imported = result["plano"]
        blocks = [block for block in imported["blocos"] if block["ot"] == "RES:PM-BMA"]
        self.assertEqual(result["importadas"], ["PM-BMA"])
        imported_order = next(item for item in imported["ordens"] if item["wonum"] == "PM-BMA")
        self.assertEqual(imported_order["status"], "APPR")
        self.assertEqual(imported_order["dados"]["description"], "Descrição atual do BMA")
        self.assertEqual(imported_order["dados"]["worktype"], "E")
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["executantes"], ["BR:TEST1", "BR:TEST2"])
        self.assertEqual([(block["dia"], block["inicio"], block["horas"]) for block in blocks], [
            ("2026-10-26", 8, 4), ("2026-10-27", 8, 2.5),
        ])
        self.assertEqual(imported["requisitos"]["RES:PM-BMA"]["duracao"], 6.5)
        self.assertEqual(pcm.get_pdf(doc["id"], imported["revisao"])[:4], b"%PDF")

        duplicate = pcm.import_bma_schedule(doc["id"], [{
            "siteid": "RES", "numero_ot": "PM-BMA", "situacao_consulta": "sucesso",
            "dados_adicionais": {"atribuicoes": [
                {"laborcode": "TEST1", "inicio": "26/10/2026 08:00", "horas": "4:00"},
            ]},
        }])
        self.assertEqual(duplicate["plano"]["revisao"], imported["revisao"])
        self.assertEqual(len(duplicate["plano"]["blocos"]), len(imported["blocos"]))
        self.assertIn("já possui blocos locais", duplicate["avisos"][0])

    def test_import_bma_schedule_refreshes_an_order_already_in_the_plan(self):
        doc = self.create()
        fresh_order = {
            "siteid": "RES", "wonum": "PM1", "status": "APPR",
            "maintenanceshop": "RES-PCMTEST", "worktype": "S", "description": "Descrição atualizada",
        }
        result = pcm.import_bma_schedule(doc["id"], [{
            "siteid": "RES", "numero_ot": "PM1", "situacao_consulta": "sucesso",
            "ordem_bma": fresh_order,
            "dados_adicionais": {"atribuicoes": [
                {"laborcode": "TEST1", "inicio": "26/10/2026 08:00", "horas": "2:00"},
            ]},
        }])

        refreshed = next(item for item in result["plano"]["ordens"] if item["wonum"] == "PM1")
        self.assertEqual(refreshed["status"], "APPR")
        self.assertEqual(refreshed["dados"]["description"], "Descrição atualizada")

    def test_import_bma_schedule_keeps_unassigned_orders_available_for_local_planning(self):
        doc = self.create()
        fresh_order = {
            "siteid": "RES", "wonum": "PM-BMA-OPEN", "status": "APPR",
            "maintenanceshop": "RES-PCMTEST", "worktype": "S", "description": "PM sem atribuição",
            "schedstart": "2026-10-26T08:00:00-03:00", "estdur": "5",
        }
        result = pcm.import_bma_schedule(doc["id"], [{
            "siteid": "RES", "numero_ot": "PM-BMA-OPEN", "ordem_bma": fresh_order,
            "dados_adicionais": {"atribuicoes": []},
        }])

        imported = result["plano"]
        order_key = "RES:PM-BMA-OPEN"
        imported_order = next(item for item in imported["ordens"] if pcm.order_key(item) == order_key)
        self.assertTrue(imported_order["planejamento_bma_importado"])
        self.assertEqual(imported["requisitos"][order_key]["duracao"], 5)
        self.assertEqual([block for block in imported["blocos"] if block["ot"] == order_key], [])
        self.assertEqual(result["importadas"], [])
        self.assertTrue(any("pendente de planejamento" in warning for warning in result["avisos"]))

    def test_import_bma_schedule_skips_terminal_orders_with_or_without_assignments(self):
        for status in ("COMP", "CLOSE", "CAN", "CANCELADA"):
            for assignments in ([], [{"laborcode": "TEST1", "inicio": "26/10/2026 08:00", "horas": "2:00"}]):
                with self.subTest(status=status, assigned=bool(assignments)):
                    doc = self.create()
                    number = f"PM-BMA-{status}-{bool(assignments)}"
                    fresh_order = {
                        "siteid": "RES", "wonum": number, "status": status,
                        "maintenanceshop": "RES-PCMTEST", "worktype": "S", "estdur": "2",
                    }
                    result = pcm.import_bma_schedule(doc["id"], [{
                        "siteid": "RES", "numero_ot": number, "ordem_bma": fresh_order,
                        "dados_adicionais": {"atribuicoes": assignments},
                    }])

                    imported = result["plano"]
                    self.assertFalse(any(item["wonum"] == number for item in imported["ordens"]))
                    self.assertFalse(any(block["ot"] == f"RES:{number}" for block in imported["blocos"]))
                    self.assertNotIn(number, result["importadas"])
                    self.assertTrue(any(status in warning and "nem na carteira" in warning
                                        for warning in result["avisos"]))

    def test_import_bma_schedule_skips_unavailable_assignments_without_aborting_other_orders(self):
        doc = self.create()
        absence = {"executante": "BR:TEST1", "dia": "2026-10-26", "motivo": "Falta"}
        doc = pcm.save_plan(doc["id"], change(doc, indisponibilidades=[absence]))
        conflicting_order = {
            "siteid": "RES", "wonum": "PM-BMA-CONFLICT", "status": "APPR",
            "maintenanceshop": "RES-PCMTEST", "worktype": "S", "description": "PM com conflito",
            "estdur": "2",
        }
        valid_order = {
            "siteid": "RES", "wonum": "PM-BMA-VALID", "status": "APPR",
            "maintenanceshop": "RES-PCMTEST", "worktype": "S", "description": "PM sem conflito",
            "estdur": "2",
        }

        result = pcm.import_bma_schedule(doc["id"], [
            {"siteid": "RES", "numero_ot": "PM-BMA-CONFLICT", "ordem_bma": conflicting_order,
             "dados_adicionais": {"atribuicoes": [
                 {"laborcode": "TEST1", "inicio": "26/10/2026 08:00", "horas": "2:00"},
             ]}},
            {"siteid": "RES", "numero_ot": "PM-BMA-VALID", "ordem_bma": valid_order,
             "dados_adicionais": {"atribuicoes": [
                 {"laborcode": "TEST2", "inicio": "26/10/2026 08:00", "horas": "2:00"},
             ]}},
        ])

        imported = result["plano"]
        conflicting_key = "RES:PM-BMA-CONFLICT"
        valid_key = "RES:PM-BMA-VALID"
        self.assertIn("PM-BMA-VALID", result["importadas"])
        self.assertNotIn("PM-BMA-CONFLICT", result["importadas"])
        self.assertFalse(any(block["ot"] == conflicting_key for block in imported["blocos"]))
        self.assertTrue(any(block["ot"] == valid_key for block in imported["blocos"]))
        self.assertIn(absence, imported["indisponibilidades"])
        self.assertTrue(any("PM-BMA-CONFLICT" in warning and "remanejamento" in warning
                            for warning in result["avisos"]))

    def test_import_validation_failure_for_one_order_does_not_abort_the_batch(self):
        doc = self.create()
        conflicting_order = {
            "siteid": "RES", "wonum": "PM-BMA-VALIDATION-CONFLICT", "status": "APPR",
            "maintenanceshop": "RES-PCMTEST", "worktype": "S", "estdur": "2",
        }
        valid_order = {
            "siteid": "RES", "wonum": "PM-BMA-VALIDATION-OK", "status": "APPR",
            "maintenanceshop": "RES-PCMTEST", "worktype": "S", "estdur": "2",
        }
        results = [
            {"siteid": "RES", "numero_ot": conflicting_order["wonum"], "ordem_bma": conflicting_order,
             "dados_adicionais": {"atribuicoes": [
                 {"laborcode": "TEST1", "inicio": "26/10/2026 08:00", "horas": "2:00"},
             ]}},
            {"siteid": "RES", "numero_ot": valid_order["wonum"], "ordem_bma": valid_order,
             "dados_adicionais": {"atribuicoes": [
                 {"laborcode": "TEST2", "inicio": "26/10/2026 08:00", "horas": "2:00"},
             ]}},
        ]
        original_validate = pcm.validate_plan

        def reject_conflicting_order(candidate, *args, **kwargs):
            if any(block["ot"] == "RES:PM-BMA-VALIDATION-CONFLICT" for block in candidate["blocos"]):
                raise ValueError("Pessoa indisponível em 2026-10-26.")
            original_validate(candidate, *args, **kwargs)

        with patch.object(pcm, "validate_plan", side_effect=reject_conflicting_order):
            result = pcm.import_bma_schedule(doc["id"], results)

        imported = result["plano"]
        self.assertIn("PM-BMA-VALIDATION-OK", result["importadas"])
        self.assertNotIn("PM-BMA-VALIDATION-CONFLICT", result["importadas"])
        self.assertTrue(any(pcm.order_key(item) == "RES:PM-BMA-VALIDATION-CONFLICT"
                            for item in imported["ordens"]))
        self.assertFalse(any(block["ot"] == "RES:PM-BMA-VALIDATION-CONFLICT"
                             for block in imported["blocos"]))
        self.assertTrue(any(block["ot"] == "RES:PM-BMA-VALIDATION-OK"
                            for block in imported["blocos"]))
        self.assertTrue(any("Pessoa indisponível" in warning for warning in result["avisos"]))

    def test_delete_plan_removes_plan_and_all_revisions(self):
        doc = self.create()
        saved = pcm.save_plan(doc["id"], change(doc))
        self.assertEqual(len(pcm.revisions(doc["id"])), 2)
        self.assertEqual(pcm.delete_plan(doc["id"]), {"id": doc["id"], "deleted": True})
        self.assertEqual(pcm.list_plans(), [])
        with self.assertRaises(LookupError):
            pcm.get_plan(doc["id"])
        with database.get_connection() as conn:
            remaining = conn.execute("SELECT COUNT(*) FROM pcm_revisoes WHERE plano_id=?", (saved["id"],)).fetchone()[0]
        self.assertEqual(remaining, 0)

    def test_delete_missing_plan_raises_not_found(self):
        with self.assertRaisesRegex(LookupError, "Planejamento nao encontrado"):
            pcm.delete_plan("missing")

    def test_team_update_changes_only_plan_snapshot_and_creates_revision(self):
        original_team = team()
        original_team["executantes"] = original_team["executantes"][:1]
        with patch.object(pcm, "obter_equipe", return_value=original_team):
            doc = self.create()
            self.assertEqual(len(doc["pessoas"]), 1)
            updated = pcm.update_plan_team(doc["id"], pcm.PlanTeamChange(revisao=doc["revisao"], equipe=team()))
            self.assertEqual(updated["revisao"], doc["revisao"] + 1)
            self.assertEqual(len(updated["pessoas"]), 2)
            self.assertEqual(len(updated["equipe"]["executantes"]), 2)
            self.assertEqual(len(pcm.revisions(doc["id"])), 2)
            self.assertEqual(len(pcm.obter_equipe(["RES-PCMTEST"])["executantes"]), 1)

    def test_team_update_rejects_removing_an_allocated_executor(self):
        doc = self.prepared_doc()
        first_person = doc["pessoas"][0]["id"]
        block = {"id": "block-1", "ot": "RES:E1", "dia": "2026-10-26", "inicio": 0,
                 "horas": 1, "executantes": [first_person]}
        doc["blocos"] = [block]
        with database.get_connection() as conn:
            conn.execute("UPDATE pcm_planos SET dados_json=? WHERE id=?", (json.dumps(doc), doc["id"]))
        changed_team = team()
        changed_team["executantes"] = changed_team["executantes"][1:]
        with self.assertRaisesRegex(ValueError, "não pode remover executantes usados"):
            pcm.update_plan_team(doc["id"], pcm.PlanTeamChange(revisao=doc["revisao"], equipe=changed_team))

    def test_missing_requirements_are_not_invented(self):
        doc = self.create()
        self.assertIsNone(doc["requisitos"]["RES:PM1"]["duracao"])
        result = pcm.suggest(doc, pcm.Suggestion(modo="pm", alteracoes=change(doc)))
        self.assertEqual(result["blocos"], [])
        self.assertIn("preparacao", result["mensagens"][0])

    def test_positioned_card_persists_without_fabricating_hours_and_blocks_confirmation(self):
        doc = self.prepared_doc()
        doc["posicionamentos"] = [{"ot": "RES:E1", "executante": "BR:TEST1", "dia": doc["fim"]}]
        saved = pcm.save_plan(doc["id"], change(doc))
        self.assertEqual(saved["blocos"], doc["blocos"])
        self.assertEqual(pcm.get_plan(doc["id"])["posicionamentos"], doc["posicionamentos"])
        with self.assertRaisesRegex(ValueError, "posicionadas"):
            pcm.save_plan(doc["id"], change(saved, confirmar=True))
        saved["posicionamentos"] = []
        self.assertEqual(pcm.save_plan(doc["id"], change(saved, confirmar=True))["status"], "confirmado")

    def test_positioned_card_rejects_invalid_target_or_duplicate(self):
        doc = self.prepared_doc()
        for placements in (
            [{"ot": "RES:E1", "executante": "OUTSIDE", "dia": doc["fim"]}],
            [{"ot": "OUTSIDE", "executante": "BR:TEST1", "dia": doc["fim"]}],
            [{"ot": "RES:E1", "executante": "BR:TEST1", "dia": "2026-11-02"}],
            [{"ot": "RES:E1", "executante": "BR:TEST1", "dia": doc["fim"]}] * 2,
        ):
            with self.subTest(placements=placements), self.assertRaisesRegex(ValueError, "Posicionamento"):
                pcm.save_plan(doc["id"], change(doc, posicionamentos=placements))

    def test_collected_labor_populates_single_specialty_and_quantity_without_inventing_duration(self):
        self.orders[0]["dados"]["wplabor"] = [{"especialidade": "180", "quantidade": "2", "horas normais": "40"}]
        doc = self.create()
        req = doc["requisitos"]["RES:PM1"]
        self.assertEqual((req["funcao"], req["orgid"], req["pessoas"]), ("180", "BR", 2))
        self.assertIsNone(req["duracao"])

    def test_refresh_labor_preserves_manual_preparation_allocations_and_persists_only_on_save(self):
        doc = self.prepared_doc()
        before = pcm.get_plan(doc["id"])
        self.orders[0]["dados"]["wplabor"] = [{"craft": "270", "quantity": 1, "laborhrs": 40, "orgid": "BR"}]
        # Existing snapshots are not silently changed.
        refreshed = pcm.refresh_labor(doc, change(doc))["plano"]
        self.assertEqual(refreshed["requisitos"]["RES:PM1"]["funcao"], "180")
        self.assertEqual(refreshed["blocos"], doc["blocos"])
        self.assertEqual(pcm.get_plan(doc["id"]), before)
        saved = pcm.save_plan(doc["id"], change(refreshed, atualizar_especialidades=True))
        self.assertEqual(saved["ordens"][0]["dados"]["wplabor"][0]["craft"], "270")
        self.assertEqual(pcm.get_plan(doc["id"])["ordens"][0]["dados"]["wplabor"], self.orders[0]["dados"]["wplabor"])

    def test_refresh_missing_collection_is_explicit_and_multiple_crafts_are_not_collapsed(self):
        doc = self.create()
        with self.assertRaisesRegex(ValueError, "Atualize o banco"):
            pcm.refresh_labor(doc, change(doc))
        self.orders[0]["dados"]["wplabor"] = [{"craft": "180", "quantity": 1}, {"craft": "270", "quantity": 2}]
        updated = pcm.refresh_labor(doc, change(doc))["plano"]
        self.assertEqual(len(updated["ordens"][0]["dados"]["wplabor"]), 2)
        self.assertEqual(updated["requisitos"]["RES:PM1"]["funcao"], "")
        self.assertEqual(updated["requisitos"]["RES:PM1"]["pessoas"], 3)

    def test_all_specialties_suggests_and_saves_mixed_crew_but_keeps_availability_checks(self):
        mixed_labor = labor()
        mixed_labor["profissionais"][1]["especialidades"] = [{"codigo": "210", "descricao": "Eletrica"}]
        mixed_team = team()
        mixed_team["executantes"][1]["funcao"] = "210"
        with (patch.object(pcm, "obter_equipe", return_value=mixed_team),
              patch.object(pcm, "listar_mao_de_obra", return_value=mixed_labor)):
            doc = self.create()
            doc["requisitos"]["RES:PM1"] = pcm.Requirement(
                duracao=4, pessoas=2, todas_especialidades=True, liberada=True).model_dump()
            suggested = pcm.suggest(doc, pcm.Suggestion(modo="pm", alteracoes=change(doc)))
            self.assertEqual(len(suggested["blocos"]), 1)
            self.assertEqual(set(suggested["blocos"][0]["executantes"]), {"BR:TEST1", "BR:TEST2"})
            doc["blocos"] = suggested["blocos"]
            saved = pcm.save_plan(doc["id"], change(doc, confirmar=True))
            self.assertTrue(pcm.get_plan(doc["id"])["requisitos"]["RES:PM1"]["todas_especialidades"])
            saved["indisponibilidades"] = [{"executante": "BR:TEST2", "dia": "2026-10-26", "motivo": "Falta"}]
            with self.assertRaisesRegex(ValueError, "indisponivel"):
                pcm.save_plan(doc["id"], change(saved))
            saved["indisponibilidades"] = []
            saved["requisitos"]["RES:PM1"].update(todas_especialidades=False, orgid="BR", funcao="180")
            cross_specialty = pcm.save_plan(doc["id"], change(saved))
            self.assertEqual(cross_specialty["blocos"][0]["executantes"], ["BR:TEST1", "BR:TEST2"])

    def test_mismatched_specialty_does_not_block_manual_assignment(self):
        mixed_labor = labor()
        mixed_labor["profissionais"][1]["especialidades"] = [{"codigo": "210", "descricao": "Eletrica"}]
        mixed_team = team()
        mixed_team["executantes"][1]["funcao"] = "210"
        with (patch.object(pcm, "obter_equipe", return_value=mixed_team),
              patch.object(pcm, "listar_mao_de_obra", return_value=mixed_labor)):
            doc = self.create()
            doc["requisitos"]["RES:PM1"] = prepared(4, 1)
            doc["blocos"] = [{"id": "mixed", "ot": "RES:PM1", "dia": "2026-10-26", "inicio": 0,
                              "horas": 4, "executantes": ["BR:TEST2"]}]
            saved = pcm.save_plan(doc["id"], change(doc))
            self.assertEqual(saved["blocos"][0]["executantes"], ["BR:TEST2"])

    def test_multiday_simultaneous_crew_and_corrective_use_remaining_capacity(self):
        doc = self.create()
        doc["requisitos"]["RES:PM1"] = prepared()
        doc["requisitos"]["RES:E1"] = prepared(6, 2)
        pm = pcm.suggest(doc, pcm.Suggestion(modo="pm", alteracoes=change(doc)))
        self.assertEqual([b["horas"] for b in pm["blocos"]], [8, 2])
        self.assertTrue(all(len(b["executantes"]) == 2 for b in pm["blocos"]))
        doc["blocos"] = pm["blocos"]
        corrective = pcm.suggest(doc, pcm.Suggestion(modo="corretiva", alteracoes=change(doc)))
        self.assertEqual(corrective["blocos"][:2], pm["blocos"])
        self.assertEqual(corrective["blocos"][-1]["dia"], "2026-10-27")
        self.assertEqual(corrective["blocos"][-1]["inicio"], 0)
        self.assertEqual(corrective["blocos"][-1]["horas"], 6)
        doc["blocos"] = corrective["blocos"]
        saved = pcm.save_plan(doc["id"], change(doc, confirmar=True))
        self.assertEqual(saved["status"], "confirmado")
        self.assertEqual(saved["revisao"], 2)
        self.assertEqual(pcm.get_plan(doc["id"], 1)["blocos"], [])
        self.assertTrue(pcm.get_pdf(doc["id"], 2).startswith(b"%PDF"))
        self.assertEqual(saved["integracoes"]["bma"], "pendente_configuracao")
        with self.assertRaises(pcm.ConflictError):
            pcm.save_plan(doc["id"], change(doc))

    def prepared_doc(self):
        doc = self.create()
        doc["requisitos"]["RES:PM1"] = prepared(4, 1)
        doc["requisitos"]["RES:E1"] = prepared(4, 1)
        doc["blocos"] = [
            {"id": "a", "ot": "RES:PM1", "dia": "2026-10-26", "inicio": 0, "horas": 4,
             "executantes": ["BR:TEST1"]}]
        return doc

    def test_capacity_absence_horizon_and_duplicate_crew_are_rejected(self):
        original = self.prepared_doc()
        cases = []
        doc = copy.deepcopy(original)
        doc["blocos"].append({**doc["blocos"][0], "id": "b", "ot": "RES:E1", "inicio": 3})
        # Draft overlaps are permitted; operational confirmation remains strict.
        doc = copy.deepcopy(original)
        doc["indisponibilidades"] = [{"executante": "BR:TEST1", "dia": "2026-10-26", "motivo": "Falta"}]
        cases.append(doc)
        doc = copy.deepcopy(original)
        doc["blocos"][0]["dia"] = "2026-10-28"
        cases.append(doc)
        doc = copy.deepcopy(original)
        doc["blocos"][0]["executantes"] = ["BR:TEST1", "BR:TEST1"]
        cases.append(doc)
        for index, doc in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                pcm.save_plan(doc["id"], change(doc))
        self.assertEqual(pcm.get_plan(original["id"])["revisao"], 1)

    def test_draft_overload_persists_but_confirmation_is_blocked(self):
        doc = self.prepared_doc()
        doc["requisitos"]["RES:E1"]["duracao"] = 14
        doc["blocos"].append({**doc["blocos"][0], "id": "over", "ot": "RES:E1", "inicio": 2})
        doc["blocos"][1]["horas"] = 14
        saved = pcm.save_plan(doc["id"], change(doc))
        self.assertEqual(len(pcm.get_plan(doc["id"])["blocos"]), 2)
        with self.assertRaisesRegex(ValueError, "capacidade semanal"):
            pcm.save_plan(doc["id"], change(saved, confirmar=True))
        saved["blocos"][1]["executantes"] = ["BR:TEST2"]
        confirmed = pcm.save_plan(doc["id"], change(saved, confirmar=True))
        self.assertEqual(confirmed["status"], "confirmado")

    def test_twelve_hours_with_ten_free_saves_two_excess_only_in_draft(self):
        doc = self.prepared_doc()
        doc["requisitos"]["RES:PM1"]["duracao"] = 12
        doc["requisitos"]["RES:E1"]["duracao"] = 6
        base = doc["blocos"][0]
        doc["blocos"] = [
            {**base, "id": "existing", "ot": "RES:E1", "horas": 6},
            {**base, "id": "free2", "inicio": 6, "horas": 2},
            {**base, "id": "free8", "dia": "2026-10-27", "horas": 8},
            {**base, "id": "excess2", "horas": 2},
        ]
        saved = pcm.save_plan(doc["id"], change(doc))
        self.assertEqual(sum(b["horas"] for b in saved["blocos"]), 18)
        with self.assertRaisesRegex(ValueError, "capacidade semanal"):
            pcm.save_plan(doc["id"], change(saved, confirmar=True))

    def test_confirmed_plan_cannot_save_overloaded_operational_revision(self):
        doc = self.prepared_doc()
        saved = pcm.save_plan(doc["id"], change(doc, confirmar=True))
        saved["requisitos"]["RES:E1"]["duracao"] = 14
        saved["blocos"].append({**saved["blocos"][0], "id": "over", "ot": "RES:E1", "inicio": 2})
        saved["blocos"][1]["horas"] = 14
        with self.assertRaisesRegex(ValueError, "capacidade semanal"):
            pcm.save_plan(doc["id"], change(saved))
        persisted = pcm.get_plan(doc["id"])
        self.assertEqual(persisted["revisao"], saved["revisao"])
        self.assertEqual(persisted["status"], "confirmado")

    def test_marked_orders_must_be_allocated_and_suggestion_uses_only_selected_subset(self):
        doc = self.prepared_doc()
        doc["blocos"] = []
        doc["requisitos"]["RES:PM1"]["selecionada"] = True
        doc["requisitos"]["RES:E1"]["selecionada"] = True
        result = pcm.suggest(doc, pcm.Suggestion(modo="pm", ordens=[], alteracoes=change(doc)))
        self.assertEqual(result["blocos"], [])
        result = pcm.suggest(doc, pcm.Suggestion(modo="pm", ordens=["RES:PM1"], alteracoes=change(doc)))
        doc["blocos"] = result["blocos"]
        saved = pcm.save_plan(doc["id"], change(doc))
        self.assertTrue(saved["requisitos"]["RES:E1"]["selecionada"])
        with self.assertRaisesRegex(ValueError, "marcada"):
            pcm.save_plan(doc["id"], change(saved, confirmar=True))

    def test_daily_twelve_hours_without_start_time_can_be_confirmed(self):
        doc = self.prepared_doc()
        doc["requisitos"]["RES:PM1"]["duracao"] = 12
        doc["blocos"][0]["horas"] = 12
        doc["blocos"][0]["inicio"] = 6  # Legacy offset is discarded by new revisions.
        saved = pcm.save_plan(doc["id"], change(doc, confirmar=True))
        self.assertEqual(saved["blocos"][0]["inicio"], 0)
        self.assertEqual(saved["blocos"][0]["horas"], 12)
        self.assertEqual(saved["status"], "confirmado")

    def test_explicit_overtime_extends_weekly_capacity_and_is_saved(self):
        doc = self.prepared_doc()
        doc["requisitos"]["RES:PM1"]["duracao"] = 18
        doc["blocos"][0]["horas"] = 18
        doc["horas_extras"] = [{
            "ot": "RES:PM1", "executante": "BR:TEST1", "dia": "2026-10-26", "horas": 2,
        }]

        saved = pcm.save_plan(doc["id"], change(doc, confirmar=True))

        self.assertEqual(saved["horas_extras"], doc["horas_extras"])
        from services.pcm_capacity import weekly_totals
        total = weekly_totals([saved])[("BR:TEST1", "2026-10-26")]
        self.assertEqual(total, {"capacidade": 18, "horas": 18})

        saved["horas_extras"][0]["horas"] = 19
        with self.assertRaisesRegex(ValueError, "Hora extra invalida"):
            pcm.validate_plan(saved, confirming=True)

    def test_resource_checkbox_is_no_longer_required(self):
        doc = self.prepared_doc()
        doc["requisitos"]["RES:PM1"]["liberada"] = False
        pcm.validate_plan(doc, confirming=True)
        doc["blocos"] = []
        result = pcm.suggest(doc, pcm.Suggestion(modo="pm", alteracoes=change(doc)))
        self.assertEqual(sum(b["horas"] for b in result["blocos"]), 4)

    def test_capacity_is_individual_per_calendar_week_and_absences_reduce_it(self):
        from services.pcm_capacity import weekly_totals, overloaded_blocks
        doc = self.prepared_doc()
        doc["fim"] = "2026-11-02"
        doc["pessoas"][0]["dias"].append("2026-11-02")
        doc["blocos"][0]["horas"] = 18
        totals = weekly_totals([doc])
        self.assertEqual(totals[("BR:TEST1", "2026-10-26")]["capacidade"], 16)
        self.assertEqual(totals[("BR:TEST1", "2026-11-02")]["capacidade"], 8)
        self.assertEqual(overloaded_blocks(doc), {"a"})
        doc["indisponibilidades"] = [{"executante": "BR:TEST1", "dia": "2026-10-27", "motivo": "Falta"}]
        self.assertEqual(weekly_totals([doc])[("BR:TEST1", "2026-10-26")]["capacidade"], 8)

    def test_activity_cannot_continue_automatically_into_next_week(self):
        doc = self.prepared_doc()
        doc["fim"] = "2026-11-02"
        doc["pessoas"][0]["dias"].append("2026-11-02")
        doc["requisitos"]["RES:PM1"]["duracao"] = 20
        doc["blocos"] = []
        result = pcm.suggest(doc, pcm.Suggestion(modo="pm", alteracoes=change(doc)))
        self.assertEqual(sum(b["horas"] for b in result["blocos"]), 16)
        self.assertTrue(all(b["dia"] < "2026-11-02" for b in result["blocos"]))
        doc["blocos"] = result["blocos"] + [{
            **result["blocos"][0], "id": "nextweek", "dia": "2026-11-02", "horas": 4}]
        with self.assertRaisesRegex(ValueError, "mesma semana"):
            pcm.save_plan(doc["id"], change(doc))

    def test_suggestion_respects_execution_window_and_balances_days_and_workers(self):
        doc = self.prepared_doc()
        doc["inicio"] = "2026-11-03"
        doc["fim"] = "2026-11-07"
        doc["equipe"]["inicio"] = doc["inicio"]
        doc["equipe"]["fim"] = doc["fim"]
        planning_days = ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07"]
        for person in doc["pessoas"]:
            person["dias"] = planning_days
        doc["ordens"][0]["dados"].update(
            targstartdate="2026-11-02", targcompdate="2026-11-05",
            sneconstraint="2026-10-30", fnlconstraint="2026-11-05",
        )
        doc["requisitos"]["RES:PM1"] = prepared(duration=16, people=1)
        doc["blocos"] = []

        result = pcm.suggest(doc, pcm.Suggestion(modo="pm", alteracoes=change(doc)))
        blocks = [block for block in result["blocos"] if block["ot"] == "RES:PM1"]

        self.assertEqual(sum(block["horas"] for block in blocks), 16)
        self.assertTrue(all("2026-11-03" <= block["dia"] <= "2026-11-05" for block in blocks))
        self.assertEqual({block["dia"] for block in blocks}, {"2026-11-03", "2026-11-04"})
        self.assertEqual({block["executantes"][0] for block in blocks}, {"BR:TEST1", "BR:TEST2"})

    def test_partial_activity_can_be_draft_but_cannot_be_confirmed(self):
        doc = self.prepared_doc()
        doc["requisitos"]["RES:PM1"]["duracao"] = 6
        saved = pcm.save_plan(doc["id"], change(doc))
        with self.assertRaisesRegex(ValueError, "parcialmente"):
            pcm.save_plan(saved["id"], change(saved, confirmar=True))

    def test_absence_and_resource_postponement_create_immutable_revision(self):
        doc = self.prepared_doc()
        saved = pcm.save_plan(doc["id"], change(doc, confirmar=True))
        old_pdf = pcm.get_pdf(saved["id"], saved["revisao"])
        saved["blocos"] = [{**saved["blocos"][0], "executantes": ["BR:TEST2"]}]
        saved["indisponibilidades"] = [{"executante": "BR:TEST1", "dia": "2026-10-26", "motivo": "Falta"}]
        updated = pcm.save_plan(saved["id"], change(saved, motivo="Substituicao por falta"))
        self.assertEqual(updated["revisao"], 3)
        self.assertEqual(pcm.get_pdf(saved["id"], 2), old_pdf)
        self.assertEqual(pcm.get_plan(saved["id"], 2)["blocos"][0]["executantes"], ["BR:TEST1"])
        self.assertEqual(len(pcm.revisions(saved["id"])), 3)
        updated["blocos"] = []
        updated["requisitos"]["RES:PM1"]["liberada"] = False
        updated["requisitos"]["RES:PM1"]["observacao"] = "Recurso indisponivel; atividade postergada"
        postponed = pcm.save_plan(updated["id"], change(updated, motivo="Postergacao por recurso"))
        self.assertEqual(postponed["status"], "confirmado")
        self.assertEqual(postponed["blocos"], [])

    def test_suggestion_honors_constraint_dates_and_priority(self):
        self.orders[0]["dados"]["sneconstraint"] = "2026-10-27"
        doc = self.create()
        doc["requisitos"]["RES:PM1"] = prepared(4, 1)
        result = pcm.suggest(doc, pcm.Suggestion(modo="pm", alteracoes=change(doc)))
        self.assertEqual(result["blocos"][0]["dia"], "2026-10-27")
        doc["blocos"] = [{**result["blocos"][0], "dia": "2026-10-26"}]
        with self.assertRaisesRegex(ValueError, "restricao"):
            pcm.save_plan(doc["id"], change(doc))

    def test_overlapping_confirmed_plans_cannot_double_book_people_or_orders(self):
        doc = self.prepared_doc()
        confirmed = pcm.save_plan(doc["id"], change(doc, confirmar=True))
        other_team = team()
        other_team["fim"] = "2026-10-28"
        for member in other_team["executantes"]:
            member["dias_disponiveis"].append("2026-10-28")
        with patch.object(pcm, "obter_equipe", return_value=other_team):
            other = self.create()
        other["requisitos"]["RES:E1"] = prepared(4, 1)
        other["blocos"] = [{**confirmed["blocos"][0], "id": "other", "ot": "RES:E1"}]
        # Same day is allowed: only the combined weekly capacity is binding.
        pcm.save_plan(other["id"], change(other, confirmar=True))
        other = pcm.get_plan(other["id"])
        other["requisitos"]["RES:E1"] = prepared(22, 1)
        other["blocos"][0]["horas"] = 22
        with self.assertRaisesRegex(ValueError, "comprometido"):
            pcm.save_plan(other["id"], change(other, confirmar=True))
        other["requisitos"]["RES:PM1"] = prepared(4, 1)
        other["blocos"] = [{**confirmed["blocos"][0], "id": "other", "executantes": ["BR:TEST2"]}]
        with self.assertRaisesRegex(ValueError, "OT ja"):
            pcm.save_plan(other["id"], change(other, confirmar=True))

    def test_xlsx_is_exact_filtered_subset_and_literal_formula_with_brazilian_date(self):
        self.orders[0]["dados"]["description"] = "PM3 = literal"
        self.orders[1]["dados"]["description"] = "=HYPERLINK(\"evil\")"
        data = pcm.spreadsheet(pcm.ExportOrders(setores=["RES-PCMTEST"], inicio="2026-10-26",
                                                fim="2026-10-27", modo="corretiva", ordens=["RES:E1"]))
        sheet = load_workbook(BytesIO(data)).active
        self.assertEqual(sheet.max_row, 2)
        self.assertEqual(sheet.cell(2, 1).value, "E1")
        self.assertEqual(sheet.cell(2, 2).data_type, "s")
        self.assertEqual(sheet.cell(2, 2).value, '=HYPERLINK("evil")')
        without_period = pcm.spreadsheet(pcm.ExportOrders(setores=["RES-PCMTEST"], modo="corretiva", ordens=["RES:E1"]))
        self.assertEqual(load_workbook(BytesIO(without_period)).active.max_row, 2)
        data = pcm.spreadsheet(pcm.ExportOrders(setores=["RES-PCMTEST"], inicio="2026-10-26",
                                                fim="2026-10-27", modo="pm", ordens=["RES:PM1"]))
        self.assertEqual(load_workbook(BytesIO(data)).active.cell(2, 10).number_format, "DD/MM/YYYY")
        with self.assertRaises(ValueError):
            pcm.spreadsheet(pcm.ExportOrders(setores=["RES-PCMTEST"], inicio="2026-10-26",
                                            fim="2026-10-27", modo="pm", ordens=["RES:OUT"]))

    def test_http_contract_error_mapping_and_binary_documents(self):
        from api.pcm import create, export, get, pdf, save
        from fastapi import HTTPException
        doc = create(pcm.NewPlan(setores=["RES-PCMTEST"]))
        self.assertEqual(get(doc["id"])["id"], doc["id"])
        self.assertEqual(pdf(doc["id"], 1).media_type, "application/pdf")
        self.assertEqual(export(pcm.ExportOrders(setores=["RES-PCMTEST"], inicio="2026-10-26",
                                                fim="2026-10-27", modo="pm", ordens=[])).status_code, 200)
        doc["requisitos"]["RES:PM1"] = prepared(1, 1)
        doc["blocos"] = [{"id": "a", "ot": "RES:PM1", "dia": "2026-10-26",
                          "inicio": 7, "horas": 2, "executantes": ["BR:TEST1"]}]
        with self.assertRaises(HTTPException) as invalid:
            save(doc["id"], change(doc))
        self.assertEqual(invalid.exception.status_code, 400)
        with self.assertRaises(HTTPException) as missing:
            get("unknown")
        self.assertEqual(missing.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
