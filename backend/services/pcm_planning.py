import copy
import json
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from models.database import get_connection, listar_mao_de_obra, listar_ordens_trabalho, obter_equipe
from services.labor_planning import PlanejamentoEquipe, calcular_equipe
from services.pcm_capacity import week_start, weekly_totals

TERMINAL = {"CAN", "CANCELADA", "CLOSE", "COMP", "HISTEDIT"}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirement(Input):
    duracao: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    pessoas: int | None = Field(default=None, ge=1, le=100)
    orgid: str = Field(default="", max_length=100)
    funcao: str = Field(default="", max_length=100)
    todas_especialidades: bool = False
    selecionada: bool = False
    na_nuvem: bool = False
    prioridade: int = Field(default=3, ge=1, le=5)
    liberada: bool = False
    observacao: str = Field(default="", max_length=1000)


class Block(Input):
    id: str = Field(min_length=1, max_length=100)
    ot: str = Field(min_length=1, max_length=100)
    dia: date
    inicio: float = Field(default=0, ge=0, le=1000, allow_inf_nan=False)
    horas: float = Field(gt=0, le=1000, allow_inf_nan=False)
    executantes: list[str] = Field(min_length=1, max_length=100)


class Unavailable(Input):
    executante: str = Field(min_length=1, max_length=100)
    dia: date
    motivo: str = Field(min_length=1, max_length=500)


class Placement(Input):
    ot: str = Field(min_length=1, max_length=100)
    executante: str = Field(min_length=1, max_length=100)
    dia: date


class Overtime(Input):
    ot: str = Field(min_length=1, max_length=100)
    executante: str = Field(min_length=1, max_length=100)
    dia: date
    horas: float = Field(gt=0, le=1000, allow_inf_nan=False)


class PlanChange(Input):
    revisao: int = Field(ge=1)
    requisitos: dict[str, Requirement]
    blocos: list[Block] = Field(max_length=10000)
    indisponibilidades: list[Unavailable] = Field(default_factory=list, max_length=10000)
    motivo: str = Field(min_length=1, max_length=1000)
    confirmar: bool = False
    atualizar_especialidades: bool = False
    posicionamentos: list[Placement] = Field(default_factory=list, max_length=20000)
    horas_extras: list[Overtime] = Field(default_factory=list, max_length=20000)


class AddOrders(Input):
    revisao: int = Field(ge=1)
    ordens: list[str] = Field(min_length=1, max_length=500)


class RefreshPlanOrders(Input):
    revisao: int = Field(ge=1)


class PlanTeamChange(Input):
    revisao: int = Field(ge=1)
    equipe: PlanejamentoEquipe


class NewPlan(Input):
    setores: list[str] = Field(min_length=1, max_length=28)


class Suggestion(Input):
    modo: Literal["pm", "corretiva"]
    alteracoes: PlanChange
    ordens: list[str] | None = Field(default=None, max_length=20000)


class ExportOrders(Input):
    setores: list[str] = Field(min_length=1, max_length=28)
    inicio: date | None = None
    fim: date | None = None
    modo: Literal["pm", "corretiva"]
    ordens: list[str] = Field(max_length=20000)


class ConflictError(ValueError):
    pass


def text(order: dict, key: str) -> str:
    value = order.get("dados", {}).get(key, order.get(key))
    if isinstance(value, dict):
        value = value.get("value", value.get("_value", value.get("description")))
    return str(value) if value is not None else ""


def order_key(order: dict) -> str:
    return f"{order['siteid']}:{order['wonum']}"


def day_value(value: str) -> str | None:
    if not value:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.date().isoformat()
        return parsed.astimezone(timezone(timedelta(hours=-3))).date().isoformat()
    except ValueError:
        return None


def pm_constraint_before_end(order: dict, end: str) -> bool:
    not_before = day_value(text(order, "sneconstraint"))
    return bool(not_before and not_before < end)


def mode_for(order: dict) -> str | None:
    kind = text(order, "worktype").strip().upper()
    if kind == "E":
        return "corretiva"
    if kind in ("I", "S") and text(order, "description").strip().upper().startswith("PM"):
        return "pm"
    return None


def has_existing_planning_info(order: dict) -> bool:
    status = text(order, "planning_status").strip()
    if status:
        return status != "Não planejada"
    data = order.get("dados")
    lead_known = (isinstance(data, dict) and "lead" in data) or "lead" in order
    return bool(text(order, "lead").strip() or text(order, "schedstart").strip()) or not lead_known


def corrective_available(order: dict) -> bool:
    status = str(order.get("status") or text(order, "status")).strip().upper()
    return mode_for(order) == "corretiva" and (
        (status == "PREPARED" and not text(order, "schedstart").strip()) or status in ("WFSCH", "WSCH"))


def eligible(sectors: list[str], start: str, end: str) -> list[dict]:
    return [order for order in listar_ordens_trabalho(sectors)
            if order["status"].upper() not in TERMINAL and
            (corrective_available(order) or (mode_for(order) == "pm" and pm_constraint_before_end(order, end)
                                                 and not has_existing_planning_info(order)))]


def get_plan(plan_id: str, revision: int | None = None) -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT dados_json FROM pcm_planos WHERE id=?", (plan_id,)).fetchone() if revision is None else conn.execute(
            "SELECT dados_json FROM pcm_revisoes WHERE plano_id=? AND revisao=?", (plan_id, revision)).fetchone()
    if row is None:
        raise LookupError("Planejamento ou revisao nao encontrado.")
    return json.loads(row["dados_json"])


def list_plans() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT dados_json FROM pcm_planos ORDER BY atualizado_em DESC").fetchall()
    return [{key: doc[key] for key in
             ("id", "revisao", "status", "inicio", "fim", "setores", "planejador", "atualizado_em", "motivo")}
            for doc in (json.loads(row["dados_json"]) for row in rows)]


def delete_plan(plan_id: str) -> dict:
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id FROM pcm_planos WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise LookupError("Planejamento nao encontrado.")
        conn.execute("DELETE FROM pcm_revisoes WHERE plano_id=?", (plan_id,))
        conn.execute("DELETE FROM pcm_planos WHERE id=?", (plan_id,))
    return {"id": plan_id, "deleted": True}


