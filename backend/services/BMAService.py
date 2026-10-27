"""Coleta ordens do Maximo usando a sessão autenticada do Firefox."""

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


BMA_QUICKREP_URL = (
    "https://workspace-ui.manage.rbmanca4.rosa-maximo-prod.aws.michelin.com/"
    "maximo/oslc/graphite/manage-shell/index.html?event=loadapp&value=quickrep#/main"
)
PAGE_SIZE = 1000
MAX_PAGES = 1000
# Status que não são baixados do BMA para reduzir o volume gravado no SQLite.
EXCLUDED_STATUSES = ("CAN", "CLOSE", "COMP", "HISTEDIT")
# Campos de planejamento validados no mxwo, sem trazer todos os controles internos.
OT_FIELDS = (
    "wonum,siteid,status,status_description,description,description_longdescription,"
    "location,assetnum,reportdate,reportedby,planner,schedstart,schedfinish,actstart,"
    "actfinish,actlabhrs,estlabhrs,estdur,statusdate,changeby,changedate,"
    "targstartdate,targcompdate,worktype,maintenanceshop,origin,"
    "sneconstraint,fnlconstraint,pmduedate,pmnextduedate,pmnum,jpnum,route,crew,"
    "parent,haschildren,estintlabhrs,estoutlabhrs,interruptible,woclass,historyflag,istask,"
    "wplabor{wplaborid,craft,orgid,quantity,laborhrs,skilllevel}"
)
ProgressCallback = Callable[[str, str, int | None, int | None], None]
LABOR_FIELDS = (
    "laborcode,personid,fullname,orgid,worksite,worklocation,status,status_description,"
    "maintenanceshop,laborcraftrate{craft,skilllevel,defaultcraft}"
)


class BMAServiceError(RuntimeError):
    pass


class BMAConfigurationError(BMAServiceError):
    pass


