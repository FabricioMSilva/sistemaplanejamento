"""Read SharePoint workforce and OT-round lists through the authenticated browser session."""

import json
from urllib.parse import urlencode, urljoin, urlsplit

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

from models.workforce_identity import normalizar
from utils.runtime_paths import data_root, resource_root
from .BMAService import BMAService, BMAServiceError

SITE = "https://michelingroup.sharepoint.com/sites/NF-RES"
LIST_URL = SITE + "/Lists/ListaFuncionario/AllItems.aspx"
ROUND_LIST_URL = SITE + "/Lists/AbrirOTRonda/AllItems.aspx"


def _load_ronda_reference(path=None) -> dict[str, list[dict]]:
    if path is not None:
        reference_path = path
    else:
        local_path = data_root() / "database" / "data" / "funcionario.json"
        packaged_path = resource_root() / "database" / "data" / "funcionario.json"
        reference_path = local_path if local_path.is_file() else packaged_path
    try:
        employees = json.loads(reference_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BMAServiceError(f"Não foi possível ler o cadastro {reference_path.name}.") from exc
    if not isinstance(employees, list) or not employees:
        raise BMAServiceError(f"O cadastro {reference_path.name} está vazio ou inválido.")

    indexed = {}
    missing_registration = []
    for index, employee in enumerate(employees, start=1):
        if not isinstance(employee, dict):
            raise BMAServiceError(f"Registro {index} inválido em {reference_path.name}.")
        name = " ".join(str(employee.get("Nome") or "").split())
        registration = " ".join(str(employee.get("Matricula") or "").split()).upper()
        if not registration:
            missing_registration.append(name or f"registro {index}")
            continue
        if not name:
            raise BMAServiceError(f"Registro {index} sem Nome em {reference_path.name}.")
        aliases = employee.get("NomesAlternativos") or []
        if not isinstance(aliases, list):
            raise BMAServiceError(f"NomesAlternativos inválidos para {name} em {reference_path.name}.")
        person = {"nome": name, "matricula": registration}
        for candidate_name in [name, *aliases]:
            key = normalizar(str(candidate_name or ""))
            if key:
                indexed.setdefault(key, {})[normalizar(registration)] = person

    if missing_registration:
        names = ", ".join(missing_registration)
        raise BMAServiceError(f"Funcionário(s) sem matrícula em {reference_path.name}: {names}.")
    if not indexed:
        raise BMAServiceError(f"O cadastro {reference_path.name} não contém funcionários válidos.")
    return {key: list(people.values()) for key, people in indexed.items()}


def _sharepoint_json(driver, url: str) -> dict:
    result = driver.execute_async_script("""
        const url=arguments[0], done=arguments[arguments.length-1];
        fetch(url, {credentials:"same-origin",headers:{Accept:"application/json;odata=nometadata"}})
          .then(async response => {
            if (!response.ok) { done({error:"SharePoint HTTP "+response.status}); return; }
            done({data:await response.json()});
          }).catch(error=>done({error:String(error)}));
    """, url)
    if not isinstance(result, dict):
        raise BMAServiceError("Falha ao consultar SharePoint: resposta inválida.")
    if result.get("error"):
        raise BMAServiceError(f"Falha ao consultar SharePoint: {result['error']}")
    payload = result.get("data")
    if not isinstance(payload, dict):
        raise BMAServiceError("Falha ao consultar SharePoint: conteúdo inválido.")
    return payload


def _sharepoint_value(value):
    if isinstance(value, dict):
        if isinstance(value.get("results"), list):
            return _sharepoint_value(value["results"])
        return value.get("Title", value.get("LookupValue", value.get("Value", value.get("value", ""))))
    if isinstance(value, list):
        return "; ".join(str(_sharepoint_value(item)).strip() for item in value if _sharepoint_value(item))
    return str(value or "").strip()


def _round_executants(value) -> list[str]:
    if isinstance(value, dict) and isinstance(value.get("results"), list):
        value = value["results"]
    rows = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(name for name in (_sharepoint_value(row) for row in rows) if name))


def abrir_sharepoint_autenticado(driver, timeout: int, progress=None) -> None:
    if progress:
        progress("navegando", "Abrindo a lista AbrirOTRonda no SharePoint corporativo.", None, None)
    try:
        driver.get(ROUND_LIST_URL)
    except TimeoutException:
        pass
    auth_service = BMAService()
    email_submitted = False

    def sharepoint_authenticated(browser):
        nonlocal email_submitted
        current_url = browser.current_url
        hostname = (urlsplit(current_url).hostname or "").casefold()
        if hostname in {"login.microsoftonline.com", "login.microsoft.com", "login.windows.net"} and not email_submitted:
            email_submitted = auth_service._advance_microsoft_email(browser)
            if email_submitted and progress:
                progress("autenticacao", "E-mail enviado; aguardando senha ou MFA, se solicitado.", None, None)
        return current_url.startswith(SITE + "/")

    try:
        WebDriverWait(driver, timeout, poll_frequency=0.5).until(sharepoint_authenticated)
    except TimeoutException as exc:
        raise BMAServiceError("Não foi possível autenticar no SharePoint para consultar as OTs de Ronda.") from exc