def revisions(plan_id: str) -> list[dict]:
    get_plan(plan_id)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT revisao,salvo_em,motivo FROM pcm_revisoes WHERE plano_id=? ORDER BY revisao DESC",
            (plan_id,)).fetchall()
    return [dict(row) for row in rows]


def update_plan_team(plan_id: str, change: PlanTeamChange) -> dict:
    current = get_plan(plan_id)
    if current["revisao"] != change.revisao:
        raise ConflictError("O plano foi alterado. Recarregue antes de salvar a equipe.")
    team = change.equipe
    if (sorted(set(sector.upper() for sector in team.setores)) != current["setores"]
            or str(team.inicio) != current["inicio"] or str(team.fim) != current["fim"]):
        raise ValueError("A equipe deve manter os setores e o período deste planejamento.")
    if not team.executantes or not team.planejador.strip():
        raise ValueError("Selecione ao menos um executante e informe o planejador.")
    if any(member.capacidade != "dias_8h" for member in team.executantes):
        raise ValueError("Revise os dias disponíveis de 8 h dos executantes antes de salvar.")

    labor = listar_mao_de_obra(current["setores"])
    calcular_equipe(team, labor)
    labor_people = {(person["orgid"], person["matricula"]): person for person in labor["profissionais"]}
    people = []
    for member in team.executantes:
        person = labor_people[(member.orgid, member.matricula)]
        craft = next(craft for craft in person["especialidades"] if craft["codigo"] == member.funcao)
        people.append({"id": f"{member.orgid}:{member.matricula}", "nome": person["nome"],
                       "orgid": member.orgid, "matricula": member.matricula, "funcao": member.funcao,
                       "funcao_descricao": craft["descricao"],
                       "dias": sorted(str(day) for day in member.dias_disponiveis)})

    doc = copy.deepcopy(current)
    doc["equipe"] = team.model_dump(mode="json")
    doc["pessoas"] = people
    person_ids = {person["id"] for person in people}
    if (any(member not in person_ids for block in doc["blocos"] for member in block["executantes"])
            or any(item["executante"] not in person_ids for item in doc["indisponibilidades"])
            or any(item["executante"] not in person_ids for item in doc.get("posicionamentos", []))):
        raise ValueError("A equipe não pode remover executantes usados em blocos, indisponibilidades ou posicionamentos.")
    validate_plan(doc, current["status"] == "confirmado")
    doc.update(revisao=current["revisao"] + 1, atualizado_em=datetime.now(timezone.utc).isoformat(),
               motivo="Equipe do planejamento atualizada")
    encoded = json.dumps(doc, ensure_ascii=False)
    pdf = schedule_pdf(doc)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT revisao,status FROM pcm_planos WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise LookupError("Planejamento nao encontrado.")
        if row["revisao"] != change.revisao:
            raise ConflictError("O plano foi alterado. Recarregue antes de salvar a equipe.")
        if doc["status"] == "confirmado":
            validate_confirmed_capacity(conn, plan_id, doc)
        updated = conn.execute(
            "UPDATE pcm_planos SET revisao=?,atualizado_em=?,dados_json=? WHERE id=? AND revisao=?",
            (doc["revisao"], doc["atualizado_em"], encoded, plan_id, change.revisao))
        if updated.rowcount != 1:
            raise ConflictError("O plano foi alterado. Recarregue antes de salvar a equipe.")
        conn.execute("INSERT INTO pcm_revisoes VALUES (?,?,?,?,?,?)",
                     (plan_id, doc["revisao"], doc["atualizado_em"], doc["motivo"], encoded, pdf))
    return doc


def create_plan(sectors: list[str]) -> dict:
    saved = obter_equipe(sectors)
    if saved is None:
        raise ValueError("Defina e salve a mao de obra primeiro.")
    team = PlanejamentoEquipe.model_validate(saved)
    labor = listar_mao_de_obra(sectors)
    calcular_equipe(team, labor)
    if not team.executantes or not team.planejador.strip():
        raise ValueError("Salve uma equipe e identifique o planejador.")
    if any(member.capacidade != "dias_8h" for member in team.executantes):
        raise ValueError("Revise a equipe no modal e salve os dias disponiveis de 8 h antes de alocar.")
    scope = json.dumps([sorted(set(s.upper() for s in sectors)), str(team.inicio), str(team.fim)])
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM pcm_planos WHERE escopo=?", (scope,)).fetchone()
    if existing:
        return get_plan(existing["id"])
    people = {(p["orgid"], p["matricula"]): p for p in labor["profissionais"]}
    orders = eligible(sectors, str(team.inicio), str(team.fim))
    requirements = {}
    for order in orders:
        raw = text(order, "estdur")
        try:
            duration = float(raw)
        except ValueError:
            duration = 0
        requirements[order_key(order)] = Requirement(
            duracao=duration if 0 < duration <= 1000 else None, **labor_requirement(order, team.executantes)).model_dump()
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid4()), "revisao": 1, "status": "rascunho", "inicio": str(team.inicio),
        "fim": str(team.fim), "setores": sorted(set(s.upper() for s in sectors)),
        "planejador": team.planejador, "atualizado_em": now, "motivo": "Criacao do rascunho",
        "integracoes": {"bma": "pendente_configuracao", "sharepoint": "pendente_configuracao"},
        "equipe": saved, "pessoas": [
            {"id": f"{m.orgid}:{m.matricula}", "nome": people[(m.orgid, m.matricula)]["nome"],
             "orgid": m.orgid, "matricula": m.matricula, "funcao": m.funcao,
             "funcao_descricao": next(c["descricao"] for c in people[(m.orgid, m.matricula)]["especialidades"]
                                      if c["codigo"] == m.funcao),
             "dias": sorted(str(day) for day in m.dias_disponiveis)}
            for m in team.executantes],
        "ordens": orders, "requisitos": requirements, "blocos": [], "indisponibilidades": [], "horas_extras": [],
    }
    encoded = json.dumps(doc, ensure_ascii=False)
    pdf = schedule_pdf(doc)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT dados_json FROM pcm_planos WHERE escopo=?", (scope,)).fetchone()
        if existing:
            return json.loads(existing["dados_json"])
        conn.execute("INSERT INTO pcm_planos VALUES (?,?,?,?,?,?)",
                     (doc["id"], scope, 1, "rascunho", now, encoded))
        conn.execute("INSERT INTO pcm_revisoes VALUES (?,?,?,?,?,?)", (doc["id"], 1, now, doc["motivo"], encoded, pdf))
    return doc


