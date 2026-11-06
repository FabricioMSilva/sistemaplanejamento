from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from services.ronda_analytics import ronda_activity_charts


class RondaAnalyticsTests(unittest.TestCase):
    def test_daily_counts_use_completed_rounds_and_calendar_assigns_missing_work_by_team(self):
        rules = {
            "turnos": {"A": {}, "B": {}, "C": {}},
            "rondas": {
                "analise_quimica": {"nome": "Analise quimica", "aliases": ["ANALISE QUIMICA NF"],
                                     "turnos": ["A", "B", "C"], "execucoes_por_turno": 1},
                "equipamentos": {"nome": "Ronda dos equipamentos", "aliases": ["RONDA EQUIPAMENTOS NF"],
                                 "turnos": ["A", "B", "C"], "execucoes_por_turno": 1},
                "medidores": {"nome": "Ronda dos medidores", "aliases": ["RONDA MEDIDORES NFE"],
                              "turnos": ["A", "C"], "execucoes_por_turno": 1},
            },
        }
        records = [
            {"id": 1, "status": "CONCLUIDO", "ronda": "ANALISE QUIMICA NF", "data": "2026-11-04",
             "turno": "A", "equipe": "NFE"},
            {"id": 2, "status": "CONCLUIDO", "ronda": "RONDA EQUIPAMENTOS NF", "data": "2026-11-04",
             "turno": "B", "equipe": "NFE"},
            {"id": 3, "status": "CONCLUIDO", "ronda": "RONDA MEDIDORES NFE", "data": "2026-11-04",
             "turno": "A", "equipe": "NFE"},
            {"id": 4, "status": "PENDENTE", "ronda": "ANALISE QUIMICA NF", "data": "2026-11-04",
             "turno": "C", "equipe": "NFE"},
            {"id": 5, "status": "CONCLUIDO", "ronda": "ANALISE QUIMICA NF", "data": "2026-10-05",
             "turno": "A", "equipe": "NFE"},
        ]
        calendar = {"2026-11-04": {
            "1": {"turno": "A", "marcacao": None},
            "2": {"turno": "B", "marcacao": None},
            "3": {"turno": "C", "marcacao": None},
            "4": {"turno": "F", "marcacao": None},
        }}
        with (
            patch("services.ronda_analytics.load_ronda_rules", return_value=rules),
            patch("services.ronda_analytics._read_turn_schedule", return_value=calendar),
            patch("services.ronda_analytics.listar_itens_ronda_sharepoint", return_value=records),
        ):
            result = ronda_activity_charts(today=date(2026, 11, 4))

        today = next(row for row in result["diario"] if row["date"] == "2026-11-04")
        self.assertEqual((today["analises"], today["equipamentos"], today["medidores"]), (1, 1, 1))
        self.assertEqual((today["analises_meta"], today["equipamentos_meta"], today["medidores_meta"]), (3, 3, 2))
        weekday = next(row for row in result["faltas_por_dia_semana"] if row["weekday"] == "Qua")
        self.assertEqual((weekday["equipe_1"], weekday["equipe_2"], weekday["equipe_3"], weekday["equipe_4"]), (1, 1, 3, 0))
        self.assertEqual(len(result["faltas_detalhadas"]), 5)


if __name__ == "__main__":
    unittest.main()