def coletar_ots_ronda(driver, timeout: int, profissionais: list[dict], progress=None) -> dict:
    reference = _load_ronda_reference()
    abrir_sharepoint_autenticado(driver, timeout, progress)

    if progress:
        progress("lendo_colunas", "Sessão SharePoint ativa; lendo as colunas da lista.", None, None)

    fields_url = SITE + "/_api/web/lists/getbytitle('AbrirOTRonda')/fields?" + urlencode({
        "$select": "Title,InternalName,TypeAsString,Hidden",
        "$top": "500",
    }, safe=",/")
    metadata = _sharepoint_json(driver, fields_url).get("value")
    if not isinstance(metadata, list):
        raise BMAServiceError("O SharePoint não retornou as colunas da lista AbrirOTRonda.")
    columns = {normalizar(str(field.get("Title") or "")): field for field in metadata
               if isinstance(field, dict) and not field.get("Hidden")}
    round_field = columns.get("RONDA") or columns.get("RONDAS")
    required = {"STATUS": columns.get("STATUS"), "RONDA": round_field, "NOME": columns.get("NOME")}
    missing = [key for key, field in required.items() if not field]
    if missing:
        raise BMAServiceError(f"Colunas não encontradas na lista AbrirOTRonda: {', '.join(missing)}.")

    status_field, round_field, name_field = (required[key] for key in ("STATUS", "RONDA", "NOME"))
    matricula_field = columns.get("MATRICULA")
    ot_number_field = columns.get("NOT")
    data_field = columns.get("DATE") or columns.get("DATA")
    shift_field = columns.get("HORARIO") or columns.get("TURNO")
    team_field = columns.get("EQUIPE") or columns.get("TEAM")
    status_name = status_field["InternalName"]
    round_name = round_field["InternalName"]
    name_name = name_field["InternalName"]
    matricula_name = matricula_field["InternalName"] if matricula_field else None
    ot_number_name = ot_number_field["InternalName"] if ot_number_field else None
    expanded_name = name_field.get("TypeAsString") in {"User", "UserMulti", "Lookup", "LookupMulti"}
    selections = ["Id", status_name, round_name]
    expands = []
    if expanded_name:
        selections.append(f"{name_name}/Title")
        expands.append(name_name)
    else:
        selections.append(name_name)
    if matricula_name:
        selections.append(matricula_name)
    if ot_number_name:
        selections.append(ot_number_name)
    for field in (data_field, shift_field, team_field):
        if field and field["InternalName"] not in selections:
            selections.append(field["InternalName"])
    query = {"$select": ",".join(selections), "$top": "5000"}
    if expands:
        query["$expand"] = ",".join(expands)
    next_url = SITE + "/_api/web/lists/getbytitle('AbrirOTRonda')/items?" + urlencode(query, safe=",/")
    origin = urlsplit(SITE)
    visited = set()
    pending = []
    blocked = []
    all_items = []
    employees = {}
    for _ in range(100):
        if next_url in visited or urlsplit(next_url).netloc != origin.netloc or not next_url.startswith(SITE + "/_api/"):
            raise BMAServiceError("Paginação inválida da lista AbrirOTRonda.")
        visited.add(next_url)
        payload = _sharepoint_json(driver, next_url)
        values = payload.get("value")
        if not isinstance(values, list):
            raise BMAServiceError("Resposta SharePoint sem itens da lista AbrirOTRonda.")
        for item in values:
            if not isinstance(item, dict):
                raise BMAServiceError("A lista AbrirOTRonda contém um item inválido.")
            status = _sharepoint_value(item.get(status_name))
            names = _round_executants(item.get(name_name))
            list_matricula = _sharepoint_value(item.get(matricula_name)) if matricula_name else ""
            matches = []
            for name in names:
                reference_matches = reference.get(normalizar(name), [])
                if len(reference_matches) > 1 and list_matricula:
                    reference_matches = [person for person in reference_matches
                                         if normalizar(person["matricula"]) == normalizar(list_matricula)]
                reference_person = reference_matches[0] if len(reference_matches) == 1 else None
                registration = reference_person["matricula"] if reference_person else None
                candidates = [person for person in profissionais
                              if registration and normalizar(registration) == normalizar(person.get("matricula", ""))]
                bma_person = candidates[0] if len(candidates) == 1 else None
                link = ("confirmado" if bma_person else "referencia_json") if registration else (
                    "ambiguo" if len(reference_matches) > 1 else "sem_vinculo"
                )
                person = {
                    "nome": name,
                    "matricula": registration,
                    "matricula_lista": list_matricula or None,
                    "orgid": bma_person.get("orgid") if bma_person else None,
                    "vinculo": link,
                    "fonte_matricula": "json" if registration else None,
                }
                matches.append(person)
                if registration:
                    employees[(normalizar(name), normalizar(registration))] = {
                        "nome": name,
                        "matricula_lista": registration,
                        "matricula_bma": registration,
                        "orgid": bma_person.get("orgid", "") if bma_person else "",
                        "vinculo": link,
                    }
            item_result = {
                "id": item.get("Id"),
                "numero_ot": _sharepoint_value(item.get(ot_number_name)) if ot_number_name else "",
                "status": status,
                "ronda": _sharepoint_value(item.get(round_name)) or "Não informado",
                "data": _sharepoint_value(item.get(data_field["InternalName"])) if data_field else "",
                "turno": _sharepoint_value(item.get(shift_field["InternalName"])) if shift_field else "",
                "equipe": _sharepoint_value(item.get(team_field["InternalName"])) if team_field else "",
                "executantes": matches,
                "bloqueios_matricula": [person["nome"] for person in matches if not person["matricula"]],
                "sharepoint_raw": item,
            }
            all_items.append(item_result)
            if normalizar(status) != "PENDENTE":
                continue
            if matches and all(person["matricula"] for person in matches):
                pending.append(item_result)
            else:
                if not matches:
                    item_result["bloqueios_matricula"] = ["Executante não informado"]
                blocked.append(item_result)
        link = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
        if not link:
            if progress:
                progress("concluido", f"Lista consultada: {len(pending)} OT(s) apta(s), {len(blocked)} bloqueada(s) por matrícula e {len(employees)} funcionário(s).", None, len(pending) + len(blocked))
            return {
                "itens": all_items,
                "pendentes": pending,
                "bloqueadas": blocked,
                "funcionarios": sorted(employees.values(), key=lambda row: normalizar(row["nome"])),
            }
        if progress:
            progress("lendo_itens", f"Lendo itens da lista AbrirOTRonda ({len(pending)} apta(s), {len(blocked)} bloqueada(s)).", None, len(pending) + len(blocked))
        next_url = urljoin(next_url, link)
    raise BMAServiceError("Lista AbrirOTRonda excedeu o limite de paginação.")