def add_orders_to_plan(plan_id: str, request: AddOrders) -> dict:
    current = get_plan(plan_id)
    if current["revisao"] != request.revisao:
        raise ConflictError("O plano foi alterado. Recarregue antes de adicionar OTs.")
    if current["status"] != "rascunho":
        raise ValueError("Adicione OTs somente a um rascunho.")

    selected_keys = set(request.ordens)
    if len(selected_keys) != len(request.ordens):
        raise ValueError("A seleção contém OTs duplicadas.")
    candidates = {
        order_key(order): order
        for order in listar_ordens_trabalho(current["setores"])
        if str(order.get("status") or "").strip().upper() in {"WSCH", "PREPARED", "WFSCH"}
        and mode_for(order) == "pm"
    }
    if not selected_keys.issubset(candidates):
        raise ValueError("Uma ou mais OTs não estão mais no banco com status WSCH, PREPARED ou WFSCH.")

    doc = copy.deepcopy(current)
    existing = {order_key(order): index for index, order in enumerate(doc["ordens"])}
    for key in request.ordens:
        if candidates[key]["status"].strip().upper() == "WFSCH" and not (
            key in existing and doc["requisitos"][key].get("na_nuvem")
        ):
            raise ValueError("OT com status WFSCH só pode voltar se estiver na nuvem deste planejamento.")
    added = 0
    members = PlanejamentoEquipe.model_validate(doc["equipe"]).executantes
    for key in request.ordens:
        if key in existing:
            requirement = doc["requisitos"][key]
            if not requirement.get("na_nuvem"):
                continue
            doc["requisitos"][key] = {**requirement, "na_nuvem": False, "selecionada": False}
            added += 1
            continue

        order = candidates[key]
        try:
            duration = float(text(order, "estdur"))
        except ValueError:
            duration = 0
        doc["ordens"].append({**order, "planejamento_adicionado": True})
        doc["requisitos"][key] = Requirement(
            duracao=duration if 0 < duration <= 1000 else None,
            **labor_requirement(order, members),
        ).model_dump()
        added += 1

    if not added:
        raise ValueError("As OTs selecionadas já estão disponíveis neste cronograma.")
    validate_plan(doc)
    doc.update(
        revisao=current["revisao"] + 1,
        atualizado_em=datetime.now(timezone.utc).isoformat(),
        motivo="OTs adicionadas da carteira do banco de dados",
    )
    encoded = json.dumps(doc, ensure_ascii=False)
    pdf = schedule_pdf(doc)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT revisao,status FROM pcm_planos WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise LookupError("Planejamento nao encontrado.")
        if row["revisao"] != request.revisao or row["status"] != "rascunho":
            raise ConflictError("O plano foi alterado. Recarregue antes de adicionar OTs.")
        updated = conn.execute(
            "UPDATE pcm_planos SET revisao=?,atualizado_em=?,dados_json=? WHERE id=? AND revisao=?",
            (doc["revisao"], doc["atualizado_em"], encoded, plan_id, request.revisao),
        )
        if updated.rowcount != 1:
            raise ConflictError("O plano foi alterado. Recarregue antes de adicionar OTs.")
        conn.execute(
            "INSERT INTO pcm_revisoes VALUES (?,?,?,?,?,?)",
            (plan_id, doc["revisao"], doc["atualizado_em"], doc["motivo"], encoded, pdf),
        )
    return doc


def refresh_plan_orders(plan_id: str, request: RefreshPlanOrders) -> dict:
    current = get_plan(plan_id)
    if current["revisao"] != request.revisao:
        raise ConflictError("O plano foi alterado. Recarregue antes de atualizar os dados das OTs.")
    latest = {order_key(order): order for order in listar_ordens_trabalho(current["setores"])}
    doc = copy.deepcopy(current)
    updated = 0
    for index, order in enumerate(doc["ordens"]):
        fresh = latest.get(order_key(order))
        if fresh is None:
            continue
        doc["ordens"][index] = {**order, **fresh}
        updated += 1
    if not updated:
        return {"plano": current, "atualizadas": 0}

    validate_plan(doc)
    doc.update(
        revisao=current["revisao"] + 1,
        atualizado_em=datetime.now(timezone.utc).isoformat(),
        motivo="Dados das OTs atualizados do banco após consulta BMA",
    )
    encoded = json.dumps(doc, ensure_ascii=False)
    pdf = schedule_pdf(doc)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT revisao,status FROM pcm_planos WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise LookupError("Planejamento nao encontrado.")
        if row["revisao"] != request.revisao:
            raise ConflictError("O plano foi alterado. Recarregue antes de atualizar os dados das OTs.")
        updated_row = conn.execute(
            "UPDATE pcm_planos SET revisao=?,atualizado_em=?,dados_json=? WHERE id=? AND revisao=?",
            (doc["revisao"], doc["atualizado_em"], encoded, plan_id, request.revisao),
        )
        if updated_row.rowcount != 1:
            raise ConflictError("O plano foi alterado. Recarregue antes de atualizar os dados das OTs.")
        conn.execute(
            "INSERT INTO pcm_revisoes VALUES (?,?,?,?,?,?)",
            (plan_id, doc["revisao"], doc["atualizado_em"], doc["motivo"], encoded, pdf),
        )
    return {"plano": doc, "atualizadas": updated}


