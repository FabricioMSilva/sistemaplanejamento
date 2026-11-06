"""Prepare Quick Report payloads from the Ronda rules and SharePoint items."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from models.workforce_identity import normalizar
from utils.runtime_paths import resource_root


def load_ronda_rules(path: Path | None = None) -> dict[str, Any]:
    rules_path = path or resource_root() / "database" / "catalogos" / "regras_rondas.json"
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Não foi possível ler regras_rondas.json: {exc}") from exc
    if not isinstance(rules, dict) or not isinstance(rules.get("turnos"), dict) or not isinstance(rules.get("rondas"), dict):
        raise ValueError("regras_rondas.json está inválido: turnos e rondas são obrigatórios.")
    return rules


def _resolve_round(name: str, rounds: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    normalized = normalizar(name)
    matches = []
    for key, config in rounds.items():
        names = [key, config.get("nome", ""), *(config.get("aliases") or [])]
        if any(normalizar(str(candidate)) == normalized for candidate in names):
            matches.append((key, config))
    if len(matches) != 1:
        raise ValueError(f"Ronda '{name}' não corresponde a uma regra única em regras_rondas.json.")
    return matches[0]


def _parse_date(value: Any, item_id: Any) -> date:
    raw = str(value or "").strip()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValueError(f"Item de Ronda {item_id}: data inválida ou ausente.") from exc


def _resolve_shift(value: Any, shifts: dict[str, Any], config: dict[str, Any], item_id: Any):
    normalized = normalizar(str(value or ""))
    tokens = set(normalized.split())
    allowed = config.get("turnos") or []
    matches = [code for code, window in shifts.items() if code in tokens and code in allowed]
    if len(matches) != 1:
        raise ValueError(f"Item de Ronda {item_id}: turno inválido ou não permitido ({value}).")
    shift = matches[0]
    window = shifts[shift]
    if not window.get("inicio") or not window.get("fim"):
        raise ValueError(f"Turno {shift} está sem horários no JSON de regras.")
    return shift, window


def _executants(item: dict[str, Any]) -> list[dict[str, str]]:
    people = item.get("executantes")
    if not isinstance(people, list) or not people:
        raise ValueError(f"Item de Ronda {item.get('id')}: executante ausente.")
    result = []
    for person in people:
        name = " ".join(str(person.get("nome") or "").split()) if isinstance(person, dict) else ""
        registration = " ".join(str(person.get("matricula") or "").split()).upper() if isinstance(person, dict) else ""
        if not name or not registration:
            raise ValueError(f"Item de Ronda {item.get('id')}: executante sem nome ou matrícula.")
        result.append({"nome": name, "matricula": registration})
    return result


def prepare_ronda_orders(items: list[dict[str, Any]], rules: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(items, list) or not items:
        raise ValueError("Não há itens pendentes de Ronda para criar no BMA.")
    rules = rules or load_ronda_rules()
    defaults = rules.get("maximo") or {}
    shifts = rules["turnos"]
    rounds = rules["rondas"]
    groups: dict[tuple, list[dict[str, Any]]] = {}

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("A lista de Ronda contém um item inválido.")
        item_id = item.get("id", "?")
        round_key, config = _resolve_round(str(item.get("ronda") or ""), rounds)
        execution_date = _parse_date(item.get("data"), item_id)
        shift, window = _resolve_shift(item.get("turno"), shifts, config, item_id)
        team = " ".join(str(item.get("equipe") or "").split())
        if not team:
            raise ValueError(f"Item de Ronda {item_id}: equipe ausente.")
        people = _executants(item)
        identities = tuple(sorted((person["matricula"], normalizar(person["nome"])) for person in people))
        group_key = (round_key, execution_date.isoformat(), shift, normalizar(team), identities)
        groups.setdefault(group_key, []).append({
            "id": item_id, "data": execution_date, "turno": shift, "janela": window,
            "equipe": team, "executantes": people, "config": config, "round_key": round_key,
        })

    orders = []
    waiting = []
    for rows in groups.values():
        first = rows[0]
        config = first["config"]
        required_runs = int(config.get("enviar_apos_execucao", 1))
        executions_per_shift = int(config.get("execucoes_por_turno", 1))
        if required_runs < 1 or executions_per_shift < required_runs:
            raise ValueError(f"Regra de envio inválida para {config.get('nome', first['round_key'])}.")
        for offset in range(0, len(rows), required_runs):
            group = rows[offset:offset + required_runs]
            if len(group) < required_runs:
                waiting.append({
                    "ronda": config.get("nome", first["round_key"]),
                    "data": first["data"].isoformat(), "turno": first["turno"],
                    "executadas": len(group), "necessarias": required_runs,
                    "itens": [row["id"] for row in group],
                })
                continue
            minutes = int(config.get("duracao_minutos", 0)) * required_runs
            if minutes <= 0:
                raise ValueError(f"Duração inválida para {config.get('nome', first['round_key'])}.")
            start = datetime.combine(first["data"], datetime.strptime(first["janela"]["inicio"], "%H:%M").time())
            finish = start + timedelta(minutes=minutes)
            people = first["executantes"]
            values = {
                "executante": ", ".join(person["nome"] for person in people),
                "matricula": ", ".join(person["matricula"] for person in people),
                "equipe": first["equipe"], "data": first["data"].strftime("%d/%m/%Y"),
                "turno": first["turno"], "inicio": start.strftime("%H:%M"), "fim": finish.strftime("%H:%M"),
            }
            template = config.get("descricao_longa_template")
            if not isinstance(template, list) or not template:
                raise ValueError(f"Template de descrição ausente para {config.get('nome', first['round_key'])}.")
            try:
                long_description = "\n".join(str(line).format_map(values) for line in template)
            except KeyError as exc:
                raise ValueError(f"Placeholder {exc.args[0]} ausente em regras_rondas.json.") from exc
            orders.append({
                "sharepoint_ids": [row["id"] for row in group],
                "description": config["nome"],
                "description_longdescription": long_description,
                "equipment": str(defaults.get("equipamento") or ""),
                "location": str(defaults.get("local") or ""),
                "refers_to": str(defaults.get("refere_se_a") or ""),
                "equipment_status": str(defaults.get("status_equipamento") or ""),
                "work_type": str(defaults.get("tipo_trabalho") or ""),
                "start_date": start.strftime("%d/%m/%Y"), "start_time": start.strftime("%H:%M"),
                "end_date": finish.strftime("%d/%m/%Y"), "end_time": finish.strftime("%H:%M"),
                "hours": minutes / 60,
                "labor": [{"laborcode": person["matricula"]} for person in people],
                "ronda": config["nome"],
            })
    return {"orders": orders, "waiting": waiting}
