from __future__ import annotations

import unicodedata
from typing import Any

from selenium.common.exceptions import ElementClickInterceptedException, NoAlertPresentException, StaleElementReferenceException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from .BMAService import BMAService, BMAServiceError, maximo_ui_loaded


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def _find(driver, by: str, selector: str, predicate):
    driver.switch_to.default_content()
    return BMAService._find_matching_in_frames(driver, by, selector, predicate)


def _find_all(driver, by: str, selector: str, predicate, *, require_enabled: bool = True):
    driver.switch_to.default_content()
    found = []

    def collect(element):
        if predicate(element):
            found.append(element)
        return False

    BMAService._find_matching_in_frames(driver, by, selector, collect, require_enabled=require_enabled)
    return found


def _find_control(driver, label: str, index: int = 0, *, require_enabled: bool = True):
    wanted = _normalize(label)
    matched_count = 0

    def matches_label(element):
        nonlocal matched_count
        try:
            text = driver.execute_script(
                """
                const el = arguments[0];
                const ids = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
                const labelled = ids.map(id => document.getElementById(id)?.innerText || '').join(' ');
                const labels = Array.from(el.labels || []).map(label => label.innerText || '').join(' ');
                                const cell = el.closest('td');
                                const cellText = cell?.innerText || '';
                                const adjacentLabel = cell?.previousElementSibling?.innerText || '';
                return [el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                                    el.getAttribute('title'), el.id, el.name, labelled, labels, adjacentLabel, cellText]
                  .filter(Boolean).join(' ');
                """,
                element,
            )
        except WebDriverException:
            return False
        if wanted not in _normalize(str(text or "")):
            return False
        matched_count += 1
        return matched_count > index

    driver.switch_to.default_content()
    return BMAService._find_matching_in_frames(
        driver, By.CSS_SELECTOR, "input,textarea,select", matches_label,
        require_enabled=require_enabled,
    )


def _value(driver, label: str, index: int = 0) -> str:
    if _normalize(label) == "ordem de trabalho":
        order_numbers = []

        def capture_order_number(element):
            value = (element.get_attribute("value") or "").strip()
            if value.upper().startswith("RES"):
                order_numbers.append(value)
                return True
            return False

        _find_all(
            driver,
            By.CSS_SELECTOR,
            "input[aria-readonly='true'],input[readonly],input:disabled",
            capture_order_number,
            require_enabled=False,
        )
        if order_numbers:
            return order_numbers[0]
    control = _find_control(driver, label, index, require_enabled=False)
    return (control.get_attribute("value") or "").strip() if control is not None else ""


def _value_confirmed(driver, label: str, expected: str, index: int) -> bool:
    actual = _value(driver, label, index)
    if actual == expected.strip():
        return True
    if _normalize(label) != "equipamento":
        return False
    actual = _normalize(actual)
    expected = _normalize(expected)
    return actual.startswith(expected) and len(actual) > len(expected) and actual[len(expected)] in " -/"


def _set(driver, label: str, value: str, index: int = 0, after_key=Keys.TAB) -> None:
    def field_ready(browser):
        browser.switch_to.default_content()
        overlay = _find(
            browser, By.CSS_SELECTOR,
            ".bx--loading-overlay, #msgbox-dialog_inner_dialogwait, .wait_modal",
            lambda element: element.is_displayed(),
        )
        if overlay is not None:
            return False
        return _find_control(browser, label, index)

    for attempt in range(3):
        try:
            control = WebDriverWait(driver, 30, poll_frequency=0.25).until(field_ready)
            control.click()
            control.send_keys(Keys.CONTROL, "a")
            control.send_keys(str(value))
            control.send_keys(after_key)
            return
        except (ElementClickInterceptedException, StaleElementReferenceException) as exc:
            if attempt == 2:
                raise BMAServiceError(f"O campo {label} continuou bloqueado durante a atualização do Maximo.") from exc
        except TimeoutException as exc:
            raise BMAServiceError(f"O campo {label} não ficou pronto para preenchimento.") from exc