def import_bma_schedule(plan_id: str, results: list[dict]) -> dict:
    current = get_plan(plan_id)
    if current["status"] != "rascunho":
        raise ValueError("Importe o planejamento do BMA em um rascunho, sem substituir um plano confirmado.")

    doc = copy.deepcopy(current)
    available_orders = {order_key(order): order for order in listar_ordens_trabalho(doc["setores"])}
    for result in results:
        fresh = result.get("ordem_bma")
        if not isinstance(fresh, dict):
            continue
        fresh_order = {"dados": fresh}
        fresh_order.update({
            "siteid": text(fresh_order, "siteid") or str(result.get("siteid", "")),
            "wonum": text(fresh_order, "wonum") or str(result.get("numero_ot", "")),
            "status": text(fresh_order, "status"),
            "maintenanceshop": text(fresh_order, "maintenanceshop").upper(),
            "lead": text(fresh_order, "lead"),
            "schedstart": text(fresh_order, "schedstart"),
        })
        if fresh_order["siteid"] and fresh_order["wonum"]:
            available_orders[order_key(fresh_order)] = fresh_order
    orders_by_number: dict[str, list[dict]] = {}
    for order in available_orders.values():
        orders_by_number.setdefault(order["wonum"].upper(), []).append(order)
    labor = listar_mao_de_obra(doc["setores"], filtrar_nf=False)["profissionais"]
    labor_by_code: dict[str, list[dict]] = {}
    for person in labor:
        labor_by_code.setdefault(person["matricula"].upper(), []).append(person)

    plan_people = {person["id"]: person for person in doc["pessoas"]}
    team_members = {f'{member["orgid"]}:{member["matricula"]}': member
                    for member in doc["equipe"]["executantes"]}
    existing_numbers = {order["wonum"].upper() for order in doc["ordens"]}
    locally_allocated = {block["ot"] for block in doc["blocos"]}
    unavailable = {(item["executante"], str(item["dia"])) for item in doc["indisponibilidades"]}
    grouped: dict[tuple[str, str, float, float], set[str]] = {}
    order_groups: dict[str, set[tuple[str, str, float, float]]] = {}
    order_people: dict[str, dict[str, dict]] = {}
    imported_orders = set()
    updated_orders = set()
    warnings: list[str] = []

    def parse_assignment_start(raw_start: str):
        for pattern in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %I:%M %p"):
            try:
                return datetime.strptime(raw_start, pattern)
            except ValueError:
                continue
        return None

    for result in results:
        number = str(result.get("numero_ot", "")).strip().upper()
        matching_orders = orders_by_number.get(number, [])
        siteid = str(result.get("siteid", "")).strip().upper()
        order = next((candidate for candidate in matching_orders
                      if siteid and candidate["siteid"].upper() == siteid), None)
        if order is None and len(matching_orders) == 1:
            order = matching_orders[0]
        if order is None:
            warnings.append(f"{number or 'OT sem número'}: não encontrada na carteira local.")
            continue
        key = order_key(order)
        status = str(result.get("status") or text(order, "status")).strip().upper()
        if status in TERMINAL:
            warnings.append(f"{number}: status {status}; não será incluída no cronograma nem na carteira.")
            continue
        if number in existing_numbers and key in locally_allocated:
            warnings.append(f"{number}: mantida como estava; já possui blocos locais.")
            continue
        existing_index = next(
            (index for index, current_order in enumerate(doc["ordens"])
             if order_key(current_order) == key),
            None,
        )
        if existing_index is None:
            imported_order = {**order, "planejamento_bma_importado": True}
            doc["ordens"].append(imported_order)
            updated_orders.add(order["wonum"])
            try:
                duration = float(text(order, "estdur"))
            except ValueError:
                duration = 0
            doc["requisitos"][key] = Requirement(
                duracao=duration if 0 < duration <= 1000 else None,
                **labor_requirement(order, PlanejamentoEquipe.model_validate(doc["equipe"]).executantes),
            ).model_dump()
        else:
            doc["ordens"][existing_index] = {
                **doc["ordens"][existing_index], **order, "planejamento_bma_importado": True,
            }
            updated_orders.add(order["wonum"])
        existing_numbers.add(order["wonum"].upper())
        assignments = result.get("dados_adicionais", {}).get("atribuicoes", [])
        unavailable_assignment = None
        for assignment in assignments:
            planned_start = parse_assignment_start(str(assignment.get("inicio", "")).strip())
            if not planned_start:
                continue
            day = planned_start.date().isoformat()
            if not doc["inicio"] <= day <= doc["fim"]:
                continue
            laborcode = str(assignment.get("laborcode", "")).strip().upper()
            matches = labor_by_code.get(laborcode, [])
            person = next((candidate for candidate in matches
                           if f'{candidate["orgid"]}:{candidate["matricula"]}' in plan_people), None)
            if person is None and len(matches) == 1:
                person = matches[0]
            if person:
                person_id = f'{person["orgid"]}:{person["matricula"]}'
                if (person_id, day) in unavailable:
                    unavailable_assignment = (
                        f"{number}: {person['nome']} indisponível localmente em {day}; "
                        "OT mantida na carteira sem importar blocos para remanejamento."
                    )
                    break
        if unavailable_assignment:
            warnings.append(unavailable_assignment)
            continue

        parsed: list[tuple[str, str, float, float, dict]] = []
        invalid = None
        for assignment in assignments:
            raw_start = str(assignment.get("inicio", "")).strip()
            planned_start = parse_assignment_start(raw_start)
            if not planned_start:
                continue
            day = planned_start.date().isoformat()
            if not doc["inicio"] <= day <= doc["fim"]:
                continue
            raw_hours = str(assignment.get("horas", "")).strip().replace(",", ".")
            try:
                hours = (int(raw_hours.split(":", 1)[0]) + int(raw_hours.split(":", 1)[1]) / 60
                         if ":" in raw_hours else float(raw_hours))
            except ValueError:
                invalid = f"{number}: horas inválidas na atribuição de {assignment.get('laborcode', 'matrícula desconhecida')}."
                break
            laborcode = str(assignment.get("laborcode", "")).strip().upper()
            matches = labor_by_code.get(laborcode, [])
            person = next((candidate for candidate in matches
                           if f'{candidate["orgid"]}:{candidate["matricula"]}' in plan_people), None)
            if person is None and len(matches) == 1:
                person = matches[0]
            if not person:
                invalid = f"{number}: matrícula {laborcode or 'vazia'} não identificada na mão de obra local."
                break
            person_id = f'{person["orgid"]}:{person["matricula"]}'
            if person_id not in plan_people:
                crafts = person.get("especialidades", [])
                craft = next((item for item in crafts if item.get("principal")), None) or next(iter(crafts), None)
                if not craft or not craft.get("codigo"):
                    invalid = f"{number}: {laborcode} não possui especialidade no cadastro local."
                    break
                order_people.setdefault(key, {})[person_id] = {
                    "id": person_id, "nome": person["nome"], "orgid": person["orgid"],
                    "matricula": person["matricula"], "funcao": craft["codigo"],
                    "funcao_descricao": craft.get("descricao") or craft["codigo"], "dias": [],
                }
                team_members.setdefault(person_id, {
                    "orgid": person["orgid"], "matricula": person["matricula"],
                    "funcao": craft["codigo"], "jornada": "adm", "equipe": None,
                    "ajustes_datas": {}, "inicio_ciclo": None, "ajuste_horas": 0,
                    "ausencias": [], "capacidade": "dias_8h", "dias_disponiveis": [],
                })
            group_key = (key, day, planned_start.hour + planned_start.minute / 60, hours)
            grouped.setdefault(group_key, set()).add(person_id)
            order_groups.setdefault(key, set()).add(group_key)
            person_data = order_people.get(key, {}).get(person_id) or plan_people.get(person_id)
            if person_data is not None and day not in person_data["dias"]:
                person_data["dias"].append(day)
            team_member = team_members[person_id]
            if team_member["capacidade"] in ("dias_6h", "dias_8h"):
                team_member["dias_disponiveis"] = sorted(set(team_member.get("dias_disponiveis") or []) | {day})
            elif team_member["capacidade"] == "escala":
                previous_days = (plan_people.get(person_id) or {}).get("dias", [])
                team_member["capacidade"] = "dias_8h"
                team_member["dias_disponiveis"] = sorted(set(previous_days) | {day})
                team_member["ajustes_datas"] = {}
                team_member["ausencias"] = []
                team_member["inicio_ciclo"] = None
                team_member["ajuste_horas"] = 0
            parsed.append((key, day, group_key[2], hours, person))

        if invalid:
            warnings.append(invalid)
            for group_key in order_groups.pop(key, set()):
                grouped.pop(group_key, None)
            order_people.pop(key, None)
            continue
        if not parsed:
            warnings.append(
                f"{number}: sem executantes atribuídos; mantida pendente de planejamento e disponível para alocação local."
            )

    for people in order_people.values():
        for person_id, person in people.items():
            if person_id not in plan_people:
                doc["pessoas"].append(person)
                plan_people[person_id] = person
    doc["equipe"]["executantes"] = list(team_members.values())
    blocks = list(doc["blocos"])
    for key, group_keys in order_groups.items():
        order = available_orders[key]
        if order["wonum"].upper() in existing_numbers and key in locally_allocated:
            continue
        sizes = {len(grouped[group_key]) for group_key in group_keys}
        if len(sizes) != 1 or not sizes or 0 in sizes:
            warnings.append(f"{order['wonum']}: quantidade de executantes varia entre atribuições; OT não importada.")
            continue
        existing_index = next(
            (index for index, current_order in enumerate(doc["ordens"])
             if order_key(current_order) == key),
            None,
        )
        if existing_index is None:
            doc["ordens"].append(order)
        else:
            doc["ordens"][existing_index] = {**doc["ordens"][existing_index], **order}
        existing_numbers.add(order["wonum"].upper())
        imported_blocks = []
        for group_key in sorted(group_keys, key=lambda item: (item[1], item[2])):
            _, day, start, hours = group_key
            imported_blocks.append({
                "id": str(uuid4()), "ot": key, "dia": day, "inicio": start,
                "horas": hours, "executantes": sorted(grouped[group_key]),
            })
        total_hours = sum(block["horas"] for block in imported_blocks)
        doc["requisitos"][key] = Requirement(
            duracao=total_hours, pessoas=next(iter(sizes)), todas_especialidades=True,
            liberada=True,
        ).model_dump()
        candidate = copy.deepcopy(doc)
        candidate["blocos"] = [*blocks, *imported_blocks]
        try:
            validate_plan(candidate)
        except ValueError as exc:
            warnings.append(
                f"{order['wonum']}: {exc} OT mantida na carteira como pendente de planejamento."
            )
            continue
        blocks.extend(imported_blocks)
        imported_orders.add(order["wonum"])

    saved = current
    if updated_orders or imported_orders:
        doc.update(
            revisao=current["revisao"] + 1,
            atualizado_em=datetime.now(timezone.utc).isoformat(),
            motivo="Importação do planejamento do BMA",
        )
        doc["blocos"] = blocks
        validate_plan(doc)
        encoded = json.dumps(doc, ensure_ascii=False)
        pdf = schedule_pdf(doc)
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT revisao FROM pcm_planos WHERE id=?", (plan_id,)).fetchone()
            if row is None:
                raise LookupError("Planejamento nao encontrado.")
            if row["revisao"] != current["revisao"]:
                raise ConflictError("O plano foi alterado. Recarregue antes de importar o BMA.")
            updated = conn.execute(
                "UPDATE pcm_planos SET revisao=?,atualizado_em=?,dados_json=? WHERE id=? AND revisao=?",
                (doc["revisao"], doc["atualizado_em"], encoded, plan_id, current["revisao"]),
            )
            if updated.rowcount != 1:
                raise ConflictError("O plano foi alterado. Recarregue antes de importar o BMA.")
            conn.execute(
                "INSERT INTO pcm_revisoes VALUES (?,?,?,?,?,?)",
                (plan_id, doc["revisao"], doc["atualizado_em"], doc["motivo"], encoded, pdf),
            )
        saved = doc
    return {"plano": saved, "importadas": sorted(imported_orders), "avisos": warnings}


