import copy
import importlib.util
import unittest

from services.pcm_pdf import render_schedule, summary


def example_plan():
    people = [{"id": f"BR:TEST{i}", "nome": f"Executante exemplo {i}", "dias": [
        f"2026-10-{day}" for day in range(26, 31)]} for i in range(1, 4)]
    doc = {
        "id": "demonstracao-layout-pcm", "revisao": 1, "status": "rascunho",
        "inicio": "2026-10-26", "fim": "2026-10-30", "planejador": "DEMONSTRAÇÃO · dados fictícios",
        "setores": ["NFE · EXEMPLO VISUAL"], "atualizado_em": "2026-10-23T15:00:00Z",
        "motivo": "Prévia do novo formato. Não representa planejamento operacional.",
        "pessoas": people, "ordens": [], "requisitos": {}, "blocos": [], "indisponibilidades": [],
    }
    activities = ["Inspeção de motores e ventiladores", "Verificação de bombas e conexões",
                  "Limpeza e inspeção de filtros", "Ajuste e teste de válvulas", "Inspeção de painéis"]
    for day in range(26, 31):
        for index, activity in enumerate(activities):
            number = f"EXEMPLO-{day}{index}"
            key = f"RES:{number}"
            order = {"siteid": "RES", "wonum": number, "dados": {
                "description": f"PM{index % 3 + 1} - {activity}", "location": f"LOCAL {index + 1}",
                "worktype": "S" if index < 4 else "E"}}
            doc["ordens"].append(order)
            doc["requisitos"][key] = {"duracao": 1, "observacao": ""}
            doc["blocos"].append({"id": number, "ot": key, "dia": f"2026-10-{day}",
                                  "inicio": index, "horas": 1, "executantes": [people[index % 3]["id"]]})
    return doc


class PdfSummaryTests(unittest.TestCase):
    def test_real_metrics_count_unique_orders_resources_and_person_hours(self):
        doc = example_plan()
        doc["blocos"][0]["horas"] = .5
        doc["blocos"].append({**doc["blocos"][0], "id": "split", "dia": "2026-10-27"})
        doc["blocos"][1]["executantes"] = ["BR:TEST1", "BR:TEST2"]
        doc["ordens"].append({"siteid": "RES", "wonum": "OUT", "dados": {}})
        doc["requisitos"]["RES:OUT"] = {"duracao": None, "observacao": "Sem recurso"}
        doc["indisponibilidades"] = [{"executante": "BR:TEST3", "dia": "2026-10-30", "motivo": "Falta"}]
        data = summary(doc)
        self.assertEqual(data["hours"], 26)
        self.assertEqual(data["capacity"], 112)
        self.assertEqual(data["people"], 3)
        self.assertEqual(data["locations"], 5)
        self.assertEqual(len(data["groups"]["Programadas"]), 25)
        self.assertEqual(data["groups"]["Não alocadas"], ["RES:OUT"])

    def test_empty_plan_and_partial_allocation_are_not_reported_as_complete(self):
        doc = example_plan()
        doc["blocos"] = []
        data = summary(doc)
        self.assertEqual(data["hours"], 0)
        self.assertEqual(data["people"], 0)
        self.assertEqual(data["groups"]["Programadas"], [])
        self.assertTrue(render_schedule(doc).startswith(b"%PDF"))
        doc["blocos"] = [{"id": "partial", "ot": "RES:EXEMPLO-260", "dia": "2026-10-26",
                          "horas": .5, "inicio": 0, "executantes": ["BR:TEST1"]}]
        self.assertEqual(summary(doc)["groups"]["Parciais"], ["RES:EXEMPLO-260"])
        self.assertTrue(render_schedule(doc).startswith(b"%PDF"))