def _confirm_work_type_change(driver, timeout: int = 5) -> None:
    code = "bmxzz0036w"
    question = "tem certeza de que deseja alterar o tipo de ordem de trabalho"

    def confirmation_ready(browser):
        try:
            alert = browser.switch_to.alert
        except NoAlertPresentException:
            alert = None
        if alert is not None:
            alert_text = _normalize(alert.text)
            if code in alert_text or question in alert_text:
                alert.accept()
                return True
            raise BMAServiceError(f"Confirmação inesperada do BMA: {alert.text}")

        def is_yes_for_work_type(element):
            label = element.text or element.get_attribute("value") or element.get_attribute("title") or ""
            if _normalize(label) != "sim":
                return False
            try:
                text = browser.execute_script(
                    """
                    const button = arguments[0];
                    const dialog = button.closest('[role="dialog"],.bx--modal,.messagebox,[id*="dialog"],[class*="dialog"]');
                    return dialog?.innerText || document.body.innerText || '';
                    """,
                    element,
                )
            except WebDriverException:
                return False
            normalized = _normalize(str(text or ""))
            return code in normalized or question in normalized

        button = _find(
            browser, By.CSS_SELECTOR,
            "button,input[type='button'],input[type='submit'],[role='button'],a",
            is_yes_for_work_type,
        )
        if button is None:
            return False
        try:
            button.click()
        except StaleElementReferenceException:
            return False
        return True

    try:
        WebDriverWait(driver, timeout, poll_frequency=0.25).until(confirmation_ready)
    except TimeoutException:
        return


def _verify_fields(driver, expected_fields: list[tuple[str, str, int]], timeout: int = 30) -> None:
    def fields_confirmed(browser):
        browser.switch_to.default_content()
        overlay = _find(
            browser, By.CSS_SELECTOR,
            ".bx--loading-overlay, #msgbox-dialog_inner_dialogwait, .wait_modal",
            lambda element: element.is_displayed(),
        )
        return overlay is None and all(
            _value_confirmed(browser, label, expected, index)
            for label, expected, index in expected_fields
        )

    try:
        WebDriverWait(driver, timeout, poll_frequency=0.25).until(fields_confirmed)
    except TimeoutException as exc:
        raise BMAServiceError(
            "A conferência final encontrou campos da OT sem o valor esperado; o BMA não foi salvo."
        ) from exc


def _click(driver, by: str, selector: str, label: str, timeout: int = 20):
    try:
        element = WebDriverWait(driver, timeout, poll_frequency=0.25).until(
            lambda browser: _find(
                browser, by, selector,
                lambda element: element.is_displayed() and element.is_enabled()
                and maximo_ui_loaded(browser),
            )
        )
    except TimeoutException as exc:
        raise BMAServiceError(f"Botão não encontrado no Quick Report: {label}.") from exc
    try:
        element.click()
    except WebDriverException as exc:
        if "the hidden form is missing" in str(exc).casefold():
            raise BMAServiceError(
                "O Quick Report ainda não carregou o formulário interno do Maximo; aguarde o carregamento e tente novamente."
            ) from exc
        raise


def _set_long_description(driver, text: str) -> None:
    field = _find_control(driver, "Ordem de Trabalho description")
    if field is None:
        raise BMAServiceError("Campo de título do Quick Report não encontrado.")
    try:
        button = field.find_element(By.XPATH, "following-sibling::img[@alt='Descrição Longa']")
        button.click()
        dialog = WebDriverWait(driver, 15, poll_frequency=0.25).until(
            lambda browser: _find(browser, By.CSS_SELECTOR, "[role='dialog']", lambda item: item.is_displayed())
        )
        editor = WebDriverWait(driver, 10, poll_frequency=0.25).until(
            lambda _browser: next((item for item in dialog.find_elements(
                By.CSS_SELECTOR, "textarea,input[type='text'],[contenteditable='true']",
            ) if item.is_displayed() and item.is_enabled()), False)
        )
        editor.click()
        editor.send_keys(Keys.CONTROL, "a")
        editor.send_keys(text)
        actual = editor.get_attribute("value")
        if actual is None:
            actual = editor.text
        if actual != text:
            raise BMAServiceError("A descrição longa não foi preenchida integralmente.")
        dialog.find_element(By.XPATH, ".//button[normalize-space()='OK']").click()
        WebDriverWait(driver, 10, poll_frequency=0.25).until(
            lambda browser: _find(browser, By.CSS_SELECTOR, "[role='dialog']", lambda item: item.is_displayed()) is None
        )
    except (TimeoutException, WebDriverException) as exc:
        raise BMAServiceError("Não foi possível preencher a descrição longa no Quick Report.") from exc


