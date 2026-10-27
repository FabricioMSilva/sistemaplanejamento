"""Read-only Selenium monitor for the Maximo Work Order Tracking page."""

from copy import deepcopy
from datetime import date, datetime
from threading import Event, Lock, Thread
from time import monotonic, sleep
from uuid import uuid4

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from services.BMAService import BMAService, BMAServiceError

WOTRACK_URL = (
    "https://workspace.manage.rbmanca4.rosa-maximo-prod.aws.michelin.com/"
    "maximo/oslc/graphite/manage-shell/index.html?event=loadapp&value=wotrack#/main"
)


class BmaPageMonitor:
    def __init__(self):
        self._lock = Lock()
        self._browser_lock = Lock()
        self._sessions = {}

    def start(self, orders: list[dict]):
        if not isinstance(orders, list) or not orders:
            raise BMAServiceError("Selecione um planejamento de OT válido.")
        if len(orders) > 1:
            raise BMAServiceError("Envie uma OT por vez para o rastreamento do BMA.")
        selected = []
        normalized_orders = []
        for order in orders:
            if not isinstance(order, dict):
                raise BMAServiceError("Planejamento de OT inválido.")
            wonum = str(order.get("wonum", "")).strip()
            siteid = str(order.get("siteid", "")).strip()
            specialty = str(order.get("specialty", "")).strip()
            try:
                planned_start = datetime.fromisoformat(order.get("planned_start", ""))
                planned_finish = datetime.fromisoformat(order.get("planned_finish", ""))
            except (TypeError, ValueError) as exc:
                raise BMAServiceError(f"Datas planejadas inválidas para a OT {wonum}.") from exc
            assignments = order.get("assignments")
            if (
                not wonum or not all(character.isalnum() or character == "-" for character in wonum)
                or not siteid or planned_start >= planned_finish
                or not isinstance(assignments, list) or not assignments or len(assignments) > 500
            ):
                raise BMAServiceError(f"Planejamento incompleto ou inválido para a OT {wonum or 'sem número'}.")
            normalized_assignments = []
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    raise BMAServiceError(f"Atribuição inválida para a OT {wonum}.")
                try:
                    assignment_day = date.fromisoformat(assignment.get("dia", ""))
                    hours = float(assignment.get("horas", 0))
                except (TypeError, ValueError) as exc:
                    raise BMAServiceError(f"Data ou horas inválidas na OT {wonum}.") from exc
                laborcode = str(assignment.get("laborcode", "")).strip()
                if (
                    not laborcode or not all(character.isalnum() or character == "-" for character in laborcode)
                    or not 0 < hours <= 24 or not planned_start.date() <= assignment_day <= planned_finish.date()
                ):
                    raise BMAServiceError(f"Mão de obra ou horas inválidas na OT {wonum}.")
                normalized_assignments.append({**assignment, "laborcode": laborcode, "horas": hours})
            selected.append(wonum)
            normalized_orders.append({
                **order,
                "wonum": wonum,
                "siteid": siteid,
                "specialty": specialty,
                "assignments": normalized_assignments,
            })
        if len(set(selected)) != len(selected):
            raise BMAServiceError("A lista contém OTs duplicadas.")
        drivers_to_close = []
        with self._lock:
            for session in self._sessions.values():
                if session["state"]["status"] in {"starting", "monitoring", "stopping"}:
                    session["stop"].set()
                    if session.get("driver"):
                        drivers_to_close.append(session["driver"])
                    session["state"].update(
                        status="stopping",
                        message="Substituindo a sessão BMA pela nova seleção de OTs.",
                    )
            monitor_id = uuid4().hex
            session = {
                "state": {
                    "monitor_id": monitor_id,
                    "status": "starting",
                    "message": "Iniciando Firefox e abrindo Rastrear Ordem de Trabalho.",
                    "fields": [],
                    "elapsed_seconds": 0,
                    "stage": "starting",
                    "selected_wonums": selected,
                    "opened_wonum": None,
                    "page_url": "",
                    "page_title": "",
                },
                "stop": Event(),
                "driver": None,
                "orders": normalized_orders,
            }
            self._sessions[monitor_id] = session
        for driver in drivers_to_close:
            Thread(target=self._close_browser, args=(driver,), daemon=True).start()
        Thread(target=self._run, args=(monitor_id, selected), daemon=True).start()
        return {"monitor_id": monitor_id}

    @staticmethod
    def _close_browser(driver):
        try:
            driver.quit()
        except WebDriverException:
            pass

    def get(self, monitor_id: str):
        with self._lock:
            session = self._sessions.get(monitor_id)
            return deepcopy(session["state"]) if session else None

    def stop(self, monitor_id: str):
        with self._lock:
            session = self._sessions.get(monitor_id)
            if not session:
                return None
            session["stop"].set()
            session["state"]["status"] = "stopping"
            session["state"]["message"] = "Encerrando o monitor e a sessão Firefox."
            return deepcopy(session["state"])

    def _update(self, monitor_id: str, **values):
        with self._lock:
            session = self._sessions.get(monitor_id)
            if session:
                session["state"].update(values)

    @staticmethod
    def _visible_fields(driver, *, frame_path="principal", depth=0):
        fields = driver.execute_script("""
            return Array.from(document.querySelectorAll('input, textarea, select, button'))
              .filter((element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none'
                  && style.visibility !== 'hidden' && !element.closest('[aria-hidden="true"]');
              })
              .map((element) => {
                const labels = element.labels ? Array.from(element.labels)
                  .map((label) => label.innerText.trim()).filter(Boolean).join(' ') : '';
                                const labelledBy = (element.getAttribute('aria-labelledby') || '')
                                    .split(/\\s+/).filter(Boolean)
                                    .map((id) => document.getElementById(id)?.innerText.trim() || '')
                                    .filter(Boolean).join(' ');
                return {
                  tag: element.tagName.toLowerCase(),
                  id: element.id || '',
                  name: element.getAttribute('name') || '',
                  label: element.getAttribute('aria-label') || element.getAttribute('placeholder')
                                        || labels || labelledBy || element.getAttribute('title') || element.id || element.tagName.toLowerCase(),
                  type: element.getAttribute('type') || '',
                  disabled: Boolean(element.disabled),
                };
            });
        """)
        fields = [{**field, "frame": frame_path} for field in fields]
        if depth >= 8:
            return fields
        for index, frame in enumerate(driver.find_elements("tag name", "iframe")):
            switched = False
            try:
                driver.switch_to.frame(frame)
                switched = True
                fields.extend(BmaPageMonitor._visible_fields(
                    driver, frame_path=f"{frame_path}/iframe[{index}]", depth=depth + 1,
                ))
            except WebDriverException:
                continue
            finally:
                if switched:
                    try:
                        driver.switch_to.parent_frame()
                    except WebDriverException:
                        driver.switch_to.default_content()
        return fields

    @staticmethod
    def _find_order_filter(driver, depth=0):
        quicksearch_inputs = driver.find_elements(By.ID, "quicksearch")
        column_filters = driver.find_elements(By.CSS_SELECTOR, "input.tablefilterfield")
        labeled_inputs = driver.find_elements(
            By.CSS_SELECTOR, "input[aria-label], input[placeholder], input[title]",
        )
        column_filter_ids = {element.id for element in column_filters}
        candidates = quicksearch_inputs + column_filters + [
            element for element in labeled_inputs
            if element.id not in column_filter_ids and element.id != "quicksearch"
        ]
        for element in candidates:
            if element.id == "quicksearch":
                if element.is_displayed() and element.is_enabled():
                    return element
                continue
            label = driver.execute_script("""
                const input = arguments[0];
                const ids = (input.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
                const labelled = ids.map((id) => document.getElementById(id)?.innerText || '').join(' ');
                const labels = input.labels ? Array.from(input.labels).map((item) => item.innerText || '').join(' ') : '';
                return [labelled, labels, input.getAttribute('aria-label'), input.getAttribute('placeholder'),
                input.getAttribute('title'), input.id, input.getAttribute('name'), input.className]
                  .filter(Boolean).join(' ').trim();
            """, element)
            normalized_label = str(label).casefold()
            if "find navigation" in normalized_label:
                continue
            if any(term in normalized_label for term in (
                "ordem de trabalho", "work order", "número da ot", "numero da ot", "wonum",
            )):
                if element.is_displayed() and element.is_enabled():
                    return element
        if depth >= 8:
            return None
        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                driver.switch_to.frame(frame)
                element = BmaPageMonitor._find_order_filter(driver, depth + 1)
                if element:
                    return element
            except WebDriverException:
                continue
            finally:
                try:
                    driver.switch_to.parent_frame()
                except WebDriverException:
                    driver.switch_to.default_content()
        return None

    @staticmethod
    def _find_order_link(driver, wonum: str, depth=0):
        links = driver.find_elements(
            By.XPATH,
            f"//*[self::a or @role='link' or self::button or @onclick or @tabindex]"
            f"[normalize-space(.)='{wonum}']",
        )
        for link in links:
            if link.is_displayed() and link.is_enabled():
                return link
        text_nodes = driver.find_elements(By.XPATH, f"//*[normalize-space(text())='{wonum}']")
        for node in text_nodes:
            clickable = node.find_elements(
                By.XPATH,
                "./ancestor-or-self::*[self::a or @role='link' or self::button or @onclick or @tabindex][1]",
            )
            if clickable and clickable[0].is_displayed() and clickable[0].is_enabled():
                return clickable[0]
        if depth >= 8:
            return None
        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                driver.switch_to.frame(frame)
                link = BmaPageMonitor._find_order_link(driver, wonum, depth + 1)
                if link:
                    return link
            except WebDriverException:
                continue
            finally:
                try:
                    driver.switch_to.parent_frame()
                except WebDriverException:
                    driver.switch_to.default_content()
        return None

    @staticmethod
    def _open_work_order_app(driver):
        app_selector = (
            "//*[self::a or @role='link' or @role='menuitem' or self::button]"
            "[normalize-space(.)='Work Order Tracking' or normalize-space(.)='Rastrear Ordem de Trabalho']"
        )
        menu_selector = (
            "//*[self::button or @role='button'][normalize-space(.)='Open menu' "
            "or @aria-label='Open menu' or normalize-space(.)='Menu']"
        )
        recent_apps_selector = (
            "//*[self::button or @role='button'][normalize-space(.)='Recent applications']"
        )
        work_orders_selector = (
            "//*[self::button or @role='button'][normalize-space(.)='Ordens de Trabalho']"
        )

        def find_visible(selector):
            return next((element for element in driver.find_elements(By.XPATH, selector)
                         if element.is_displayed() and element.is_enabled()), None)

        app = find_visible(app_selector)
        if app:
            app.click()
            return True
        menu = find_visible(menu_selector)
        if menu:
            menu.click()

        recent_apps = find_visible(recent_apps_selector)
        if recent_apps and recent_apps.get_attribute("aria-expanded") != "true":
            recent_apps.click()
        app = find_visible(app_selector)
        if app:
            app.click()
            return True

        work_orders = find_visible(work_orders_selector)
        if work_orders and work_orders.get_attribute("aria-expanded") != "true":
            work_orders.click()
        app = find_visible(app_selector)
        if not app:
            return False
        app.click()
        return True

    @staticmethod
    def _find_login_button(driver):
        for element in driver.find_elements(
            By.XPATH, "//*[self::button or @role='button' or (self::input and @type='submit')]",
        ):
            label = " ".join((element.text or "", element.get_attribute("aria-label") or "",
                              element.get_attribute("value") or "")).strip().casefold()
            if label == "efetuar login" and element.is_displayed() and element.is_enabled():
                return element
        return None

    def _run(self, monitor_id: str, wonums: list[str]):
        driver = None
        started_at = monotonic()
        tracking_wait_started_at = None
        self._browser_lock.acquire()
        try:
            with self._lock:
                session = self._sessions.get(monitor_id)
                if not session or session["stop"].is_set():
                    return
            service = BMAService()
            self._update(monitor_id, message="Iniciando monitor BMA em segundo plano.")
            service.clear_browser_cache_and_history()
            driver = service._create_browser(page_load_strategy="eager", headless=False)
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session:
                    session["driver"] = driver
            driver.set_page_load_timeout(service.timeout)
            self._update(monitor_id, status="monitoring", message=(
                "Firefox aberto para autenticação do BMA; aguardando os controles do Maximo."
            ))
            try:
                driver.get(WOTRACK_URL)
            except TimeoutException:
                self._update(monitor_id, stage="waiting_page", message=(
                    "Maximo ainda carregando após o limite de navegação; procurando controles disponíveis."
                ))

            query_submitted = False
            tracking_ready = False
            direct_navigation_attempted = False
            app_navigation_attempted = False
            opened_wonum = None
            login_clicked = False
            while True:
                with self._lock:
                    session = self._sessions.get(monitor_id)
                    if not session or session["stop"].is_set():
                        break
                try:
                    driver.switch_to.default_content()
                except WebDriverException:
                    sleep(1)
                    continue
                try:
                    fields = self._visible_fields(driver)
                except WebDriverException:
                    fields = []
                page_url = driver.current_url
                page_title = driver.title
                if "auth.rbmanca4" in page_url or "login-fed.michelin.com" in page_url:
                    tracking_ready = False
                    tracking_wait_started_at = None
                    if not login_clicked:
                        try:
                            login_button = self._find_login_button(driver)
                        except WebDriverException:
                            login_button = None
                        if login_button:
                            self._update(monitor_id, stage="authenticating", message="Acionando o login do BMA.")
                            login_button.click()
                            login_clicked = True
                    self._update(
                        monitor_id, status="monitoring", stage="authenticating",
                        message="Conclua o login/MFA na janela do Firefox; o monitor continuará após o redirecionamento.",
                        fields=fields, elapsed_seconds=round(monotonic() - started_at),
                        page_url=page_url, page_title=page_title,
                    )
                    sleep(1)
                    continue
                if tracking_wait_started_at is None:
                    tracking_wait_started_at = monotonic()
                if not query_submitted:
                    tracking_input_ready = any(
                        field["tag"] == "input" and field["id"] == "quicksearch"
                        for field in fields
                    )
                    try:
                        order_filter = self._find_order_filter(driver)
                    except WebDriverException:
                        order_filter = None
                    if order_filter or tracking_input_ready:
                        tracking_ready = True
                    if order_filter:
                        try:
                            self._update(monitor_id, stage="filtering", message=(
                                f"Filtrando a OT {wonums[0]} no rastreamento do Maximo."
                            ))
                            order_filter.clear()
                            order_filter.send_keys(wonums[0], Keys.ENTER)
                            driver.switch_to.default_content()
                            query_submitted = True
                        except WebDriverException:
                            order_filter = None
                    if not query_submitted and not tracking_ready:
                        if (
                            not direct_navigation_attempted
                            and monotonic() - tracking_wait_started_at >= 10
                        ):
                            direct_navigation_attempted = True
                            tracking_wait_started_at = monotonic()
                            self._update(monitor_id, stage="opening_app", message=(
                                "Acessando diretamente o link do Rastreamento de Ordem de Trabalho."
                            ))
                            try:
                                driver.get(WOTRACK_URL)
                            except TimeoutException:
                                self._update(monitor_id, stage="waiting_page", message=(
                                    "Maximo ainda carregando o link direto; aguardando os controles do rastreamento."
                                ))
                            except WebDriverException:
                                pass
                            try:
                                driver.switch_to.default_content()
                            except WebDriverException:
                                pass
                        elif (
                            not app_navigation_attempted
                            and direct_navigation_attempted
                            and monotonic() - tracking_wait_started_at >= 10
                        ):
                            app_navigation_attempted = True
                            try:
                                app_opened = self._open_work_order_app(driver)
                            except WebDriverException:
                                app_opened = False
                            if app_opened:
                                self._update(monitor_id, stage="opening_app", message=(
                                    "Abrindo o aplicativo Work Order Tracking pelo menu do Maximo."
                                ))
                                driver.switch_to.default_content()
                if query_submitted and not opened_wonum:
                    self._update(monitor_id, stage="waiting_results", message=(
                        f"Aguardando resultados para {len(wonums)} OT(s)."
                    ))
                    for wonum in wonums:
                        driver.switch_to.default_content()
                        link = self._find_order_link(driver, wonum)
                        if link:
                            self._update(monitor_id, stage="opening_order", message=f"Abrindo a primeira OT selecionada: {wonum}.")
                            try:
                                link.click()
                            except WebDriverException:
                                try:
                                    driver.execute_script("arguments[0].click();", link)
                                except WebDriverException:
                                    continue
                            driver.switch_to.default_content()
                            opened_wonum = wonum
                            self._update(monitor_id, opened_wonum=wonum)
                            break
                search_ready = any(field["id"] == "quicksearch" for field in fields)
                self._update(
                    monitor_id,
                    status="monitoring",
                    stage=("observing_order" if opened_wonum else "waiting_filter" if not query_submitted
                           else "waiting_results"),
                    message=(f"OT {opened_wonum} aberta. Observando os campos para orientar o preenchimento."
                             if opened_wonum else "Rastreamento pronto; aguardando o campo de filtro de OT."
                             if search_ready or tracking_ready else "Página aberta; aguardando os controles de rastreamento aparecerem."),
                    fields=fields,
                    elapsed_seconds=round(monotonic() - started_at),
                    page_url=page_url,
                    page_title=page_title,
                )
                sleep(1)
        except Exception as exc:
            self._update(monitor_id, status="failed", message=f"Monitor interrompido: {exc}")
        finally:
            if driver:
                try:
                    driver.quit()
                except WebDriverException:
                    pass
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session and session["state"]["status"] != "failed":
                    session["state"].update(status="stopped", message="Monitor encerrado.")
                if session:
                    session["driver"] = None
            self._browser_lock.release()