def prepare_change(current: dict, change: PlanChange) -> dict:
    if current["revisao"] != change.revisao:
        raise ConflictError("Outro usuario alterou este plano. Recarregue antes de salvar.")
    doc = copy.deepcopy(current)
    doc.update(change.model_dump(mode="json", exclude={"revisao", "confirmar", "motivo", "atualizar_especialidades"}))
    for block in doc["blocos"]:
        block["inicio"] = 0
    if set(doc["requisitos"]) != {order_key(order) for order in doc["ordens"]}:
        raise ValueError("Os requisitos devem corresponder exatamente a carteira do plano.")
    if not change.motivo.strip():
        raise ValueError("Informe o motivo da revisao.")
    if change.atualizar_especialidades:
        merge_labor(doc)
    return doc


def labor_requirement(order: dict, members) -> dict:
    rows = order.get("dados", {}).get("wplabor", [])
    if not isinstance(rows, list):
        return {}
    def value(row, key):
        raw = row.get(key)
        return raw.get("value", raw.get("_value", raw.get("description"))) if isinstance(raw, dict) else raw

    labor_rows = [row for row in rows if isinstance(row, dict)]
    if not labor_rows:
        return {}
    crafts = {str(value(row, key) or "").strip() for row in labor_rows
              for key in ("craft", "especialidade") if value(row, key)}
    orgs = {str(value(row, "orgid") or "").strip() for row in labor_rows if value(row, "orgid")}
    result = {}
    if len(crafts) == 1:
        craft = next(iter(crafts))
        matching = {m.orgid for m in members if m.funcao == craft and (not orgs or m.orgid in orgs)}
        if len(orgs) == 1 or len(matching) == 1:
            result.update(funcao=craft, orgid=next(iter(orgs)) if orgs else next(iter(matching)))
    quantities = []
    for row in labor_rows:
        raw_quantity = value(row, "quantity") or value(row, "quantidade")
        try:
            quantity = float(raw_quantity)
        except (TypeError, ValueError):
            quantities = []
            break
        if not 1 <= quantity <= 100 or not quantity.is_integer():
            quantities = []
            break
        quantities.append(quantity)
    quantity = sum(quantities)
    if 1 <= quantity <= 100 and quantity.is_integer():
        result["pessoas"] = int(quantity)
    return result