class BMAService:
    def __init__(self) -> None:
        self.quickrep_url = os.getenv("BMA_QUICKREP_URL", BMA_QUICKREP_URL).strip()
        self.login_timeout = int(os.getenv("BMA_LOGIN_TIMEOUT", "600"))
        self.timeout = int(os.getenv("BMA_OSLC_TIMEOUT", "60"))

    def listar_ots_por_setor(
        self,
        setores: list[str],
        progress: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        records, _ = self._collect_planning(setores, progress, include_labor=False)
        return records

    def coletar_planejamento(
        self, setores: list[str], progress: ProgressCallback | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return self._collect_planning(setores, progress, include_labor=True)

    def atualizar_mao_de_obra(self, verificar_nf: bool, progress: ProgressCallback | None = None):
        from .nf_workforce import coletar_ativos

        driver = self._create_browser()
        try:
            driver.set_page_load_timeout(self.timeout)
            driver.set_script_timeout(self.timeout)
            self._report(progress, "autenticacao", "Atualizando mão de obra. Conclua o login/MFA no Firefox.")
            driver.get(self.quickrep_url)
            self._wait_for_quickrep(driver, progress)
            labor = self._collect_labor(driver, progress)
            roster = coletar_ativos(driver, self.login_timeout, progress) if verificar_nf else None
            return labor, roster
        finally:
            driver.quit()

    def _collect_planning(
        self, setores: list[str], progress: ProgressCallback | None, *, include_labor: bool,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        selected_sectors = list(dict.fromkeys(setores or []))
        if not selected_sectors or len(selected_sectors) > 28 or any(
            not re.fullmatch(r"[A-Za-z0-9-]+", setor)
            for setor in selected_sectors
        ):
            raise BMAServiceError("Um ou mais códigos de setor são inválidos.")
        selected_sectors = [sector.upper() for sector in selected_sectors]

        self._report(progress, "navegador", "Acessando o BMA em segundo plano.")
        driver = self._create_browser(headless=True)
        records: list[dict[str, Any]] = []
        try:
            self._report(progress, "quickrep", "Abrindo Relatório rápido do BMA.")
            driver.set_page_load_timeout(self.timeout)
            try:
                driver.get(self.quickrep_url)
            except TimeoutException:
                self._report(
                    progress,
                    "quickrep",
                    "A navegação excedeu o tempo de carga; verificando se o Quickrep abriu parcialmente.",
                )
            self._wait_for_quickrep(driver, progress)
            self._report(progress, "oslc", "Sessão Quickrep pronta; iniciando consulta OSLC.")
            next_url = self._initial_query_url(selected_sectors)
            visited_urls: set[str] = set()
            origin = urlsplit(self.quickrep_url)

            for page_number in range(1, MAX_PAGES + 1):
                if next_url in visited_urls:
                    raise BMAServiceError("O BMA retornou um ciclo na paginação OSLC.")
                visited_urls.add(next_url)
                self._report(
                    progress,
                    "oslc",
                    f"Consultando página {page_number} de OTs no Maximo.",
                    page=page_number,
                    orders=len(records),
                )
                payload = self._fetch_payload(driver, next_url, progress)
                members = payload.get("member", [])
                if not isinstance(members, list):
                    raise BMAServiceError("Resposta OSLC inválida: lista de OTs ausente.")

                for record in members:
                    if not isinstance(record, dict):
                        continue
                    if self._matches_scope(record, selected_sectors):
                        self._complete_planned_labor(driver, record, progress)
                        records.append(record)
                self._report(
                    progress,
                    "oslc",
                    f"Página {page_number} recebida; {len(members)} linhas lidas, "
                    f"{len(records)} OTs dentro do escopo.",
                    page=page_number,
                    orders=len(records),
                )

                response_info = payload.get("responseInfo")
                response_info = response_info if isinstance(response_info, dict) else {}
                next_page = response_info.get("nextPage") or payload.get("nextPage")
                if isinstance(next_page, dict):
                    next_page = next_page.get("href")
                if not next_page:
                    if len(members) >= PAGE_SIZE:
                        raise BMAServiceError(
                            "O BMA retornou uma página cheia sem link para a próxima; "
                            "a coleta foi interrompida para não salvar resultados incompletos."
                        )
                    self._report(
                        progress,
                        "oslc_concluido",
                        f"Leitura OSLC concluída: {len(records)} OTs encontradas.",
                        page=page_number,
                        orders=len(records),
                    )
                    self._collect_children(driver, records, progress)
                    labor = self._collect_labor(driver, progress) if include_labor else []
                    return records, labor

                next_url = self._normalize_next_page(next_url, str(next_page), origin)

            raise BMAServiceError("A paginação do BMA excedeu o limite de segurança.")
        finally:
            try:
                driver.quit()
            except WebDriverException:
                pass

    def _collect_labor(
        self, driver, progress: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        query = urlencode({
            "lean": "1", "oslc.pageSize": str(PAGE_SIZE), "oslc.paging": "true",
            "oslc.select": LABOR_FIELDS,
            "oslc.where": 'worksite="RES" and status="ACTIVE"',
        })
        next_url = f"/maximo/oslc/os/mxlabor?{query}"
        origin = urlsplit(self.quickrep_url)
        visited: set[str] = set()
        records: dict[tuple[str, str], dict[str, Any]] = {}
        for page in range(1, MAX_PAGES + 1):
            if next_url in visited:
                raise BMAServiceError("Ciclo na paginação de mão de obra do BMA.")
            visited.add(next_url)
            self._report(progress, "mao_de_obra", f"Consultando mão de obra ativa de RES: página {page}.")
            payload = self._fetch_payload(driver, next_url, progress)
            members = payload.get("member")
            if not isinstance(members, list):
                raise BMAServiceError("Resposta inválida na consulta de mão de obra.")
            for record in members:
                if not isinstance(record, dict) or (
                    record.get("worksite") != "RES" or record.get("status") != "ACTIVE"
                    or not record.get("laborcode") or not record.get("orgid")
                ):
                    raise BMAServiceError("O BMA retornou mão de obra inválida ou fora de RES/ACTIVE.")
                records[(record["orgid"], record["laborcode"])] = record
            info = payload.get("responseInfo") or {}
            if not isinstance(info, dict):
                raise BMAServiceError("Paginação inválida na consulta de mão de obra.")
            link = info.get("nextPage") or payload.get("nextPage")
            if isinstance(link, dict):
                link = link.get("href")
            if not link:
                if len(members) >= PAGE_SIZE:
                    raise BMAServiceError("Página cheia de mão de obra sem continuação.")
                self._report(
                    progress, "mao_de_obra",
                    f"Cadastro de RES coletado: {len(records)} profissionais ativos.",
                )
                return list(records.values())
            next_url = self._normalize_next_page(next_url, str(link), origin)
        raise BMAServiceError("Paginação de mão de obra excedeu o limite de segurança.")

    def _collect_children(self, driver, records, progress=None) -> None:
        parents = {
            record["wonum"]: record
            for record in records
            if record.get("haschildren") in (True, 1, "1")
        }
        for record in records:
            record["children"] = []
        numbers = list(parents)
        origin = urlsplit(self.quickrep_url)
        for offset in range(0, len(numbers), 40):
            batch = numbers[offset:offset + 40]
            if any(not re.fullmatch(r"[A-Za-z0-9-]+", number) for number in batch):
                raise BMAServiceError("O BMA retornou um número de OT inválido para consultar filhas.")
            query = urlencode({
                "lean": "1",
                "oslc.pageSize": str(PAGE_SIZE),
                "oslc.paging": "true",
                "oslc.select": OT_FIELDS,
                "oslc.where": 'siteid="RES" and parent in ['
                + ",".join(f'"{number}"' for number in batch) + "]",
            })
            next_url = f"/maximo/oslc/os/mxwo?{query}"
            visited: set[str] = set()
            seen: set[tuple[str, str]] = set()
            for page in range(1, MAX_PAGES + 1):
                if next_url in visited:
                    raise BMAServiceError("O BMA retornou um ciclo na paginação das OTs filhas.")
                visited.add(next_url)
                self._report(
                    progress, "filhas",
                    f"Coletando filhas e tarefas: lote {offset // 40 + 1}, página {page}.",
                    orders=len(records),
                )
                payload = self._fetch_payload(driver, next_url, progress)
                members = payload.get("member")
                if not isinstance(members, list):
                    raise BMAServiceError("Resposta OSLC inválida na consulta de OTs filhas.")
                for child in members:
                    if not isinstance(child, dict):
                        raise BMAServiceError("O BMA retornou uma OT filha inválida.")
                    parent = child.get("parent")
                    wonum = child.get("wonum")
                    if parent not in batch or not isinstance(wonum, str) or child.get("siteid") != "RES":
                        raise BMAServiceError("O BMA retornou uma OT filha fora do escopo solicitado.")
                    key = (parent, wonum)
                    if key not in seen:
                        self._complete_planned_labor(driver, child, progress)
                        parents[parent]["children"].append(child)
                        seen.add(key)
                info = payload.get("responseInfo") or {}
                link = info.get("nextPage") or payload.get("nextPage")
                if isinstance(link, dict):
                    link = link.get("href")
                if not link:
                    if len(members) >= PAGE_SIZE:
                        raise BMAServiceError("Página cheia de OTs filhas sem link de continuação.")
                    break
                next_url = self._normalize_next_page(next_url, str(link), origin)
            else:
                raise BMAServiceError("A paginação das OTs filhas excedeu o limite de segurança.")

    def _complete_planned_labor(self, driver, record, progress=None) -> None:
        rows = record.get("wplabor", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BMAServiceError("Mão de obra planejada da OT retornada em formato inválido.")
        rows = list(rows)
        info = record.get("wplabor_collectionref", {})
        info = info if isinstance(info, dict) else {}
        response_info = info.get("responseInfo", {})
        response_info = response_info if isinstance(response_info, dict) else {}
        link = info.get("nextPage") or response_info.get("nextPage")
        visited = set()
        for _ in range(MAX_PAGES):
            if not link:
                record["wplabor"] = rows
                return
            if isinstance(link, dict):
                link = link.get("href")
            if not isinstance(link, str):
                raise BMAServiceError("Paginação inválida na mão de obra planejada.")
            url = self._normalize_next_page("", link, urlsplit(self.quickrep_url))
            if url in visited:
                raise BMAServiceError("Ciclo na paginação da mão de obra planejada.")
            visited.add(url)
            payload = self._fetch_payload(driver, url, progress)
            page = payload.get("member")
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise BMAServiceError("Página inválida de mão de obra planejada.")
            rows.extend(page)
            info = payload.get("responseInfo") or {}
            link = info.get("nextPage") or payload.get("nextPage")
        raise BMAServiceError("Paginação de mão de obra planejada excedeu o limite de segurança.")

    def _create_browser(self, *, page_load_strategy: str = "normal", headless: bool = False):
        options = webdriver.FirefoxOptions()
        options.page_load_strategy = page_load_strategy
        if headless:
            options.add_argument("-headless")
        options.add_argument("-width=1400")
        options.add_argument("-height=900")
        firefox_binary = os.getenv("BMA_FIREFOX_BINARY", "").strip()
        if firefox_binary:
            options.binary_location = firefox_binary

        profile_dir = self._browser_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.profile = str(profile_dir)
        options.set_preference(
            "network.negotiate-auth.trusted-uris",
            "login-fed.michelin.com,workspace-ui.manage.rbmanca4.rosa-maximo-prod.aws.michelin.com",
        )
        options.set_preference(
            "network.automatic-ntlm-auth.trusted-uris",
            "login-fed.michelin.com,workspace-ui.manage.rbmanca4.rosa-maximo-prod.aws.michelin.com",
        )

        try:
            if not firefox_binary and not shutil.which("firefox"):
                candidates = (
                    Path(os.getenv("LOCALAPPDATA", Path.home())) / "Mozilla Firefox" / "firefox.exe",
                    Path(os.getenv("PROGRAMFILES", "C:/Program Files"))
                    / "Mozilla Firefox" / "firefox.exe",
                    Path(os.getenv("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
                    / "Mozilla Firefox" / "firefox.exe",
                )
                binary = next((candidate for candidate in candidates if candidate.is_file()), None)
                if binary:
                    options.binary_location = str(binary)
            return webdriver.Firefox(options=options)
        except WebDriverException as exc:
            raise BMAConfigurationError(
                "Não foi possível abrir o Firefox para acessar o BMA. "
                "Verifique se o Firefox está instalado e se o Selenium Manager pode iniciar o driver."
            ) from exc

    @staticmethod
    def _browser_profile_dir() -> Path:
        local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home()))
        return local_app_data / "BMA_Automacao" / "FirefoxProfile"

    def clear_browser_cache_and_history(self) -> None:
        profile_dir = self._browser_profile_dir()
        for directory in ("cache2", "startupCache", "thumbnails", "storage", "sessionstore-backups"):
            shutil.rmtree(profile_dir / directory, ignore_errors=True)
        for filename in (
            "places.sqlite", "places.sqlite-shm", "places.sqlite-wal",
            "cookies.sqlite", "cookies.sqlite-shm", "cookies.sqlite-wal",
            "storage.sqlite", "webappsstore.sqlite", "formhistory.sqlite",
            "sessionstore.jsonlz4",
        ):
            (profile_dir / filename).unlink(missing_ok=True)

    @staticmethod
    def _report(
        progress: ProgressCallback | None,
        stage: str,
        message: str,
        *,
        page: int | None = None,
        orders: int | None = None,
    ) -> None:
        if progress:
            progress(stage, message, page, orders)

    def _wait_for_quickrep(
        self,
        driver,
        progress: ProgressCallback | None = None,
    ) -> None:
        driver.set_page_load_timeout(self.timeout)
        driver.set_script_timeout(self.timeout)
        login_clicked = False

        def quickrep_ready(current_driver):
            nonlocal login_clicked
            current_driver.switch_to.default_content()
            if self._find_quick_search(current_driver):
                return True

            page_url = current_driver.current_url
            if not login_clicked and (
                "auth.rbmanca4" in page_url or "login-fed.michelin.com" in page_url
            ):
                login_button = self._find_login_button(current_driver)
                if login_button:
                    self._report(
                        progress,
                        "autenticacao",
                        "Acionando o login corporativo do BMA em segundo plano.",
                    )
                    login_button.click()
                    login_clicked = True
            return False

        try:
            self._report(
                progress,
                "autenticacao",
                "Validando a sessão do BMA em segundo plano.",
            )
            WebDriverWait(driver, self.login_timeout, poll_frequency=0.5).until(quickrep_ready)
            self._report(progress, "autenticado", "Relatório rápido pronto para consulta.")
        except TimeoutException as exc:
            raise BMAServiceError(
                "O BMA exige autenticação interativa ou MFA. A coleta em segundo plano "
                "não pode concluir essa etapa; use uma integração autorizada ou faça "
                "a autenticação manual antes de tentar novamente."
            ) from exc

    @staticmethod
    def _find_login_button(driver):
        elements = driver.find_elements(
            By.XPATH, "//*[self::button or @role='button' or (self::input and @type='submit')]",
        )
        for element in elements:
            label = " ".join((
                element.text or "",
                element.get_attribute("aria-label") or "",
                element.get_attribute("value") or "",
            )).strip().casefold()
            if label == "efetuar login" and element.is_displayed() and element.is_enabled():
                return element
        return None

    @classmethod
    def _find_quick_search(cls, driver, depth: int = 0):
        matches = driver.find_elements(By.CSS_SELECTOR, "input[aria-label='Find Ordem de Trabalho']")
        if any(element.is_displayed() and element.is_enabled() for element in matches):
            return True
        if depth >= 8:
            return False

        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
            switched = False
            try:
                driver.switch_to.frame(frame)
                switched = True
                if cls._find_quick_search(driver, depth + 1):
                    return True
            except WebDriverException:
                continue
            finally:
                if switched:
                    try:
                        driver.switch_to.parent_frame()
                    except WebDriverException:
                        driver.switch_to.default_content()
        return False

    @staticmethod
    def _initial_query_url(setores: list[str]) -> str:
        sector_filter = "maintenanceshop in [" + ",".join(
            f'"{setor}"' for setor in setores
        ) + "]"
        status_filter = " and ".join(
            f'status!="{status}"' for status in EXCLUDED_STATUSES
        )
        query = urlencode({
            "lean": "1",
            "oslc.pageSize": str(PAGE_SIZE),
            "oslc.paging": "true",
            "oslc.select": OT_FIELDS,
            "oslc.where": f"{sector_filter} and {status_filter}",
        })
        return f"/maximo/oslc/os/mxwo?{query}"

    @staticmethod
    def _matches_scope(
        record: dict[str, Any],
        setores: list[str],
    ) -> bool:
        def value(key: str) -> str:
            current = record.get(key, "")
            if isinstance(current, dict):
                current = current.get("value", current.get("_value", ""))
            return str(current or "").strip().upper()

        return (
            value("wonum").startswith("RES")
            and value("status") not in EXCLUDED_STATUSES
            and value("maintenanceshop") in {setor.upper() for setor in setores}
            and value("siteid") in {"", "RES"}
            and value("historyflag") not in {"1", "TRUE", "Y"}
            and value("istask") not in {"1", "TRUE", "Y"}
            and value("woclass") in {"", "WORKORDER", "ACTIVITY"}
        )

    @staticmethod
    def _normalize_next_page(current_url: str, next_page: str, origin) -> str:
        site = f"{origin.scheme}://{origin.netloc}/"
        if next_page.startswith(("/maximo/", "/oslc/")) or "://" in next_page:
            base_url = site
        else:
            base_url = site + "maximo/"
        parsed = urlsplit(urljoin(base_url, next_page))
        if (parsed.scheme.casefold(), parsed.netloc.casefold()) != (
            origin.scheme.casefold(), origin.netloc.casefold()
        ):
            raise BMAServiceError("O Maximo retornou um link de paginação para outra origem.")
        if parsed.path.startswith("/oslc/"):
            parsed = parsed._replace(path="/maximo" + parsed.path)
        if not parsed.path.startswith("/maximo/oslc/"):
            raise BMAServiceError("O Maximo retornou um link fora da API OSLC.")
        return urlunsplit(("", "", parsed.path, parsed.query, ""))

    def _fetch_payload(
        self,
        driver,
        url: str,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        authentication_recovered = False
        for delay in (0, 1, 2, 4):
            if delay:
                self._report(
                    progress,
                    "retry",
                    f"Nova tentativa da consulta OSLC após {delay}s.",
                )
                time.sleep(delay)
            try:
                try:
                    result = driver.execute_async_script(
                        """
                        const url = arguments[0];
                        const finish = arguments[arguments.length - 1];
                        fetch(url, { credentials: "include", headers: { Accept: "application/json" } })
                          .then(async response => ({ status: response.status, body: await response.text() }))
                          .then(finish)
                          .catch(error => finish({ status: 0, error: String(error) }));
                        """,
                        url,
                    )
                except (TimeoutException, WebDriverException) as exc:
                    self._report(
                        progress,
                        "retry",
                        f"A consulta OSLC falhou ({type(exc).__name__}); tentando novamente.",
                    )
                    continue
            except (TimeoutException, WebDriverException) as exc:
                self._report(
                    progress,
                    "retry",
                    f"A página OSLC demorou ou falhou ({type(exc).__name__}); tentando novamente.",
                )
                continue
            if not isinstance(result, dict):
                continue
            status = result.get("status")
            if status in {401, 403} and not authentication_recovered:
                authentication_recovered = True
                driver.get(self.quickrep_url)
                self._wait_for_quickrep(driver, progress)
                continue
            if status == 200:
                try:
                    payload = json.loads(result.get("body", ""))
                except json.JSONDecodeError as exc:
                    if not authentication_recovered and "<html" in result.get("body", "").lower():
                        authentication_recovered = True
                        driver.get(self.quickrep_url)
                        self._wait_for_quickrep(driver, progress)
                        continue
                    raise BMAServiceError("O Maximo retornou JSON inválido.") from exc
                if isinstance(payload, dict) and not payload.get("Error"):
                    return payload
                raise BMAServiceError("O Maximo retornou uma resposta OSLC inválida.")
            if status not in {0, 429, 500, 502, 503, 504}:
                detail = str(result.get("body") or result.get("error") or "")
                try:
                    detail = json.loads(detail).get("Error", {}).get("message", detail)
                except (TypeError, ValueError, AttributeError):
                    pass
                raise BMAServiceError(f"Falha OSLC no Maximo (HTTP {status}): {detail[:300]}")
        raise BMAServiceError("Não foi possível consultar as OTs no Maximo após novas tentativas.")

    def criar_ot(self, dados_json):
        """Cria Ordens de Trabalho no BMA a partir do JSON processado.

        Implementação futura: autenticação, navegação Selenium e
        persistência do Nº OT BMA gerado de volta na planilha/SharePoint.
        """
        registros = dados_json if isinstance(dados_json, list) else [dados_json]
        quantidade = len(registros)
        if quantidade == 0:
            raise ValueError("Nenhum registro selecionado para criar OT.")
        return {
            "status": "solicitado",
            "quantidade": quantidade,
            "mensagem": f"Solicitação registrada para {quantidade} OT(s). A criação automática no BMA ainda não está ativa.",
        }
