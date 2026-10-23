import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from math import isfinite
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ExecutantePlanejado(BaseModel):
    orgid: str = Field(min_length=1)
    matricula: str = Field(min_length=1)
    funcao: str = Field(min_length=1)
    jornada: Literal["adm", "08-16", "16-00", "00-08", "equipe"]
    equipe: int | None = Field(default=None, ge=1, le=4)
    ajustes_datas: dict[date, float] = Field(default_factory=dict)
    inicio_ciclo: date | None = None
    ajuste_horas: float = Field(default=0, allow_inf_nan=False)
    ausencias: list[date] = Field(default_factory=list)
    capacidade: Literal["escala", "dias_6h", "dias_8h"] = "escala"
    dias_disponiveis: list[date] | None = None

    @model_validator(mode="after")
    def validar_ciclo(self):
        if self.jornada == "equipe" and self.equipe is None:
            raise ValueError("Selecione a equipe do calendário.")
        if any(not isfinite(hours) or hours < 0 or hours > 24 for hours in self.ajustes_datas.values()):
            raise ValueError("As horas manuais por data devem estar entre 0 e 24.")
        if self.capacidade in ("dias_6h", "dias_8h"):
            if self.dias_disponiveis is None:
                raise ValueError("Informe os dias disponíveis do executante.")
            if self.ajuste_horas != 0 or self.ajustes_datas or self.ausencias:
                raise ValueError("Informe somente os dias disponíveis, sem ajustes ou ausências adicionais.")
        if self.capacidade == "escala" and self.jornada not in ("adm", "equipe") and self.inicio_ciclo is None:
            raise ValueError("Informe o primeiro dia de trabalho do ciclo 6x2.")
        return self


@lru_cache(maxsize=1)
def calendario_turnos() -> dict:
    path = Path(__file__).resolve().parents[2] / "database" / "catalogos" / "turnos-2026.json"
    return json.loads(path.read_text(encoding="utf-8"))


def horas_calendario(inicio: date, fim: date, member: ExecutantePlanejado) -> tuple[int, float]:
    calendar = calendario_turnos()["dias"]
    days = 0
    hours = 0.0
    current = inicio
    while current <= fim:
        row = calendar.get(current.isoformat(), {}).get(str(member.equipe))
        if row is None:
            raise ValueError("O calendário oficial das equipes cobre somente 2026.")
        if current in member.ausencias:
            value = 0
        elif row["marcacao"]:
            if current not in member.ajustes_datas:
                raise ValueError(f"Informe as horas de {current.isoformat()} ({row['marcacao']}).")
            value = member.ajustes_datas[current]
        else:
            value = 0 if row["turno"] == "F" else 8
        hours += value
        days += value > 0
        current += timedelta(days=1)
    if any(key < inicio or key > fim for key in member.ajustes_datas):
        raise ValueError("Há ajustes por data fora do período. Revise as datas especiais.")
    return days, hours


class PlanejamentoEquipe(BaseModel):
    setores: list[str] = Field(min_length=1, max_length=28)
    inicio: date
    fim: date
    executantes: list[ExecutantePlanejado]
    planejador: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def validar_periodo(self):
        if self.fim < self.inicio:
            raise ValueError("O fim do planejamento deve ser igual ou posterior ao início.")
        keys = [(p.orgid, p.matricula) for p in self.executantes]
        if len(keys) != len(set(keys)):
            raise ValueError("Um executante não pode ser contado mais de uma vez.")
        if any(not setor or not all(c.isalnum() or c == "-" for c in setor) for setor in self.setores):
            raise ValueError("Setor de planejamento inválido.")
        for member in self.executantes:
            if member.dias_disponiveis is not None:
                if len(member.dias_disponiveis) != len(set(member.dias_disponiveis)):
                    raise ValueError("Há dias disponíveis duplicados.")
                if any(day < self.inicio or day > self.fim for day in member.dias_disponiveis):
                    raise ValueError("Há dias disponíveis fora do período de planejamento.")
            if len(member.ausencias) != len(set(member.ausencias)):
                raise ValueError("Há dias de ausência duplicados.")
            if any(day < self.inicio or day > self.fim for day in member.ausencias):
                raise ValueError("Há ausências fora do período de planejamento.")
        return self


def dias_trabalho(inicio: date, fim: date, jornada: str, ciclo: date | None) -> int:
    days = (fim - inicio).days + 1
    if days <= 0:
        raise ValueError("Período de planejamento inválido.")
    weeks, remainder = divmod(days, 7 if jornada == "adm" else 8)
    if jornada == "adm":
        return weeks * 5 + sum((inicio.weekday() + i) % 7 < 5 for i in range(remainder))
    if ciclo is None:
        raise ValueError("Informe o início do ciclo 6x2.")
    phase = (inicio - ciclo).days % 8
    return weeks * 6 + sum((phase + i) % 8 < 6 for i in range(remainder))


def calcular_equipe(plan: PlanejamentoEquipe, labor: dict) -> dict:
    if labor.get("verificacao_nf", {}).get("necessaria") and not labor["verificacao_nf"]["verificada"]:
        raise ValueError("Atualize a mão de obra no modal e confira os vínculos NF no SharePoint.")
    sectors = {sector.upper() for sector in plan.setores}
    people = {
        (p["orgid"], p["matricula"]): p for p in labor["profissionais"]
        if p.get("setor", "").upper() in sectors or p.get("local_trabalho", "").upper() == "NFE"
        or ("RES-TC-NF" in sectors and labor.get("verificacao_nf", {}).get("verificada") and p.get("nf_ativo") is True)
    }
    summary: dict[tuple[str, str], dict] = {}
    details = []
    for member in plan.executantes:
        person = people.get((member.orgid, member.matricula))
        if person is None:
            raise ValueError(
                f"Executante {member.matricula} não consta no cadastro ativo dos setores selecionados."
            )
        craft = next((c for c in person["especialidades"] if c["codigo"] == member.funcao), None)
        if craft is None:
            raise ValueError(f"Função não cadastrada para o executante {member.matricula}.")
        if member.capacidade in ("dias_6h", "dias_8h"):
            days = len(member.dias_disponiveis)
            base = days * (8 if member.capacidade == "dias_8h" else 6)
        elif member.jornada == "equipe":
            days, base = horas_calendario(plan.inicio, plan.fim, member)
        else:
            days = dias_trabalho(plan.inicio, plan.fim, member.jornada, member.inicio_ciclo)
            days -= sum(dias_trabalho(day, day, member.jornada, member.inicio_ciclo) for day in member.ausencias)
            base = days * (6 if member.jornada == "adm" else 8)
        hours = round(base + member.ajuste_horas, 2)
        if not isfinite(hours) or hours < 0:
            raise ValueError(f"Ajuste de horas inválido para {member.matricula}: total negativo.")
        key = (member.orgid, member.funcao)
        if key not in summary:
            summary[key] = {
                "orgid": member.orgid, "codigo": member.funcao,
                "descricao": craft["descricao"], "quantidade": 0, "horas": 0,
            }
        summary[key]["quantidade"] += 1
        summary[key]["horas"] = round(summary[key]["horas"] + hours, 2)
        details.append({"orgid": member.orgid, "matricula": member.matricula,
                        "dias": days, "horas_base": base, "horas": hours})
    return {"funcoes": list(summary.values()), "executantes": details,
            "total_horas": round(sum(d["horas"] for d in details), 2)}