def _open_new_order(driver) -> str:
    existing_form = _find_control(driver, "Ordem de Trabalho description") is not None
    previous_number = _value(driver, "Ordem de Trabalho") if existing_form else ""
    if existing_form and _normalize(_value(driver, "Status da OT")) != "comp":
        raise BMAServiceError(
            f"A OT {previous_number or 'atual'} ainda não está em COMP; não vou abrir outra OT para evitar perda ou duplicidade."
        )
    _click(
        driver, By.CSS_SELECTOR,
        "#toolactions_INSERT-tbb_anchor",
        "Nova Ordem de trabalho",
    )
    def order_form_ready(browser):
        return _find_control(browser, "Ordem de Trabalho description") is not None

    try:
        WebDriverWait(driver, 30, poll_frequency=0.25).until(order_form_ready)
    except TimeoutException:
        if not order_form_ready(driver):
            _click(
                driver, By.CSS_SELECTOR, "#toolactions_INSERT-tbb_anchor",
                "Nova Ordem de trabalho",
            )
            try:
                WebDriverWait(driver, 30, poll_frequency=0.25).until(order_form_ready)
            except TimeoutException as exc:
                raise BMAServiceError(
                    "Duas tentativas no + do Quick Report não abriram o formulário da nova ordem."
                ) from exc
    try:
        WebDriverWait(driver, 15, poll_frequency=0.25).until(
            lambda browser: _value(browser, "Ordem de Trabalho").startswith("RES")
            and _value(browser, "Ordem de Trabalho") != previous_number
        )
    except TimeoutException as exc:
        raise BMAServiceError("O formulário abriu após o clique no +, mas o Maximo não gerou o número RES.") from exc
    number = _value(driver, "Ordem de Trabalho")
    if not number.startswith("RES"):
        raise BMAServiceError(f"Número de OT inválido retornado pelo BMA: {number}.")
    return number


def _save(driver, expected_number: str) -> None:
    _click(driver, By.ID, "toolactions_SAVE-tbb_anchor", "Salvar Ordem de trabalho")
    try:
        WebDriverWait(driver, 20, poll_frequency=0.25).until(
            lambda browser: not any(
                overlay.is_displayed()
                for overlay in browser.find_elements(By.CSS_SELECTOR, ".bx--loading-overlay")
            )
        )
    except TimeoutException as exc:
        raise BMAServiceError("O Quick Report não terminou de salvar a OT.") from exc
    actual = _value(driver, "Ordem de Trabalho")
    if actual != expected_number:
        raise BMAServiceError(f"O número da OT mudou durante o salvamento: {expected_number} -> {actual}.")
    messages = _find(
        driver, By.CSS_SELECTOR, "[role='alert'],.fieldError,.errmsg,.messagebox-text",
        lambda item: item.is_displayed() and bool((item.text or "").strip()),
    ) or []
    errors = [
        item.text.strip() for item in messages
        if "bmxaa4205i" not in _normalize(item.text)
        and "o registro foi salvo" not in _normalize(item.text)
    ]
    if errors:
        raise BMAServiceError("O BMA recusou o salvamento: " + " | ".join(errors))


def _add_labor_row(driver, row_index: int = 0) -> None:
    if _find_control(driver, "Mão de obra", row_index) is not None:
        return
    _click(
        driver, By.CSS_SELECTOR,
        "button[id$='_bg_button_addrow-pb'],a[id$='_bg_button_addrow-pb_addrow_a'],"
        "button[title='Nova linha'],button[title='New Row'],img[id$='_addrow']",
        "Nova linha de mão de obra",
    )
    try:
        WebDriverWait(driver, 8, poll_frequency=0.25).until(
            lambda browser: _find_control(browser, "Mão de obra", row_index) is not None
        )
    except TimeoutException as exc:
        raise BMAServiceError("A linha de mão de obra não apareceu.") from exc


