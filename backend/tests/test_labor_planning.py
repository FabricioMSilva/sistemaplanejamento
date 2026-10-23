import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

import backend.models.database as database
from backend.services.labor_planning import PlanejamentoEquipe, calcular_equipe, dias_trabalho


def executante(matricula="TEST1", **values):
    return {
        "orgid": "BR", "matricula": matricula, "funcao": "210",
        "jornada": "adm", "inicio_ciclo": None, "ajuste_horas": 0, **values,
    }


def plano(**values):
    return PlanejamentoEquipe.model_validate({
        "setores": ["RES-TC-NF"], "inicio": "2026-11-01", "fim": "2026-11-08",
        "executantes": [executante()], **values,
    })


def cadastro():
    return {"profissionais": [
        {"orgid": "BR", "matricula": code, "setor": "RES-TC-NF",
         "local_trabalho": "TC", "especialidades": [
            {"codigo": "210", "descricao": "Eletricista"},
            {"codigo": "300", "descricao": "Eletromecânico"},
        ]} for code in ("TEST1", "TEST2")
    ]}


class LaborPlanningTests(unittest.TestCase):
    def test_admin_uses_weekdays_six_hours_and_inclusive_period(self):
        result = calcular_equipe(plano(), cadastro())
        self.assertEqual(result["total_horas"], 30)
        self.assertEqual(result["executantes"][0]["dias"], 5)
        self.assertEqual(calcular_equipe(plano(inicio="2026-11-02", fim="2026-11-02"), cadastro())["total_horas"], 6)
        self.assertEqual(calcular_equipe(plano(inicio="2026-11-01", fim="2026-11-01"), cadastro())["total_horas"], 0)

    def test_all_shifts_include_weekends_with_six_work_days_and_two_rest_days(self):
        for shift in ("08-16", "16-00", "00-08"):
            result = calcular_equipe(plano(executantes=[
                executante(jornada=shift, inicio_ciclo="2026-11-01"),
            ]), cadastro())
            self.assertEqual(result["total_horas"], 48)
            rest = calcular_equipe(plano(inicio="2026-11-07", fim="2026-11-08", executantes=[
                executante(jornada=shift, inicio_ciclo="2026-11-01"),
            ]), cadastro())
            self.assertEqual(rest["total_horas"], 0)

    def test_calendar_formula_matches_day_by_day_for_all_phases(self):
        cycle = date(2026, 11, 1)
        for offset in range(-10, 11):
            for length in (1, 2, 6, 7, 8, 9, 31, 366):
                start = cycle + timedelta(days=offset)
                end = start + timedelta(days=length - 1)
                days = [start + timedelta(days=i) for i in range(length)]
                self.assertEqual(dias_trabalho(start, end, "adm", None), sum(d.weekday() < 5 for d in days))
                self.assertEqual(
                    dias_trabalho(start, end, "08-16", cycle),
                    sum((d - cycle).days % 8 < 6 for d in days),
                )

    def test_selected_function_counts_each_person_only_once(self):
        plan = plano(executantes=[executante(), executante("TEST2", funcao="300", ajuste_horas=-6)])
        result = calcular_equipe(plan, cadastro())
        self.assertEqual(result["total_horas"], 54)
        self.assertEqual([r["horas"] for r in result["funcoes"]], [30, 24])
        combined = calcular_equipe(plano(executantes=[executante(), executante("TEST2")]), cadastro())
        self.assertEqual(combined["funcoes"][0]["quantidade"], 2)
        self.assertEqual(combined["funcoes"][0]["horas"], 60)

    def test_invalid_dates_duplicates_journeys_and_missing_reference_rejected(self):
        for change in (
            {"fim": "2026-10-01"}, {"inicio": "2026-02-30"},
            {"executantes": [executante(), executante()]},
            {"executantes": [executante(jornada="08-16")]},
            {"executantes": [executante(jornada="invalid")]},
            {"executantes": [executante(ajuste_horas=float("nan"))]},
            {"setores": ["invalid|sector"]},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                plano(**change)

    def test_inactive_people_unknown_function_and_negative_total_rejected(self):
        for member in (
            executante("INACTIVE"), executante(funcao="UNKNOWN"), executante(ajuste_horas=-31),
        ):
            with self.subTest(member=member), self.assertRaises(ValueError):
                calcular_equipe(plano(executantes=[member]), cadastro())

    def test_empty_team_is_valid_zero_capacity(self):
        self.assertEqual(calcular_equipe(plano(executantes=[]), cadastro())["total_horas"], 0)

    def test_official_team_calendar_rotates_shifts_and_requires_exception_hours(self):
        from backend.services.labor_planning import calendario_turnos
        calendar = calendario_turnos()["dias"]
        self.assertEqual(len(calendar), 365)
        self.assertEqual(calendar["2026-11-01"]["1"]["turno"], "F")
        self.assertEqual(calendar["2026-11-03"]["1"]["turno"], "B")
        self.assertEqual(calendar["2026-11-11"]["1"]["turno"], "A")
        self.assertEqual(calendar["2026-11-19"]["1"]["turno"], "C")
        self.assertEqual(calendar["2026-12-25"]["1"]["marcacao"], "PARADA")
        team = executante(jornada="equipe", equipe=1)
        with self.assertRaisesRegex(ValueError, "2026-11-03"):
            calcular_equipe(plano(executantes=[team]), cadastro())
        team["ajustes_datas"] = {"2026-11-03": 6, "2026-11-05": 7}
        self.assertEqual(calcular_equipe(plano(executantes=[team]), cadastro())["total_horas"], 45)
        with self.assertRaisesRegex(ValueError, "somente 2026"):
            calcular_equipe(plano(inicio="2027-01-01", fim="2027-01-01", executantes=[team]), cadastro())
        with self.assertRaises(ValidationError):
            plano(executantes=[executante(jornada="equipe", equipe=5)])

    def test_active_person_from_another_sector_is_rejected(self):
        labor = cadastro()
        labor["profissionais"][0]["setor"] = "RES-TC-NC"
        with self.assertRaisesRegex(ValueError, "setores selecionados"):
            calcular_equipe(plano(), labor)
        plan = plano(setores=["RES-TC-NF", "res-tc-nc"])
        self.assertEqual(calcular_equipe(plan, labor)["total_horas"], 30)

    def test_active_person_from_nf_workplace_is_included(self):
        labor = cadastro()
        labor["profissionais"][0]["setor"] = "RES-MATRM-NR2"
        labor["profissionais"][0]["local_trabalho"] = "NFE"
        result = calcular_equipe(plano(), labor)
        self.assertEqual(result["total_horas"], 30)
        self.assertEqual(calcular_equipe(plano(executantes=[
            executante("TEST1"), executante("TEST2"),
        ]), labor)["total_horas"], 60)
        labor["profissionais"][0]["local_trabalho"] = "NFE-AREA"
        with self.assertRaisesRegex(ValueError, "setores selecionados"):
            calcular_equipe(plano(), labor)

    def test_saved_team_restores_by_sector_and_survives_catalog_refresh(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            database, "DB_PATH", Path(directory) / "test.db",
        ):
            database.init_db()
            plan = plano(setores=["RES-TC-NF", "RES-TC-NC"]).model_dump(mode="json")
            self.assertIsNone(database.obter_equipe(["RES-TC-NF"]))
            database.salvar_equipe(plan)
            database.init_db()
            self.assertEqual(database.obter_equipe(["RES-TC-NC", "res-tc-nf"]), plan)
            plan["fim"] = "2026-11-09"
            database.salvar_equipe(plan)
            self.assertEqual(database.obter_equipe(["RES-TC-NF", "RES-TC-NC"])["fim"], "2026-11-09")
            self.assertIsNone(database.obter_equipe(["RES-TC-NF"]))


if __name__ == "__main__":
    unittest.main()
