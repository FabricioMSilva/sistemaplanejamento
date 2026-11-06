from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from models.database import listar_itens_ronda_sharepoint
from models.workforce_identity import normalizar
from utils.runtime_paths import resource_root
from .ronda_work_orders import load_ronda_rules

WEEKDAYS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
MODALITY_KEYS = {
    "analise_quimica": ("analises", "Análises químicas"),
    "equipamentos": ("equipamentos", "Ronda de equipamentos"),
    "medidores": ("medidores", "Ronda dos medidores"),
}
COMPLETED_STATUSES = {"CONCLUIDO", "COMP", "COMPLETED", "FEITA", "FEITO", "REALIZADA", "REALIZADO"}


def _read_turn_schedule() -> dict[str, Any]:
    path = resource_root() / "database" / "catalogos" / "turnos-2026.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Não foi possível ler {path.name}: {exc}") from exc
    days = payload.get("dias")
    if not isinstance(days, dict):
        raise ValueError(f"{path.name} não contém o calendário de equipes.")
    return days


def _date_from_value(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _round_mapping(rules: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    aliases: dict[str, str] = {}
    modalities = []
    for key, (series_key, label) in MODALITY_KEYS.items():
        config = rules.get("rondas", {}).get(key)
        if not isinstance(config, dict):
            continue
        modalities.append({
            "key": series_key,
            "label": label,
            "allowed_shifts": {str(value).strip().upper() for value in config.get("turnos", [])},
            "per_shift": max(1, int(config.get("execucoes_por_turno", 1))),
        })
        for candidate in (key, config.get("nome", ""), *(config.get("aliases") or [])):
            normalized = normalizar(str(candidate or ""))
            if normalized:
                aliases[normalized] = series_key
    return aliases, modalities


def ronda_activity_charts(*, today: date | None = None) -> dict[str, Any]:
    end_day = today or date.today()
    start_day = end_day - timedelta(days=29)
    days = [start_day + timedelta(days=offset) for offset in range(30)]
    date_keys = [day.isoformat() for day in days]
    rules = load_ronda_rules()
    round_aliases, modalities = _round_mapping(rules)
    schedule = _read_turn_schedule()
    stored_items = listar_itens_ronda_sharepoint()

    completed_by_day: Counter[tuple[str, str]] = Counter()
    completed_by_team: Counter[tuple[str, str, str]] = Counter()
    for item in stored_items:
        is_completed = (
            normalizar(str(item.get("status") or "")).upper() in COMPLETED_STATUSES
            or item.get("criacao_status") == "criada"
        )
        if not is_completed:
            continue
        item_day = _date_from_value(item.get("data"))
        if item_day is None or item_day < start_day or item_day > end_day:
            continue
        modality = round_aliases.get(normalizar(str(item.get("ronda") or "")))
        if modality is None:
            continue
        day_key = item_day.isoformat()
        completed_by_day[(day_key, modality)] += 1

        shift = str(item.get("turno") or "").strip().upper()
        day_schedule = schedule.get(day_key, {})
        team_ids = [
            str(team_id)
            for team_id, entry in day_schedule.items()
            if isinstance(entry, dict)
            and str(entry.get("turno") or "").strip().upper() == shift
            and shift in {"A", "B", "C"}
        ]
        if len(team_ids) == 1:
            completed_by_team[(day_key, team_ids[0], modality)] += 1

    series = []
    for day, day_key in zip(days, date_keys):
        day_schedule = schedule.get(day_key, {})
        active_shifts = [
            str(entry.get("turno") or "").strip().upper()
            for entry in day_schedule.values()
            if isinstance(entry, dict)
        ] if isinstance(day_schedule, dict) else []
        row: dict[str, Any] = {
            "date": day_key,
            "label": f"{day.day:02d}/{day.month:02d}",
            "weekday": WEEKDAYS[day.weekday()],
        }
        for modality in modalities:
            key = modality["key"]
            row[key] = completed_by_day[(day_key, key)]
            row[f"{key}_meta"] = sum(
                1 for shift in active_shifts if shift in modality["allowed_shifts"]
            ) * modality["per_shift"]
        series.append(row)

    team_ids = sorted({str(team) for day in schedule.values() if isinstance(day, dict) for team in day})
    missing_by_weekday: dict[str, Counter[str]] = {
        team: Counter({weekday: 0 for weekday in WEEKDAYS}) for team in team_ids
    }
    missing_details = []
    for day, day_key in zip(days, date_keys):
        day_schedule = schedule.get(day_key, {})
        if not isinstance(day_schedule, dict):
            continue
        for team_id, entry in day_schedule.items():
            if not isinstance(entry, dict):
                continue
            shift = str(entry.get("turno") or "").strip().upper()
            if shift not in {"A", "B", "C"}:
                continue
            for modality in modalities:
                if shift not in modality["allowed_shifts"]:
                    continue
                expected = modality["per_shift"]
                actual = completed_by_team[(day_key, str(team_id), modality["key"])]
                missing = max(0, expected - actual)
                if missing:
                    missing_by_weekday.setdefault(str(team_id), Counter()) [WEEKDAYS[day.weekday()]] += missing
                    missing_details.append({
                        "date": day_key,
                        "weekday": WEEKDAYS[day.weekday()],
                        "team": str(team_id),
                        "turno": shift,
                        "modalidade": modality["label"],
                        "faltantes": missing,
                    })

    weekday_series = []
    for weekday in WEEKDAYS:
        row = {"weekday": weekday}
        for team_id in team_ids:
            row[f"equipe_{team_id}"] = missing_by_weekday.get(team_id, {}).get(weekday, 0)
        weekday_series.append(row)

    return {
        "inicio": start_day.isoformat(),
        "fim": end_day.isoformat(),
        "modalidades": [
            {"key": item["key"], "label": item["label"],
             "meta_diaria": len(item["allowed_shifts"]) * item["per_shift"]}
            for item in modalities
        ],
        "diario": series,
        "equipes": team_ids,
        "faltas_por_dia_semana": weekday_series,
        "faltas_detalhadas": missing_details,
    }