def refresh_labor(current: dict, change: PlanChange) -> dict:
    doc = prepare_change(current, change.model_copy(update={"atualizar_especialidades": False}))
    updated = merge_labor(doc)
    return {"plano": doc, "atualizadas": updated}


def merge_labor(doc: dict) -> int:
    latest = {order_key(o): o for o in listar_ordens_trabalho(doc["setores"])}
    updated = 0
    members = PlanejamentoEquipe.model_validate(doc["equipe"]).executantes
    allocated = {b["ot"] for b in doc["blocos"]}
    for order in doc["ordens"]:
        key = order_key(order)
        fresh = latest.get(key)
        if not fresh or "wplabor" not in fresh["dados"]:
            continue
        order["dados"]["wplabor"] = copy.deepcopy(fresh["dados"]["wplabor"])
        order["sincronizado_em"] = fresh["sincronizado_em"]
        updated += 1
        req = doc["requisitos"][key]
        if key not in allocated:
            inferred = labor_requirement(order, members)
            if not req["funcao"] and not req.get("todas_especialidades"):
                req.update({k: v for k, v in inferred.items() if k in ("funcao", "orgid")})
            if not req["pessoas"] and "pessoas" in inferred:
                req["pessoas"] = inferred["pessoas"]
    if not updated:
        raise ValueError("O banco ainda nao possui mao de obra planejada para estas OTs. Atualize o banco pelo BMA primeiro.")
    return updated


def validate_plan(doc: dict, confirming: bool = False) -> None:
    people = {p["id"]: p for p in doc["pessoas"]}
    orders = {order_key(o): o for o in doc["ordens"]}
    positioned = set()
    for placement in doc.get("posicionamentos", []):
        if (placement["ot"] not in orders or placement["executante"] not in people
                or not doc["inicio"] <= placement["dia"] <= doc["fim"] or placement["ot"] in positioned):
            raise ValueError("Posicionamento de OT invalido ou duplicado.")
        positioned.add(placement["ot"])
    if confirming and positioned:
        raise ValueError("Complete os dados e as horas das OTs posicionadas no rascunho ou retire seus cartoes antes de confirmar.")
    unavailable = set()
    for item in doc["indisponibilidades"]:
        key = (item["executante"], item["dia"])
        if item["executante"] not in people or not doc["inicio"] <= item["dia"] <= doc["fim"] or key in unavailable or not item["motivo"].strip():
            raise ValueError("Indisponibilidade invalida ou duplicada.")
        unavailable.add(key)
    duration: dict[str, float] = {}
    order_weeks: dict[str, str] = {}
    block_hours: dict[tuple[str, str, str], float] = {}
    ids = set()
    for block in doc["blocos"]:
        ot, day = block["ot"], block["dia"]
        if ot not in orders or block["id"] in ids:
            raise ValueError("Bloco duplicado ou OT fora da carteira.")
        ids.add(block["id"])
        req = doc["requisitos"][ot]
        week = week_start(day)
        if ot in order_weeks and order_weeks[ot] != week:
            raise ValueError(f"{orders[ot]['wonum']}: a continuacao da atividade deve permanecer na mesma semana.")
        order_weeks[ot] = week
        if not req["duracao"] or not req["pessoas"]:
            raise ValueError(f"{orders[ot]['wonum']}: informe duracao e quantidade de pessoas.")
        if not doc["inicio"] <= day <= doc["fim"]:
            raise ValueError("Bloco fora do horizonte.")
        earliest = day_value(text(orders[ot], "sneconstraint"))
        if earliest and day < earliest:
            raise ValueError(f"{orders[ot]['wonum']}: bloco antecede a data de inicio permitida no BMA.")
        members = block["executantes"]
        if len(members) != req["pessoas"] or len(set(members)) != len(members):
            raise ValueError("O bloco deve ter a quantidade simultanea de executantes requerida.")
        for member in members:
            person = people.get(member)
            if not person:
                raise ValueError("Executante fora da equipe.")
            if day not in person["dias"] or (member, day) in unavailable:
                raise ValueError(f"{person['nome']}: indisponivel em {day}.")
            block_key = (ot, member, day)
            block_hours[block_key] = block_hours.get(block_key, 0) + block["horas"]
        duration[ot] = duration.get(ot, 0) + block["horas"]
        if duration[ot] > req["duracao"] + 1e-6:
            raise ValueError(f"{orders[ot]['wonum']}: duracao alocada acima da atividade.")
    overtime_keys = set()
    for extra in doc.get("horas_extras", []):
        ot, member, day = extra["ot"], extra["executante"], extra["dia"]
        key = (ot, member, day)
        person = people.get(member)
        if (key in overtime_keys or ot not in orders or not person or not doc["inicio"] <= day <= doc["fim"]
                or day not in person["dias"] or (member, day) in unavailable
                or extra["horas"] > block_hours.get(key, 0) + 1e-6):
            raise ValueError("Hora extra invalida: confira OT, executante, data e horas do bloco.")
        overtime_keys.add(key)
    if confirming:
        for (person, week), total in weekly_totals([doc]).items():
            if total["horas"] > total["capacidade"] + 1e-6:
                raise ValueError(f"{people[person]['nome']}: capacidade semanal excedida na semana de {week}.")
        for key, req in doc["requisitos"].items():
            if req.get("selecionada") and (not req["duracao"] or abs(duration.get(key, 0) - req["duracao"]) > 1e-6):
                raise ValueError(f"{orders[key]['wonum']}: OT marcada para planejar ainda nao esta totalmente alocada.")
        for ot, hours in duration.items():
            if abs(hours - doc["requisitos"][ot]["duracao"]) > 1e-6:
                raise ValueError(f"{orders[ot]['wonum']}: atividade parcialmente alocada. Complete ou retire antes de confirmar.")


