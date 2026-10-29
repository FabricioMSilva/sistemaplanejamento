"""Read-only Selenium monitor for the Maximo Work Order Tracking page."""

from copy import deepcopy
from datetime import date, datetime
from threading import Event, Lock, Thread
from time import monotonic, sleep
import unicodedata
from uuid import uuid4

from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from services.BMAService import BMAService, BMAServiceError
from services.bma_planning_reader import PlanningReadMixin

WOTRACK_URL = (
    "https://workspace.manage.rbmanca4.rosa-maximo-prod.aws.michelin.com/"
    "maximo/oslc/graphite/manage-shell/index.html?event=loadapp&value=wotrack#/main"
)


class BmaPageMonitor(PlanningReadMixin):
    def __init__(self):
        self._lock = Lock()
        self._browser_lock = Lock()
        self._sessions = {}

    def start(self, orders: list[dict]):
        if not isinstance(orders, list) or not orders:
            raise BMAServiceError("Selecione um planejamento de OT válido.")
        if len(orders) > 100:
            raise BMAServiceError("Selecione no máximo 100 OTs por fila.")
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
                laborcode = str(assignment.get("laborcode", "")).strip().upper()
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
                    "queue_total": len(selected),
                    "current_order_index": 0,
                    "current_wonum": None,
                    "completed_wonums": [],
                    "failed_wonum": None,
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

    def start_search(self, wonum: str):
        return self._start_read_only(wonum, "search_only")

    def start_open_order(self, wonum: str):
        return self._start_read_only(wonum, "open_order")

    def _start_read_only(self, wonum: str, mode: str):
        wonum = str(wonum or "").strip().upper()
        if not wonum or not all(character.isalnum() or character == "-" for character in wonum):
            raise BMAServiceError("Número da OT inválido.")
        drivers_to_close = []
        with self._lock:
            for session in self._sessions.values():
                if session["state"]["status"] in {"starting", "monitoring", "stopping"}:
                    session["stop"].set()
                    if session.get("driver"):
                        drivers_to_close.append(session["driver"])
                    session["state"].update(
                        status="stopping",
                        message="Substituindo a sessão BMA pela busca somente leitura.",
                    )
            monitor_id = uuid4().hex
            session = {
                "state": {
                    "monitor_id": monitor_id,
                    "mode": mode,
                    "inspection_only": True,
                    "status": "starting",
                    "message": "Abrindo Rastreamento de Ordem de Trabalho.",
                    "fields": [],
                    "elapsed_seconds": 0,
                    "stage": "starting",
                    "progress": 0,
                    "selected_wonums": [wonum],
                    "queue_total": 1,
                    "current_order_index": 0,
                    "current_wonum": wonum,
                    "completed_wonums": [],
                    "failed_wonum": None,
                    "opened_wonum": None,
                    "page_url": "",
                    "page_title": "",
                },
                "stop": Event(),
                "driver": None,
                "orders": [],
            }
            self._sessions[monitor_id] = session
        for driver in drivers_to_close:
            Thread(target=self._close_browser, args=(driver,), daemon=True).start()
        target = self._run_open_order_only if mode == "open_order" else self._run_search_only
        Thread(target=target, args=(monitor_id, wonum), daemon=True).start()
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
        if quicksearch_inputs:
            return next((element for element in quicksearch_inputs
                         if element.is_displayed() and element.is_enabled()), None)

        column_filters = driver.find_elements(By.CSS_SELECTOR, "input.tablefilterfield")
        labeled_inputs = driver.find_elements(
            By.CSS_SELECTOR, "input[aria-label], input[placeholder], input[title]",
        )
        column_filter_ids = {element.get_attribute("id") for element in column_filters}
        candidates = column_filters + [
            element for element in labeled_inputs
            if element.get_attribute("id") not in column_filter_ids
        ]
        for element in candidates:
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
            element = None
            switched = False
            try:
                driver.switch_to.frame(frame)
                switched = True
                element = BmaPageMonitor._find_order_filter(driver, depth + 1)
                if element:
                    return element
            except WebDriverException:
                continue
            finally:
                if switched and not element:
                    try:
                        driver.switch_to.parent_frame()
                    except WebDriverException:
                        driver.switch_to.default_content()
        return None

    @staticmethod
    def _submit_order_filter(order_filter, wonum):
        order_filter.click()
        order_filter.send_keys(Keys.CONTROL, "a")
        order_filter.send_keys(wonum, Keys.ENTER)

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
            link = None
            switched = False
            try:
                driver.switch_to.frame(frame)
                switched = True
                link = BmaPageMonitor._find_order_link(driver, wonum, depth + 1)
                if link:
                    return link
            except WebDriverException:
                continue
            finally:
                if switched and not link:
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

    @staticmethod
    def _switch_to_manage_frame(driver):
        driver.switch_to.default_content()
        frames = driver.find_elements(By.CSS_SELECTOR, 'iframe[name="manage-shell_Iframe"]')
        if not frames:
            frames = [frame for frame in driver.find_elements(By.TAG_NAME, "iframe")
                      if frame.get_attribute("name") == "manage-shell_Iframe"]
        if frames:
            driver.switch_to.frame(frames[0])
            return
        if not BmaPageMonitor._enter_maximo_document(driver):
            raise BMAServiceError("O frame do Maximo não foi encontrado.")

    @staticmethod
    def _enter_maximo_document(driver, depth=0):
        # Documento do Maximo = onde está o campo "Find Ordem de Trabalho" (#quicksearch).
        if driver.find_elements(By.ID, "quicksearch"):
            return True
        if depth >= 8:
            return False
        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                driver.switch_to.frame(frame)
            except WebDriverException:
                continue
            if BmaPageMonitor._enter_maximo_document(driver, depth + 1):
                return True
            driver.switch_to.parent_frame()
        return False

    @staticmethod
    def _normalize_text(value):
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        return " ".join("".join(character for character in normalized
                               if not unicodedata.combining(character)).casefold().split())

    @staticmethod
    def _find_labeled_input(driver, label):
        return driver.execute_script("""
            const normalize = (value) => String(value || '').normalize('NFD')
              .replace(/[\\u0300-\\u036f]/g, '').trim().toLocaleLowerCase();
            const wanted = normalize(arguments[0]);
            return Array.from(document.querySelectorAll('input, textarea, select'))
              .find((element) => {
                const rect = element.getBoundingClientRect();
                if (!rect.width || !rect.height || element.disabled) return false;
                const ids = (element.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
                const names = [element.getAttribute('aria-label'), element.getAttribute('placeholder'),
                  element.getAttribute('title'), ...(element.labels ? Array.from(element.labels).map((item) => item.innerText) : []),
                  ...ids.map((id) => document.getElementById(id)?.innerText || '')];
                return names.some((name) => normalize(name) === wanted);
              }) || null;
        """, label)

    # Mensagens do Maximo respondidas com OK; as demais são fechadas e interrompem a OT.
    ACCEPTED_MAXIMO_MESSAGES = {
        "BMXAA0159W",  # datas programadas posteriores à restrição de término: aplica a data do planejador
    }

    @staticmethod
    def _handle_maximo_message(driver):
        message = driver.execute_script("""
            const visible = (el) => { const r = el.getBoundingClientRect(); const s = window.getComputedStyle(el);
              return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
            const norm = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
            for (const box of document.querySelectorAll('[role=dialog],[role=alertdialog],.dijitDialog,[id^="msgbox"]')) {
              if (!visible(box)) continue;
              const text = norm(box.innerText);
              const code = text.match(/BMXAA\\d+[A-Z]/);
              if (!code) continue;
              const buttons = Array.from(box.querySelectorAll('button,[role=button]')).filter(visible);
              const find = (name) => buttons.find((b) => norm(b.innerText).toLowerCase() === name) || null;
              return { code: code[0], text: text.slice(0, 400), ok: find('ok'), close: find('fechar') || find('close') };
            }
            return null;
        """)
        if not isinstance(message, dict):
            return False
        accepted = message["code"] in BmaPageMonitor.ACCEPTED_MAXIMO_MESSAGES and message.get("ok")
        button = message.get("ok") if accepted else message.get("close") or message.get("ok")
        if button:
            button.click()
        if not accepted:
            raise BMAServiceError(f"Mensagem do BMA: {message['text']}")
        handled = getattr(driver, "_bma_messages", [])
        handled.append(f"{message['code']} respondida com OK")
        driver._bma_messages = handled
        return True

    @staticmethod
    def _wait_maximo_idle(driver, timeout=60):
        # O Maximo bloqueia a tela com overlays de espera enquanto processa; cliques nesse período são interceptados.
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            try:
                if BmaPageMonitor._handle_maximo_message(driver):
                    sleep(0.5)
                    continue
                # .wait_modal é só o fundo de janelas (workflow, mensagens); não indica carregamento.
                busy = driver.execute_script("""
                    return Array.from(document.querySelectorAll('.bx--loading-overlay')).some((element) => {
                      const rect = element.getBoundingClientRect();
                      const style = window.getComputedStyle(element);
                      return rect.width > 0 && rect.height > 0 && style.display !== 'none'
                        && style.visibility !== 'hidden' && !element.className.includes('--stop');
                    });
                """)
            except WebDriverException:
                busy = False
            if busy is not True:
                return
            sleep(0.25)
        raise BMAServiceError("O BMA ficou carregando (tela bloqueada) por tempo demais.")

    @staticmethod
    def _click_when_idle(driver, element):
        for attempt in range(5):
            BmaPageMonitor._wait_maximo_idle(driver)
            try:
                element.click()
                return
            except ElementClickInterceptedException:
                if attempt == 4:
                    raise
                sleep(0.5)

    @staticmethod
    def _click_tab(driver, label):
        wanted = BmaPageMonitor._normalize_text(label)
        BmaPageMonitor._wait_maximo_idle(driver)
        for tab in driver.find_elements(By.XPATH, "//*[@role='tab']"):
            if BmaPageMonitor._normalize_text(tab.text) == wanted and tab.is_displayed():
                BmaPageMonitor._click_when_idle(driver, tab)
                BmaPageMonitor._wait_maximo_idle(driver)
                return
        raise BMAServiceError(f"A aba {label} do Maximo não foi encontrada.")

    @staticmethod
    def _replace_input(element, value, *, select_suggestion=False):
        BmaPageMonitor._click_when_idle(element.parent, element)
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(value)
        if select_suggestion:
            element.send_keys(Keys.ENTER)
        element.send_keys(Keys.TAB)
        BmaPageMonitor._wait_maximo_idle(element.parent)

    @staticmethod
    def _find_assignment_grid(driver):
        for table in driver.find_elements(By.TAG_NAME, "table"):
            if not table.is_displayed():
                continue
            rows = table.find_elements(By.XPATH, ".//tr")
            for header in rows:
                cells = header.find_elements(By.XPATH, "./th | ./td")
                labels = [BmaPageMonitor._normalize_text(cell.text) for cell in cells]
                required = {"mao de obra", "inicio planejado", "horas"}
                if required.issubset(set(labels)):
                    columns = {label: labels.index(label) for label in required}
                    data_rows = []
                    for row in rows:
                        if row == header:
                            continue
                        row_cells = row.find_elements(By.XPATH, "./th | ./td")
                        if len(row_cells) <= max(columns.values()):
                            continue
                        if row_cells[columns["mao de obra"]].find_elements(By.TAG_NAME, "input"):
                            data_rows.append((row, row_cells))
                    return table, columns, data_rows
        raise BMAServiceError("A grade de Atribuições do Maximo não foi encontrada.")

    @staticmethod
    def _assignment_input(cells, column):
        inputs = cells[column].find_elements(By.TAG_NAME, "input")
        return inputs[0] if inputs else None

    @staticmethod
    def _input_value(element):
        return (element.get_attribute("value") or "").strip() if element else ""

    @staticmethod
    def _parse_maximo_datetime(value):
        raw = str(value or "").strip()
        for pattern in (
            "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %I:%M %p",
            "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%d/%m/%Y",
        ):
            try:
                return datetime.strptime(raw, pattern)
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_maximo_hours(value):
        raw = str(value or "").strip()
        if ":" in raw:
            hours, minutes = raw.split(":", 1)
            try:
                return int(hours) + int(minutes) / 60
            except ValueError:
                return None
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            return None

    @staticmethod
    def _format_maximo_hours(hours):
        minutes = round(float(hours) * 60)
        return f"{minutes // 60}:{minutes % 60:02d}"

    @staticmethod
    def _current_order_number(driver):
        field = BmaPageMonitor._find_labeled_input(driver, "Ordem de Trabalho")
        if field:
            return BmaPageMonitor._input_value(field)
        for element in driver.find_elements(By.CSS_SELECTOR, 'input[id$="-tb"]'):
            if "_tdrow_" not in (element.get_attribute("id") or ""):
                value = BmaPageMonitor._input_value(element)
                if value:
                    return value
        return ""

    def _current_order_number_in_frames(self, driver, depth=0):
        current = self._current_order_number(driver)
        if current or depth >= 8:
            return current
        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
            switched = False
            try:
                driver.switch_to.frame(frame)
                switched = True
                current = self._current_order_number_in_frames(driver, depth + 1)
            except WebDriverException:
                continue
            finally:
                if switched:
                    try:
                        driver.switch_to.parent_frame()
                    except WebDriverException:
                        driver.switch_to.default_content()
            if current:
                return current
        return ""

    def _wait_until(self, monitor_id, predicate, message, timeout=60):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            with self._lock:
                session = self._sessions.get(monitor_id)
                if not session or session["stop"].is_set():
                    raise BMAServiceError("Fila BMA interrompida pelo usuário.")
            try:
                result = predicate()
                if result:
                    return result
            except WebDriverException:
                pass
            sleep(0.5)
        raise BMAServiceError(message)

    def _wait_for_order(self, monitor_id, driver, wonum):
        def loaded():
            self._switch_to_manage_frame(driver)
            return self._current_order_number(driver) == wonum

        self._wait_until(monitor_id, loaded, f"A OT {wonum} não abriu no Maximo.")

    def _save_current_order(self, driver):
        self._switch_to_manage_frame(driver)
        save = driver.find_element(By.ID, "toolactions_SAVE-tbb_anchor")
        if not save.is_displayed() or not save.is_enabled():
            raise BMAServiceError("O botão Salvar do Maximo não está disponível.")
        self._click_when_idle(driver, save)

    def _fill_general_dates(self, monitor_id, driver, order):
        self._switch_to_manage_frame(driver)
        self._click_tab(driver, "Ordem de Trabalho")
        start = datetime.fromisoformat(order["planned_start"])
        finish = datetime.fromisoformat(order["planned_finish"])
        start_field = self._find_labeled_input(driver, "Início planejado")
        finish_field = self._find_labeled_input(driver, "Final planejado")
        if not start_field or not finish_field:
            raise BMAServiceError(f"Campos de datas planejadas ausentes na OT {order['wonum']}.")
        self._replace_input(start_field, start.strftime("%d/%m/%Y %H:%M"))
        self._replace_input(finish_field, finish.strftime("%d/%m/%Y %H:%M"))
        self._save_current_order(driver)

        def dates_saved():
            self._switch_to_manage_frame(driver)
            self._click_tab(driver, "Ordem de Trabalho")
            current_start = self._parse_maximo_datetime(
                self._input_value(self._find_labeled_input(driver, "Início planejado")),
            )
            current_finish = self._parse_maximo_datetime(
                self._input_value(self._find_labeled_input(driver, "Final planejado")),
            )
            return current_start == start and current_finish == finish

        self._wait_until(monitor_id, dates_saved, f"As datas da OT {order['wonum']} não foram salvas.")

    def _fill_assignments(self, monitor_id, driver, order):
        self._switch_to_manage_frame(driver)
        self._click_tab(driver, "Atribuições")
        table, columns, rows = self._find_assignment_grid(driver)
        while len(rows) < len(order["assignments"]):
            previous_count = len(rows)
            new_row = next((element for element in driver.find_elements(
                By.CSS_SELECTOR, 'a[title="New Row"]',
            ) if element.is_displayed() and element.is_enabled()), None)
            if not new_row:
                raise BMAServiceError(f"Não foi possível adicionar linha de atribuição na OT {order['wonum']}.")
            new_row.click()
            _, _, rows = self._wait_until(
                monitor_id,
                lambda: (grid if len(grid[2]) > previous_count else None)
                if (grid := self._find_assignment_grid(driver)) else None,
                f"A nova linha de atribuição não apareceu na OT {order['wonum']}.",
            )
            table, columns, rows = self._find_assignment_grid(driver)

        for row, _ in rows[len(order["assignments"]):]:
            delete_link = next((element for element in row.find_elements(
                By.CSS_SELECTOR, 'a[title="Marcar a linha para excluir"]',
            ) if element.is_displayed() and element.is_enabled()), None)
            if not delete_link:
                raise BMAServiceError(f"Não foi possível remover linha extra na OT {order['wonum']}.")
            delete_link.click()

        for (_, cells), assignment in zip(rows, order["assignments"]):
            labor = self._assignment_input(cells, columns["mao de obra"])
            planned_day = self._assignment_input(cells, columns["inicio planejado"])
            hours = self._assignment_input(cells, columns["horas"])
            if not labor or not planned_day or not hours:
                raise BMAServiceError(f"Campos de atribuição incompletos na OT {order['wonum']}.")
            laborcode = assignment["laborcode"].strip().upper()
            assignment_start = datetime.combine(date.fromisoformat(assignment["dia"]), datetime.min.time()).replace(minute=1)
            self._replace_input(labor, laborcode, select_suggestion=True)
            self._replace_input(planned_day, assignment_start.strftime("%d/%m/%Y %H:%M"))
            self._replace_input(hours, self._format_maximo_hours(assignment["horas"]))

        self._save_current_order(driver)

    def _verify_saved_order(self, monitor_id, driver, order):
        expected_start = datetime.fromisoformat(order["planned_start"])
        expected_finish = datetime.fromisoformat(order["planned_finish"])

        def verified():
            self._switch_to_manage_frame(driver)
            self._click_tab(driver, "Ordem de Trabalho")
            status = self._input_value(self._find_labeled_input(driver, "Status da OT"))
            current_start = self._parse_maximo_datetime(
                self._input_value(self._find_labeled_input(driver, "Início planejado")),
            )
            current_finish = self._parse_maximo_datetime(
                self._input_value(self._find_labeled_input(driver, "Final planejado")),
            )
            if (status.casefold() != "prepared" or current_start != expected_start
                    or current_finish != expected_finish):
                return False

            self._click_tab(driver, "Atribuições")
            _, columns, rows = self._find_assignment_grid(driver)
            if len(rows) != len(order["assignments"]):
                return False
            for (_, cells), assignment in zip(rows, order["assignments"]):
                labor = self._input_value(self._assignment_input(cells, columns["mao de obra"]))
                planned_day = self._parse_maximo_datetime(
                    self._input_value(self._assignment_input(cells, columns["inicio planejado"])),
                )
                hours = self._parse_maximo_hours(
                    self._input_value(self._assignment_input(cells, columns["horas"])),
                )
                expected_day = date.fromisoformat(assignment["dia"])
                if (not labor.upper().startswith(assignment["laborcode"].upper()) or not planned_day
                        or planned_day.date() != expected_day or hours is None
                        or abs(hours - float(assignment["horas"])) > 1 / 60):
                    return False
            return True

        self._wait_until(
            monitor_id, verified,
            f"Conferência falhou na OT {order['wonum']}: status, datas ou matrícula divergentes.",
        )

    def _open_order_in_maximo(self, monitor_id, driver, wonum):
        driver.switch_to.default_content()
        order_filter = self._find_order_filter(driver)
        if not order_filter:
            raise BMAServiceError("O campo Find Ordem de Trabalho não está disponível.")
        self._submit_order_filter(order_filter, wonum)

        self._open_order_result_in_maximo(monitor_id, driver, wonum)

    def _open_order_result_in_maximo(self, monitor_id, driver, wonum):
        def find_opened_order():
            driver.switch_to.default_content()
            if self._current_order_number_in_frames(driver) == wonum:
                return True, None
            link = self._find_order_link(driver, wonum)
            return (False, link) if link else None

        is_current_order, link = self._wait_until(
            monitor_id, find_opened_order,
            f"A OT {wonum} não foi encontrada no Maximo.",
        )
        if not is_current_order:
            try:
                link.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click();", link)

        def loaded():
            driver.switch_to.default_content()
            return self._current_order_number_in_frames(driver) == wonum

        self._wait_until(monitor_id, loaded, f"A OT {wonum} não abriu no Maximo.")

    def _process_order_queue(self, monitor_id, driver, orders):
        completed = []
        for index, order in enumerate(orders):
            with self._lock:
                session = self._sessions.get(monitor_id)
                if not session or session["stop"].is_set():
                    return False
            wonum = order["wonum"]
            if index:
                self._open_order_in_maximo(monitor_id, driver, wonum)
            self._update(
                monitor_id, current_order_index=index + 1, current_wonum=wonum,
                opened_wonum=wonum, stage="saving_dates",
                message=f"OT {wonum}: preenchendo início e final planejados.",
            )
            self._fill_general_dates(monitor_id, driver, order)
            self._update(
                monitor_id, stage="saving_assignments",
                message=f"OT {wonum}: preenchendo matrículas em maiúsculas e salvando Atribuições.",
            )
            self._fill_assignments(monitor_id, driver, order)
            self._update(monitor_id, stage="verifying", message=f"OT {wonum}: conferindo PREPARED, datas e matrículas.")
            self._verify_saved_order(monitor_id, driver, order)
            completed.append(wonum)
            self._update(
                monitor_id, completed_wonums=completed.copy(),
                message=f"OT {wonum} conferida. {len(completed)} de {len(orders)} concluída(s).",
            )
        return True

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
            queue_completed = False
            login_clicked = False
            filter_error = None
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
                    except WebDriverException as exc:
                        order_filter = None
                        filter_error = str(exc).strip()[:240] or type(exc).__name__
                    if order_filter or tracking_input_ready:
                        tracking_ready = True
                    if order_filter:
                        try:
                            self._update(monitor_id, stage="filtering", message=(
                                f"Filtrando a OT {wonums[0]} no rastreamento do Maximo."
                            ))
                            self._submit_order_filter(order_filter, wonums[0])
                            driver.switch_to.default_content()
                            query_submitted = True
                            filter_error = None
                        except WebDriverException as exc:
                            order_filter = None
                            filter_error = str(exc).strip()[:240] or type(exc).__name__
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
                    driver.switch_to.default_content()
                    try:
                        self._switch_to_manage_frame(driver)
                        current_wonum = self._current_order_number(driver)
                    except WebDriverException:
                        current_wonum = ""
                    if current_wonum == wonums[0]:
                        opened_wonum = wonums[0]
                    else:
                        driver.switch_to.default_content()
                        for wonum in wonums:
                            link = self._find_order_link(driver, wonum)
                            if not link:
                                continue
                            self._update(monitor_id, stage="opening_order", message=(
                                f"Abrindo a primeira OT selecionada: {wonum}."
                            ))
                            try:
                                link.click()
                            except WebDriverException:
                                try:
                                    driver.execute_script("arguments[0].click();", link)
                                except WebDriverException:
                                    continue
                            opened_wonum = wonum
                            break
                    if opened_wonum:
                        self._update(monitor_id, stage="opening_order", message=(
                            f"OT {opened_wonum} localizada; aguardando carregar para iniciar o planejamento."
                        ))
                        self._wait_for_order(monitor_id, driver, opened_wonum)
                        self._update(monitor_id, opened_wonum=opened_wonum, current_wonum=opened_wonum)
                        with self._lock:
                            session = self._sessions.get(monitor_id)
                            queue_stopped = not session or session["stop"].is_set()
                            orders = list(session["orders"]) if session else []
                        if not queue_stopped:
                            queue_completed = self._process_order_queue(monitor_id, driver, orders)
                if queue_completed:
                    self._update(
                        monitor_id, status="completed", stage="completed",
                        message=f"Fila concluída: {len(wonums)} OT(s) conferida(s). Firefox encerrado.",
                        elapsed_seconds=round(monotonic() - started_at),
                    )
                    break
                search_ready = any(field["id"] == "quicksearch" for field in fields)
                self._update(
                    monitor_id,
                    status="monitoring",
                    stage=("observing_order" if opened_wonum else "waiting_filter" if not query_submitted
                           else "waiting_results"),
                    message=(f"OT {opened_wonum} aberta. Observando os campos para orientar o preenchimento."
                             if opened_wonum else
                             f"Busca enviada; aguardando os resultados da OT {wonums[0]}."
                             if query_submitted else
                             f"Campo de filtro localizado, mas houve falha ao interagir: {filter_error}. Tentando novamente."
                             if filter_error else
                             "Campo de filtro detectado; tentando aplicar a busca."
                             if search_ready or tracking_ready else
                             "Página aberta; aguardando os controles de rastreamento aparecerem."),
                    fields=fields,
                    elapsed_seconds=round(monotonic() - started_at),
                    page_url=page_url,
                    page_title=page_title,
                )
                sleep(1)
        except Exception as exc:
            state = self.get(monitor_id) or {}
            self._update(
                monitor_id, status="failed", stage="failed",
                failed_wonum=state.get("current_wonum"),
                message=f"Fila interrompida na OT {state.get('current_wonum') or 'atual'}: {exc}",
            )
        finally:
            if driver:
                try:
                    driver.quit()
                except WebDriverException:
                    pass
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session and session["state"]["status"] not in {"failed", "completed"}:
                    session["state"].update(status="stopped", message="Monitor encerrado.")
                if session:
                    session["driver"] = None
            self._browser_lock.release()

    def _run_search_only(self, monitor_id: str, wonum: str):
        self._run_read_only(monitor_id, wonum)

    def _run_open_order_only(self, monitor_id: str, wonum: str):
        driver = None
        keep_browser_open = False
        self._browser_lock.acquire()
        try:
            with self._lock:
                session = self._sessions.get(monitor_id)
                if not session or session["stop"].is_set():
                    return
            service = BMAService()
            self._update(monitor_id, message="Abrindo Rastreamento de Ordem no Firefox.", progress=10)
            driver = service._create_browser(page_load_strategy="eager", headless=False)
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session:
                    session["driver"] = driver
            driver.set_page_load_timeout(service.timeout)
            try:
                driver.get(WOTRACK_URL)
            except TimeoutException:
                pass
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session:
                    session["state"].update(
                        status="completed",
                        stage="opened",
                        progress=100,
                        message="Rastreamento de Ordem aberto no Firefox.",
                        selected_wonums=[],
                        queue_total=0,
                        current_order_index=0,
                        current_wonum=None,
                        opened_wonum=None,
                        page_url=driver.current_url,
                        page_title=driver.title,
                    )
            keep_browser_open = True
        except Exception as exc:
            self._update(
                monitor_id, status="failed", stage="failed",
                message=f"Não foi possível abrir o Rastreamento de Ordem: {exc}",
            )
        finally:
            if driver and not keep_browser_open:
                try:
                    driver.quit()
                except WebDriverException:
                    pass
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session and not keep_browser_open:
                    session["driver"] = None
            self._browser_lock.release()

    def _run_read_only(self, monitor_id: str, wonum: str, *, open_order=False):
        driver = None
        started_at = monotonic()
        submitted = False
        opened = False
        self._browser_lock.acquire()
        try:
            with self._lock:
                session = self._sessions.get(monitor_id)
                if not session or session["stop"].is_set():
                    return
            service = BMAService()
            self._update(monitor_id, message="Iniciando Firefox para abrir a OT.", progress=10)
            driver = service._create_browser(page_load_strategy="eager", headless=False)
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session:
                    session["driver"] = driver
            driver.set_page_load_timeout(service.timeout)
            try:
                driver.get(WOTRACK_URL)
            except TimeoutException:
                pass
            self._update(monitor_id, progress=25)

            while True:
                with self._lock:
                    session = self._sessions.get(monitor_id)
                    if not session or session["stop"].is_set():
                        break
                try:
                    driver.switch_to.default_content()
                    fields = self._visible_fields(driver)
                except WebDriverException:
                    fields = []
                page_url = driver.current_url
                page_title = driver.title
                authenticated = not (
                    "auth.rbmanca4" in page_url or "login-fed.michelin.com" in page_url
                )
                filter_error = None
                if authenticated and not submitted:
                    try:
                        order_filter = self._find_order_filter(driver)
                    except WebDriverException as exc:
                        order_filter = None
                        filter_error = str(exc).strip()[:240] or type(exc).__name__
                    if order_filter:
                        try:
                            self._submit_order_filter(order_filter, wonum)
                            driver.switch_to.default_content()
                            submitted = True
                            self._update(monitor_id, stage="search_submitted", progress=60)
                        except WebDriverException as exc:
                            filter_error = str(exc).strip()[:240] or type(exc).__name__
                if open_order and submitted and not opened:
                    self._update(
                        monitor_id, stage="opening_order", progress=80,
                        message=f"Abrindo a primeira OT: {wonum}.",
                    )
                    self._open_order_result_in_maximo(monitor_id, driver, wonum)
                    opened = True
                    self._update(
                        monitor_id, status="monitoring", stage="opened", progress=100,
                        opened_wonum=wonum, current_wonum=wonum,
                        message=f"OT {wonum} aberta no Maximo. Nenhum dado foi alterado.",
                    )
                message = (
                    f"OT {wonum} aberta no Maximo. Nenhum dado foi alterado."
                    if opened else
                    f"OT {wonum} enviada no filtro. Aguardando o resultado para abrir."
                    if submitted and open_order else
                    f"OT {wonum} enviada no filtro. A busca está aberta; nenhum resultado foi aberto ou alterado."
                    if submitted else
                    "Conclua o login/MFA na janela Firefox; a busca será enviada ao aparecer o rastreamento."
                    if not authenticated else
                    f"Aguardando o campo de busca do Rastreamento de Ordem de Trabalho para inserir {wonum}."
                )
                if filter_error:
                    message = f"Não foi possível inserir a OT no filtro: {filter_error}"
                self._update(
                    monitor_id,
                    status="monitoring",
                    stage="opened" if opened else "search_submitted" if submitted else "waiting_filter",
                    progress=100 if opened else 60 if submitted else 30,
                    message=message,
                    fields=fields,
                    elapsed_seconds=round(monotonic() - started_at),
                    current_order_index=0,
                    current_wonum=wonum,
                    opened_wonum=wonum if opened else None,
                    page_url=page_url,
                    page_title=page_title,
                )
                sleep(1)
        except Exception as exc:
            self._update(
                monitor_id, status="failed", stage="failed",
                failed_wonum=wonum,
                message=f"Busca somente leitura interrompida: {exc}",
            )
        finally:
            if driver:
                try:
                    driver.quit()
                except WebDriverException:
                    pass
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session and session["state"]["status"] not in {"failed", "completed"}:
                    session["state"].update(status="stopped", message="Busca somente leitura encerrada.")
                if session:
                    session["driver"] = None
            self._browser_lock.release()