def coletar_ativos(driver, timeout: int, progress=None) -> list[dict]:
    if progress:
        progress("sharepoint", "Conferindo ativos NF no SharePoint. Conclua o login corporativo se solicitado.", None, None)
    try:
        driver.get(LIST_URL)
    except TimeoutException:
        pass
    try:
        WebDriverWait(driver, timeout).until(
            lambda browser: browser.current_url.startswith(SITE + "/")
        )
    except TimeoutException as exc:
        raise BMAServiceError("Não foi possível autenticar no SharePoint. O cadastro anterior foi preservado.") from exc
    next_url = SITE + "/_api/web/lists/getbytitle('ListaFuncionario')/items?$select=ID,Nome,Matr_x00ed_cula&$top=5000"
    rows = []
    visited = set()
    for _ in range(100):
        if next_url in visited or not next_url.startswith(SITE + "/_api/"):
            raise BMAServiceError("Paginação inválida da lista de funcionários NF.")
        visited.add(next_url)
        result = driver.execute_async_script("""
            const url=arguments[0], done=arguments[arguments.length-1];
            fetch(url, {credentials:"same-origin",headers:{Accept:"application/json;odata=nometadata"}})
              .then(async response => {
                if (!response.ok) { done({error:"SharePoint HTTP "+response.status}); return; }
                done({data:await response.json()});
              }).catch(error=>done({error:String(error)}));
        """, next_url)
        if not isinstance(result, dict):
            raise BMAServiceError("Falha ao consultar SharePoint: resposta inválida.")
        if result.get("error"):
            raise BMAServiceError(f"Falha ao consultar SharePoint: {result['error']}")
        payload = result.get("data", {})
        values = payload.get("value")
        if not isinstance(values, list):
            raise BMAServiceError("Resposta SharePoint sem lista de funcionários.")
        for row in values:
            if not isinstance(row, dict) or not row.get("ID") or not str(row.get("Nome") or "").strip():
                raise BMAServiceError("Funcionário SharePoint sem ID ou nome. Revise a lista.")
            rows.append({"id": int(row["ID"]), "nome": str(row["Nome"]).strip(),
                         "matricula": str(row.get("Matr_x00ed_cula") or "").strip()})
        link = payload.get("@odata.nextLink") or payload.get("odata.nextLink")
        if not link:
            if not rows or len({r["id"] for r in rows}) != len(rows):
                raise BMAServiceError("Lista NF vazia ou com IDs duplicados; cadastro anterior preservado.")
            return rows
        next_url = urljoin(next_url, link)
        if urlsplit(next_url).netloc != urlsplit(SITE).netloc:
            raise BMAServiceError("Origem inválida na paginação SharePoint.")
    raise BMAServiceError("Lista SharePoint excedeu o limite de paginação.")