def save_plan(plan_id: str, change: PlanChange) -> dict:
    current = get_plan(plan_id)
    doc = prepare_change(current, change)
    if change.confirmar and current["status"] == "rascunho" and not doc["blocos"]:
        raise ValueError("Aloque ao menos uma atividade antes de confirmar.")
    validate_plan(doc, change.confirmar or current["status"] == "confirmado")
    # Recheck active workforce and open orders when confirming or revising an operational plan.
    if change.confirmar or current["status"] == "confirmado":
        calcular_equipe(PlanejamentoEquipe.model_validate(doc["equipe"]), listar_mao_de_obra(doc["setores"]))
        active = {order_key(o) for o in listar_ordens_trabalho(doc["setores"]) if o["status"].upper() not in TERMINAL}
        if any(block["ot"] not in active for block in doc["blocos"]):
            raise ValueError("Uma OT alocada foi encerrada ou saiu dos setores. Retire-a e revise o plano.")
    doc.update(revisao=current["revisao"] + 1, atualizado_em=datetime.now(timezone.utc).isoformat(),
               motivo=change.motivo.strip(),
               status="confirmado" if change.confirmar or current["status"] == "confirmado" else "rascunho")
    encoded = json.dumps(doc, ensure_ascii=False)
    pdf = schedule_pdf(doc)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if doc["status"] == "confirmado":
            validate_confirmed_capacity(conn, plan_id, doc)
        updated = conn.execute(
            "UPDATE pcm_planos SET revisao=?,status=?,atualizado_em=?,dados_json=? WHERE id=? AND revisao=?",
            (doc["revisao"], doc["status"], doc["atualizado_em"], encoded, plan_id, change.revisao))
        if updated.rowcount != 1:
            raise ConflictError("O plano foi alterado. Recarregue antes de salvar.")
        conn.execute("INSERT INTO pcm_revisoes VALUES (?,?,?,?,?,?)",
                     (plan_id, doc["revisao"], doc["atualizado_em"], doc["motivo"], encoded, pdf))
    return doc


def validate_confirmed_capacity(conn, plan_id: str, doc: dict) -> None:
    rows = conn.execute("SELECT dados_json FROM pcm_planos WHERE status='confirmado' AND id<>?", (plan_id,)).fetchall()
    others = [json.loads(row["dados_json"]) for row in rows]
    for other in others:
        if (other["inicio"] <= doc["fim"] and other["fim"] >= doc["inicio"]
                and {block["ot"] for block in doc["blocos"]} & {block["ot"] for block in other["blocos"]}):
            raise ValueError("Uma OT ja esta alocada em outro planejamento confirmado no mesmo horizonte.")
    totals = weekly_totals([doc, *others])
    relevant = {(person, week_start(block["dia"])) for block in doc["blocos"] for person in block["executantes"]}
    if any(totals[key]["horas"] > totals[key]["capacidade"] + 1e-6 for key in relevant):
        raise ValueError("Executante ja comprometido: capacidade semanal excedida entre planejamentos confirmados.")


def suggest(current: dict, request: Suggestion) -> dict:
    doc = prepare_change(current, request.alteracoes)
    validate_plan(doc)
    unavailable = {(a["executante"], a["dia"]) for a in doc["indisponibilidades"]}
    candidates = [o for o in doc["ordens"] if mode_for(o) == request.modo]
    if request.ordens is not None:
        selected = set(request.ordens)
        if any(key not in doc["requisitos"] for key in selected):
            raise ValueError("Selecao de OTs fora da carteira.")
        candidates = [o for o in candidates if order_key(o) in selected]
    candidates.sort(key=lambda o: (
        day_value(text(o, "fnlconstraint")) or "9999",
        doc["requisitos"][order_key(o)]["prioridade"],
        day_value(text(o, "targstartdate")) or "9999",
        o["wonum"],
    ))
    messages = []
    day = date.fromisoformat(doc["inicio"])
    days = []
    while str(day) <= doc["fim"]:
        days.append(str(day))
        day += timedelta(days=1)
    for order in candidates:
        key = order_key(order)
        req = doc["requisitos"][key]
        if not req["duracao"] or not req["pessoas"]:
            messages.append(f"{order['wonum']}: preparacao incompleta.")
            continue
        remaining = round(req["duracao"] - sum(b["horas"] for b in doc["blocos"] if b["ot"] == key), 6)
        if remaining <= 1e-6:
            continue
        earliest = day_value(text(order, "sneconstraint"))
        latest = day_value(text(order, "fnlconstraint"))
        execution_days = [candidate_day for candidate_day in days
                          if (not earliest or candidate_day >= earliest)
                          and (not latest or candidate_day <= latest)]
        if not execution_days:
            messages.append(f"{order['wonum']}: a janela de execucao nao cruza o periodo do planejamento.")
            continue
        target = day_value(text(order, "targstartdate")) or day_value(text(order, "schedstart"))
        existing_days = [block["dia"] for block in doc["blocos"] if block["ot"] == key]
        if existing_days:
            activity_week = week_start(existing_days[0])
        else:
            preferred_day = min(execution_days, key=lambda value: (
                abs((date.fromisoformat(value) - date.fromisoformat(target)).days) if target else 0,
                value,
            ))
            activity_week = week_start(preferred_day)
        execution_days = [candidate_day for candidate_day in execution_days
                          if week_start(candidate_day) == activity_week]
        total_person_capacity = {}
        for person in doc["pessoas"]:
            total_person_capacity[person["id"]] = max(8, 8 * sum(
                doc["inicio"] <= available_day <= doc["fim"]
                and (person["id"], available_day) not in unavailable
                for available_day in person["dias"]
            ))
        for day in sorted(execution_days, key=lambda value: (
            abs((date.fromisoformat(value) - date.fromisoformat(target)).days) if target else 0,
            value,
        )):
            if remaining <= 1e-6:
                break
            totals = weekly_totals([doc])
            free = []
            for person in doc["pessoas"]:
                if day not in person["dias"] or (person["id"], day) in unavailable:
                    continue
                total = totals[(person["id"], week_start(day))]
                load = sum(b["horas"] for b in doc["blocos"] if b["dia"] == day and person["id"] in b["executantes"])
                room = min(8 - load, total["capacidade"] - total["horas"])
                if room > 1e-6:
                    assigned = sum(b["horas"] for b in doc["blocos"] if person["id"] in b["executantes"])
                    utilization = assigned / total_person_capacity[person["id"]]
                    free.append((person["id"], room, utilization, total["horas"], load))
            if len(free) < req["pessoas"]:
                continue
            free.sort(key=lambda candidate: (candidate[2], candidate[3], candidate[4], candidate[0]))
            crew = free[:req["pessoas"]]
            hours = round(min(remaining, *(candidate[1] for candidate in crew)), 6)
            doc["blocos"].append({"id": str(uuid4()), "ot": key, "dia": day,
                                  "inicio": 0, "horas": hours, "executantes": [candidate[0] for candidate in crew]})
            remaining = round(remaining - hours, 6)
        if remaining > 1e-6:
            messages.append(f"{order['wonum']}: faltam {remaining:g} h de duracao por falta de capacidade compativel.")
    validate_plan(doc)
    return {"blocos": doc["blocos"], "mensagens": messages}