def _complete_workflow(driver, timeout: int = 90) -> None:
    _click(driver, By.CSS_SELECTOR, "a[title='Rotear Workflow']", "Rotear Workflow")
    try:
        dialog = WebDriverWait(driver, timeout, poll_frequency=0.25).until(
            lambda browser: _find(browser, By.CSS_SELECTOR, "#inputwf-hb", lambda item: item.is_displayed())
        )
    except TimeoutException as exc:
        raise BMAServiceError("O modal de workflow do BMA não abriu.") from exc
    options = _find_all(driver, By.XPATH, "//input[@type='radio'] | //*[@role='radio']", lambda item: item.is_displayed())

    def option_text(item):
        value = driver.execute_script(
            "const e=arguments[0], row=e.closest('tr'); return row?.innerText || e.parentElement?.innerText || e.value || '';",
            item,
        )
        return _normalize(str(value or ""))

    option = next((item for item in options if "completar a ordem de trabalho" in option_text(item)), None)
    if option is None:
        raise BMAServiceError("Opção 'Completar a Ordem de Trabalho' não encontrada no workflow.")
    if not option.is_selected():
        option.click()
    buttons = dialog.find_elements(By.CSS_SELECTOR, "button[title='OK']")
    if not buttons:
        buttons = dialog.find_elements(By.XPATH, ".//button[normalize-space()='OK']")
    if not buttons:
        raise BMAServiceError("Botão OK não encontrado no workflow.")
    buttons[0].click()
    try:
        WebDriverWait(driver, timeout, poll_frequency=0.5).until(
            lambda browser: _normalize(_value(browser, "Status da OT")) == "comp"
        )
    except TimeoutException as exc:
        raise BMAServiceError("O workflow não confirmou status COMP para a OT.") from exc


def create_ronda_work_order(
    driver,
    order: dict[str, Any],
    *,
    on_number=None,
    on_saved=None,
    on_completed=None,
) -> str:
    labor = order.get("labor")
    if not isinstance(labor, list) or not labor:
        raise BMAServiceError("A OT de Ronda não possui executantes válidos.")
    if not order.get("equipment") or not order.get("description_longdescription"):
        raise BMAServiceError("A OT de Ronda está sem equipamento ou descrição longa.")

    number = _open_new_order(driver)
    if on_number:
        on_number(number)
    title = f"SITE-NFE-{order['ronda']}"
    equipment = str(order["equipment"])
    work_type = "T"
    refers_to = str(order.get("refers_to") or "3 AVAIL")
    equipment_status = "NA"
    expected_location = str(order.get("location") or "OFICINA-NFE")
    expected_fields = [
        ("Ordem de Trabalho description", title, 0),
        ("Equipamento", equipment, 0),
        ("Local", expected_location, 0),
        ("Tipo de trabalho", work_type, 0),
        ("Refere-se a", refers_to, 0),
        ("Status do Equipamento", equipment_status, 0),
    ]

    _set(driver, "Ordem de Trabalho description", title)
    _set(driver, "Equipamento", equipment)
    _set(driver, "Tipo de trabalho", work_type)
    _confirm_work_type_change(driver)
    _set(driver, "Refere-se a", refers_to)
    _set(driver, "Status do Equipamento", equipment_status)
    _set_long_description(driver, str(order["description_longdescription"]))

    for index, person in enumerate(labor):
        _add_labor_row(driver, index)
        laborcode = str(person["laborcode"])
        start_date = str(order["start_date"])
        start_time = str(order["start_time"])
        end_date = str(order["end_date"])
        end_time = str(order["end_time"])
        hours = float(order["hours"])
        normal_hours = f"{int(hours)}:{round((hours % 1) * 60):02d}"
        _set(driver, "Mão de obra", laborcode, index)
        _set(driver, "Data de início", start_date, index)
        _set(driver, "Hora de início", start_time, index)
        _set(driver, "End Date", end_date, index)
        _set(driver, "Hora de término", end_time, index)
        _set(driver, "Horas normais", normal_hours, index)
        expected_fields.extend([
            ("Mão de obra", laborcode, index),
            ("Data de início", start_date, index),
            ("Hora de início", start_time, index),
            ("End Date", end_date, index),
            ("Hora de término", end_time, index),
            ("Horas normais", normal_hours, index),
        ])
    _verify_fields(driver, expected_fields)
    _save(driver, number)
    if on_saved:
        on_saved(number)
    _complete_workflow(driver)
    if on_completed:
        on_completed(number)
    return number