@unittest.skipUnless(importlib.util.find_spec("pymupdf"), "Optional PDF inspection requires pymupdf")
class PdfLayoutTests(unittest.TestCase):
    def parse(self, doc):
        import pymupdf
        return pymupdf.open(stream=render_schedule(doc), filetype="pdf")

    def test_schedule_shows_target_finish_as_data_limite(self):
        doc = example_plan()
        doc["ordens"][0]["dados"]["targcompdate"] = "2026-11-02T10:00:00-03:00"
        pdf = self.parse(doc)
        lines = "\n".join(page.get_text() for page in pdf).splitlines()
        self.assertIn("Data Limite", lines)
        self.assertIn("02/11/2026", lines)
        self.assertNotIn("Programada", lines)

    def test_schedule_preserves_saved_sequence_instead_of_sorting_ot_numbers(self):
        doc = example_plan()
        doc["blocos"] = list(reversed(doc["blocos"][:3]))
        pdf = self.parse(doc)
        text = "\n".join(page.get_text() for page in pdf)
        self.assertLess(text.index("EXEMPLO-262"), text.index("EXEMPLO-261"))
        self.assertLess(text.index("EXEMPLO-261"), text.index("EXEMPLO-260"))

    def test_positioned_cards_are_explicitly_pending_without_added_hours(self):
        doc = example_plan()
        before = summary(doc)["hours"]
        doc["posicionamentos"] = [{"ot": "RES:EXEMPLO-260", "executante": "BR:TEST1", "dia": "2026-10-29"}]
        self.assertEqual(summary(doc)["hours"], before)
        pdf = self.parse(doc)
        text = "\n".join(page.get_text() for page in pdf)
        self.assertNotIn("OTs posicionadas no rascunho", text)

    def test_pdf_summarizes_backlog_with_status_and_pm_type_charts(self):
        doc = example_plan()
        doc["requisitos"]["RES:EXEMPLO-260"]["duracao"] = 2
        doc["ordens"].extend([
            {"siteid": "RES", "wonum": "BACKLOG-PM", "dados": {
                "description": "PM1 - backlog", "worktype": "I"}},
            {"siteid": "RES", "wonum": "BACKLOG-COR", "dados": {
                "description": "Falha hidráulica", "worktype": "E", "targcompdate": "2026-10-28"}},
            {"siteid": "RES", "wonum": "BACKLOG-COR-2", "dados": {
                "description": "Falha elétrica", "worktype": "E", "status": "APPR"}},
        ])
        doc["requisitos"].update({
            "RES:BACKLOG-PM": {"duracao": 2, "observacao": "Não listar"},
            "RES:BACKLOG-COR": {"duracao": None, "observacao": "Não listar"},
            "RES:BACKLOG-COR-2": {"duracao": None, "observacao": "Não listar"},
        })
        corrective_orders = [order for order in doc["ordens"] if order["dados"].get("worktype") == "E"]
        for order, status in zip(corrective_orders, ("WPREP", "INPROG", "WSCH", "COMP", "WPREP", "WPREP")):
            order["status"] = status

        data = summary(doc)
        self.assertEqual([len(data["groups"][status]) for status in
                          ("Programadas", "Parciais", "Não alocadas")], [24, 1, 3])
        self.assertEqual(data["groups_by_type"]["PM1"], {
            "Programadas": 9, "Parciais": 1, "Não alocadas": 1,
        })
        self.assertEqual(data["groups_by_type"]["PM2"]["Programadas"], 5)
        self.assertEqual(data["corrective_by_status"], {
            "APPR": 1, "WPREP": 1,
        })
        self.assertEqual(len(data["unprogrammed_corrective"]), 2)

        pdf = self.parse(doc)
        text = "\n".join(page.get_text() for page in pdf)
        self.assertIn("BACKLOG · OTs TIPO E NÃO ALOCADAS POR STATUS", text)
        self.assertNotIn("OTs TIPO E NÃO PROGRAMADAS", text)
        self.assertNotIn("BACKLOG-COR", text)
        self.assertNotIn("BACKLOG-COR-2", text)
        self.assertIn("APPR", text)
        self.assertNotIn("PARETO DE OTs POR STATUS", text)
        self.assertNotIn("Acumulado", text)
        self.assertIn("WPREP", text)
        self.assertIn("PM · QUANTIDADE POR TIPO E STATUS", text)
        self.assertNotIn("BACKLOG-PM", text)
        self.assertNotIn("PM · S", text)
        self.assertNotIn("COR · E", text)

    def test_draft_conflicts_are_red_and_explicit_in_pdf(self):
        doc = example_plan()
        doc["blocos"][1]["executantes"] = doc["blocos"][0]["executantes"]
        doc["blocos"][1]["inicio"] = 0
        doc["blocos"][1]["horas"] = 40
        self.assertGreaterEqual(len(summary(doc)["conflicts"]), 2)
        pdf = self.parse(doc)
        text = "\n".join(page.get_text() for page in pdf)
        self.assertIn("PRÉVIA COM SOBRECARGA SEMANAL", text)
        self.assertNotIn("Excesso", text)
        self.assertTrue(any("PRÉVIA COM SOBRECARGA SEMANAL" in span["text"] and span["color"] != 0
                            for page in pdf for block in page.get_text("dict")["blocks"] if "lines" in block
                            for line in block["lines"] for span in line["spans"]))

    def test_a4_portrait_content_and_repeated_header_and_footer(self):
        pdf = self.parse(example_plan())
        text = "\n".join(page.get_text() for page in pdf)
        for expected in ["PLANEJAMENTO SEMANAL", "26/10/2026", "30/10/2026", "EXEMPLO-260",
                         "EXEMPLO-304", "Executante exemplo", "RESUMO DA SEMANA", "CARGA DIÁRIA",
                         "COBERTURA DA CARTEIRA", "HH comprometidos", "sem hora de início", "BMA: envio pendente"]:
            self.assertIn(expected, text)
        for page in pdf:
            self.assertLess(page.rect.width, page.rect.height)
            self.assertIn("PLANEJAMENTO SEMANAL", page.get_text())
            self.assertIn("NFE", page.get_text())
            self.assertIn("PERFORMANCE SEMPRE", page.get_text())
            self.assertGreater(len(page.get_images()), 0)
            self.assertNotIn("Faixa (h)", page.get_text())
            if "Recurso / equipe" in page.get_text():
                self.assertIn("TOTAL DO DIA", page.get_text())
            self.assertIn("Centro PCM", page.get_text())
            for x0, y0, x1, y1, *_ in page.get_text("blocks"):
                self.assertGreaterEqual(x0, 0)
                self.assertLessEqual(x1, page.rect.width + 1)
                self.assertGreaterEqual(y0, 0)
                self.assertLessEqual(y1, page.rect.height + 1)

    def test_metric_values_and_labels_share_a_consistent_icon_text_grid(self):
        page = self.parse(example_plan())[0]
        labels = ["OTs com alocação", "HH comprometidos", "Recursos alocados",
                  "Locais informados", "Ocupação da equipe"]
        expected_lefts = [24 + index * (page.rect.width - 48) / 5 + 39 for index in range(5)]
        for label, left in zip(labels, expected_lefts):
            found = page.search_for(label)
            self.assertTrue(found, label)
            self.assertAlmostEqual(found[0].x0, left, delta=1)
        metric_spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block
                        for line in block["lines"] for span in line["spans"]
                        if abs(span["size"] - 13) < .1 and span["bbox"][1] < 150]
        self.assertEqual(len(metric_spans), 5)
        for span, left in zip(metric_spans, expected_lefts):
            self.assertAlmostEqual(span["bbox"][0], left, delta=1)

    def test_large_daily_schedule_long_names_and_escaped_text_paginate_without_loss(self):
        doc = example_plan()
        original_order = doc["ordens"][0]
        original_block = doc["blocos"][0]
        doc["ordens"], doc["blocos"], doc["requisitos"] = [], [], {}
        for index in range(100):
            order = copy.deepcopy(original_order)
            order["wonum"] = f"LONG-{index:03}"
            order["dados"]["description"] = "Inspeção <equipamento> & verificação " * 5
            key = f"RES:{order['wonum']}"
            doc["ordens"].append(order)
            doc["requisitos"][key] = {"duracao": .05, "observacao": ""}
            doc["blocos"].append({**original_block, "id": str(index), "ot": key,
                                  "inicio": index * .05, "horas": .05})
        doc["pessoas"][0]["nome"] = "Executante de nome longo " * 5
        pdf = self.parse(doc)
        text = "\n".join(page.get_text() for page in pdf)
        self.assertGreater(len(pdf), 2)
        for index in range(100):
            self.assertIn(f"LONG-{index:03}", text)
        self.assertIn("Inspeção <equipamento> &", text)
        self.assertIn("CARGA DIÁRIA", text)


if __name__ == "__main__":
    unittest.main()