def spreadsheet(payload: ExportOrders) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    if payload.modo == "pm" and (payload.inicio is None or payload.fim is None or payload.fim < payload.inicio):
        raise ValueError("Informe um periodo valido para exportar as preventivas.")
    available = {order_key(o): o for o in eligible(payload.setores, str(payload.inicio or ""), str(payload.fim or ""))
                 if mode_for(o) == payload.modo}
    if len(set(payload.ordens)) != len(payload.ordens) or any(key not in available for key in payload.ordens):
        raise ValueError("A exportacao contem OT fora da carteira selecionada. Recarregue os dados.")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "PM" if payload.modo == "pm" else "Corretiva"
    columns = [("wonum", "OT"), ("description", "Descricao"), ("status", "Status"),
               ("worktype", "Tipo"), ("maintenanceshop", "Setor"), ("location", "Local"),
               ("assetnum", "Equipamento"), ("estdur", "Duracao (h)"), ("estlabhrs", "HH estimado"),
               ("targstartdate", "Inicio alvo"), ("targcompdate", "Fim alvo"),
               ("schedstart", "Inicio programado"), ("schedfinish", "Fim programado")]
    sheet.append([label for _, label in columns])
    for key in payload.ordens:
        order = available[key]
        sheet.append([text(order, field) for field, _ in columns])
        for cell in sheet[sheet.max_row]:
            # Explicit string cells prevent spreadsheet formula execution.
            cell.data_type = "s"
        for index in range(10, 14):
            cell = sheet.cell(sheet.max_row, index)
            value = day_value(cell.value)
            if value:
                cell.value = date.fromisoformat(value)
                cell.number_format = "DD/MM/YYYY"
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="003B71")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, width in enumerate([20, 70, 18, 12, 22, 22, 22, 18, 18, 20, 20, 22, 22], 1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _planner_display_name(value: str, people: list[dict]) -> str:
    planner = value.strip()
    normalized_planner = planner.casefold()
    for person in people:
        registration = str(person.get("matricula") or "").strip()
        name = str(person.get("nome") or "").strip()
        if not registration or not name:
            continue
        if normalized_planner in {registration.casefold(), name.casefold()} \
                or normalized_planner.startswith(f"{registration.casefold()} - "):
            return f"{registration} - {name}"
    return planner


def schedule_pdf(doc: dict) -> bytes:
    from services.pcm_pdf import render_schedule
    report = copy.deepcopy(doc)
    planner = str(report.get("planejador") or "").strip()
    if planner:
        people = listar_mao_de_obra(None, filtrar_nf=False)["profissionais"]
        report["planejador"] = _planner_display_name(planner, people)
    return render_schedule(report)


def get_pdf(plan_id: str, revision: int) -> bytes:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT dados_json, pdf FROM pcm_revisoes WHERE plano_id=? AND revisao=?",
            (plan_id, revision),
        ).fetchone()
    if row is None:
        raise LookupError("Cronograma nao encontrado.")
    doc = json.loads(row["dados_json"])
    planner = str(doc.get("planejador") or "").strip()
    if planner:
        people = listar_mao_de_obra(None, filtrar_nf=False)["profissionais"]
        resolved = _planner_display_name(planner, people)
        if resolved != planner:
            doc["planejador"] = resolved
            from services.pcm_pdf import render_schedule
            return render_schedule(doc)
    return bytes(row["pdf"])


def get_person_pdf(plan_id: str, revision: int, executante: str) -> bytes:
    doc = get_plan(plan_id, revision)
    person = next((item for item in doc["pessoas"] if item["id"] == executante), None)
    if person is None:
        raise LookupError("Executante nao encontrado nesta revisao.")
    blocks = [
        {**block, "executantes": [executante]}
        for block in doc["blocos"] if executante in block["executantes"]
    ]
    if not blocks:
        raise ValueError("Este executante nao possui atividades na revisao.")
    order_keys = {block["ot"] for block in blocks}
    individual = copy.deepcopy(doc)
    individual["pessoas"] = [person]
    individual["ordens"] = [order for order in doc["ordens"] if order_key(order) in order_keys]
    individual["requisitos"] = {key: value for key, value in doc["requisitos"].items() if key in order_keys}
    individual["blocos"] = blocks
    individual["indisponibilidades"] = [item for item in doc["indisponibilidades"] if item["executante"] == executante]
    individual["posicionamentos"] = [item for item in doc.get("posicionamentos", []) if item["executante"] == executante]
    individual["horas_extras"] = [item for item in doc.get("horas_extras", []) if item["executante"] == executante]
    team = individual.get("equipe", {})
    team["executantes"] = [
        member for member in team.get("executantes", [])
        if f'{member["orgid"]}:{member["matricula"]}' == executante
    ]
    individual["motivo"] = f"PDF individual · {person['nome']}"
    return schedule_pdf(individual)
