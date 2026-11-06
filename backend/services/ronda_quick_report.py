"""Selenium flow dedicated to creating Ronda work orders in Maximo Quick Report."""

from __future__ import annotations

import unicodedata
from typing import Any

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoAlertPresentException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
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


def _find_all(driver, by: str, selector: str, predicate):
    found = []

    def collect(element):
        if predicate(element):
            found.append(element)
        return False

    driver.switch_to.default_content()
    BMAService._find_matching_in_frames(driver, by, selector, collect)
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
                const adjacentLabel = cell?.previousElementSibling?.innerText || '';
                return [el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                  el.getAttribute('title'), el.id, el.name, labelled, labels, adjacentLabel,
                  cell?.innerText || ''].filter(Boolean).join(' ');
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
        values = []

        def capture_number(element):
            value = (element.get_attribute("value") or "").strip()
            if value.upper().startswith("RES"):
                values.append(value)
                return True
            return False

        driver.switch_to.default_content()
        BMAService._find_matching_in_frames(
            driver, By.CSS_SELECTOR,
            "input[aria-readonly='true'],input[readonly],input:disabled",
            capture_number, require_enabled=False,
        )
        if values:
            return values[0]
    control = _find_control(driver, label, index, require_enabled=False)
    return (control.get_attribute("value") or "").strip() if control is not None else ""


def _value_matches(driver, label: str, expected: str, index: int = 0) -> bool:
    actual = _value(driver, label, index)
    if actual == expected.strip():
        return True
    if _normalize(label) != "equipamento":
        return False
    actual_normalized = _normalize(actual)
    expected_normalized = _normalize(expected)
    return (
        actual_normalized.startswith(expected_normalized)
        and len(actual_normalized) > len(expected_normalized)
        and actual_normalized[len(expected_normalized)] in " -/"
    )


def _loading_overlay(driver):
    return _find(
        driver, By.CSS_SELECTOR,
        ".bx--loading-overlay, #msgbox-dialog_inner_dialogwait, .wait_modal",
        lambda element: element.is_displayed(),
    )


def _required_fields_ok_button(driver):
    def is_required_fields_ok(element):
        label = element.text or element.get_attribute("value") or element.get_attribute("title") or ""
        if _normalize(label) != "ok":
            return False
        try:
            text = driver.execute_script("return document.body.innerText || ''", element)
        except WebDriverException:
            try:
                text = driver.execute_script("return document.body.innerText || ''")
            except WebDriverException:
                return False
        return "bmxaa7998e" in _normalize(str(text or ""))

    return _find(
        driver, By.CSS_SELECTOR,
        "button,input[type='button'],input[type='submit'],[role='button'],a",
        is_required_fields_ok,
    )


def _dismiss_required_fields_message(driver) -> bool:
    try:
        alert = driver.switch_to.alert
    except NoAlertPresentException:
        alert = None
    if alert is not None:
        if "bmxaa7998e" not in _normalize(alert.text):
            return False
        alert.accept()
        return True

    button = _required_fields_ok_button(driver)
    if button is None:
        return False
    try:
        button.click()
        WebDriverWait(driver, 5, poll_frequency=0.2).until(
            lambda browser: _required_fields_ok_button(browser) is None
        )
        return True
    except (StaleElementReferenceException, TimeoutException):
        return False


def _missing_fields(driver, expected: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
    return [
        (label, value, index)
        for label, value, index in expected
        if not _value_matches(driver, label, value, index)
    ]


def _fill(driver, label: str, value: str, index: int = 0, *, skip_if_matches: bool = False) -> None:
    def field_ready(browser):
        browser.switch_to.default_content()
        _dismiss_required_fields_message(browser)
        if _loading_overlay(browser) is not None:
            return False
        if skip_if_matches and _value_matches(browser, label, value, index):
            return (None, True)
        control = _find_control(browser, label, index)
        return (control, False) if control is not None else False

    for attempt in range(3):
        try:
            control, already_filled = WebDriverWait(driver, 30, poll_frequency=0.25).until(field_ready)
            if already_filled:
                return
            driver.execute_script(
                """
                const element = arguments[0];
                const value = arguments[1];
                const prototype = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
                  : element.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
                element.focus();
                if (setter) setter.call(element, value);
                else element.value = value;
                const document = element.ownerDocument;
                for (const name of ['input', 'change']) {
                    const event = document.createEvent('HTMLEvents');
                    event.initEvent(name, true, false);
                    element.dispatchEvent(event);
                }
                element.blur();
                const maximoWindow = element.ownerDocument.defaultView;
                if (typeof maximoWindow.sendEvent !== 'function') {
                  throw new Error('Maximo sendEvent is unavailable in the field frame.');
                }
                maximoWindow.sendEvent('change', element.id, value);
                """,
                control,
                str(value),
            )
            WebDriverWait(driver, 10, poll_frequency=0.25).until(
                lambda browser: maximo_ui_loaded(browser) and _value_matches(browser, label, value, index)
            )
            return
        except (ElementClickInterceptedException, StaleElementReferenceException, WebDriverException) as exc:
            if attempt == 2:
                raise BMAServiceError(f"O Maximo não aceitou a atualização direta do campo {label}.") from exc
        except TimeoutException as exc:
            raise BMAServiceError(f"O valor do campo {label} não foi confirmado pelo Maximo.") from exc


def _confirm_work_type_change(driver, timeout: int = 5) -> None:
    code = "bmxzz0036w"
    question = "tem certeza de que deseja alterar o tipo de ordem de trabalho"

    def confirmation_ready(browser):
        try:
            alert = browser.switch_to.alert
        except NoAlertPresentException:
            alert = None
        if alert is not None:
            text = _normalize(alert.text)
            if code in text or question in text:
                alert.accept()
                return True
            raise BMAServiceError(f"Confirmação inesperada do BMA: {alert.text}")

        def is_no_button(element):
            label = (
                element.text or element.get_attribute("value")
                or element.get_attribute("aria-label") or element.get_attribute("title") or ""
            )
            if _normalize(label) != "nao":
                return False
            try:
                dialog_text = browser.execute_script(
                    """
                    const button = arguments[0];
                    const dialog = button.closest('[role="dialog"],.bx--modal,.messagebox,[id*="dialog"],[class*="dialog"]');
                    return dialog?.innerText || document.body.innerText || '';
                    """,
                    element,
                )
            except WebDriverException:
                return False
            normalized = _normalize(str(dialog_text or ""))
            return code in normalized or question in normalized

        button = _find(
            browser, By.CSS_SELECTOR,
            "button,input[type='button'],input[type='submit'],[role='button'],a",
            is_no_button,
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


def _verify_fields(driver, expected: list[tuple[str, str, int]], timeout: int = 30) -> list[tuple[str, str, int]]:
    def all_confirmed(browser):
        browser.switch_to.default_content()
        if _dismiss_required_fields_message(browser):
            return "required_fields"
        if _loading_overlay(browser) is not None:
            return False
        return not _missing_fields(browser, expected)

    try:
        result = WebDriverWait(driver, timeout, poll_frequency=0.25).until(all_confirmed)
    except TimeoutException:
        return _missing_fields(driver, expected)
    return _missing_fields(driver, expected) if result == "required_fields" else []


def _set_long_description(driver, text: str) -> None:
    field = _find_control(driver, "Ordem de Trabalho description")
    if field is None:
        raise BMAServiceError("Campo de título do Quick Report não encontrado.")

    icon = _find(
        driver, By.CSS_SELECTOR, "img[alt],img[title],[aria-label]",
        lambda item: item.is_displayed() and any(
            "descricao longa" in _normalize(item.get_attribute(attribute) or "")
            for attribute in ("alt", "title", "aria-label")
        ),
    )
    if icon is None:
        raise BMAServiceError("Ícone de descrição longa do título não encontrado.")

    def description_dialog_ready(browser):
        dialog = _find(
            browser, By.CSS_SELECTOR, "[role='dialog'],.dijitDialog",
            lambda item: item.is_displayed() and "descricao longa" in _normalize(item.text or ""),
        )
        if dialog is None:
            return False
        editor = next((item for item in dialog.find_elements(
            By.CSS_SELECTOR, "textarea,input[type='text'],[contenteditable='true']",
        ) if item.is_displayed() and item.is_enabled()), None)
        return (dialog, editor) if editor is not None else False

    try:
        icon.click()
        dialog, editor = WebDriverWait(driver, 30, poll_frequency=0.25).until(description_dialog_ready)
        editor.click()
        editor.send_keys(Keys.CONTROL, "a")
        editor.send_keys(text)
        actual = editor.get_attribute("value")
        if actual is None:
            actual = editor.text
        if actual != text:
            raise BMAServiceError("A descrição longa não foi preenchida integralmente.")

        ok_button = next((button for button in dialog.find_elements(
            By.CSS_SELECTOR, "button,input[type='button'],input[type='submit'],[role='button'],a",
        ) if _normalize(
            button.text or button.get_attribute("value") or button.get_attribute("aria-label")
            or button.get_attribute("title") or ""
        ) == "ok" and button.is_displayed() and button.is_enabled()), None)
        if ok_button is None:
            raise BMAServiceError("Botão OK do modal de descrição longa não encontrado.")
        ok_button.click()
        WebDriverWait(driver, 10, poll_frequency=0.25).until(
            lambda browser: _find(
                browser, By.CSS_SELECTOR, "[role='dialog'],.dijitDialog",
                lambda item: item.is_displayed() and "descricao longa" in _normalize(item.text or ""),
            ) is None
        )
    except TimeoutException as exc:
        raise BMAServiceError("O modal Descrição Longa do título não ficou pronto ou não fechou.") from exc
    except WebDriverException as exc:
        raise BMAServiceError(
            f"Não foi possível preencher a descrição longa no Quick Report: {type(exc).__name__}: {exc}"
        ) from exc


def _open_new_order(driver) -> str:
    form_exists = _find_control(driver, "Ordem de Trabalho description") is not None
    previous_number = _value(driver, "Ordem de Trabalho") if form_exists else ""
    if form_exists and _normalize(_value(driver, "Status da OT")) != "comp":
        raise BMAServiceError(
            f"A OT {previous_number or 'atual'} ainda não está em COMP; não vou abrir outra OT."
        )
    _click_new_order(driver)
    try:
        WebDriverWait(driver, 30, poll_frequency=0.25).until(
            lambda browser: _find_control(browser, "Ordem de Trabalho description") is not None
        )
    except TimeoutException as exc:
        raise BMAServiceError("O botão Nova Ordem foi ativado, mas o formulário não abriu.") from exc
    try:
        WebDriverWait(driver, 15, poll_frequency=0.25).until(
            lambda browser: _value(browser, "Ordem de Trabalho").startswith("RES")
            and _value(browser, "Ordem de Trabalho") != previous_number
        )
    except TimeoutException as exc:
        raise BMAServiceError("O formulário abriu, mas o Maximo não gerou um novo número RES.") from exc
    number = _value(driver, "Ordem de Trabalho")
    if not number.startswith("RES"):
        raise BMAServiceError(f"Número de OT inválido retornado pelo BMA: {number}.")
    return number


def _click_new_order(driver, timeout: int = 90) -> None:
    def insert_button_ready(browser):
        browser.switch_to.default_content()

        def is_ready(anchor):
            if not anchor.is_displayed() or not anchor.is_enabled():
                return False
            if (anchor.get_attribute("aria-disabled") or "").casefold() == "true":
                return False
            icons = anchor.find_elements(By.ID, "toolactions_INSERT-tbb_image")
            return bool(icons and icons[0].is_displayed() and maximo_ui_loaded(browser))

        return _find(browser, By.CSS_SELECTOR, "a#toolactions_INSERT-tbb_anchor", is_ready)

    try:
        button = WebDriverWait(driver, timeout, poll_frequency=0.1).until(insert_button_ready)
    except TimeoutException as exc:
        raise BMAServiceError("Botão Nova Ordem de Trabalho não ficou pronto no Quick Report.") from exc
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", button)
    except (ElementClickInterceptedException, StaleElementReferenceException, WebDriverException) as exc:
        raise BMAServiceError("O botão Nova Ordem ficou pronto, mas não foi possível ativá-lo.") from exc


def _save(driver, number: str) -> None:
    try:
        button = WebDriverWait(driver, 20, poll_frequency=0.25).until(
            lambda browser: _find(
                browser, By.ID, "toolactions_SAVE-tbb_anchor",
                lambda element: element.is_displayed() and element.is_enabled() and maximo_ui_loaded(browser),
            )
        )
        button.click()
        WebDriverWait(driver, 20, poll_frequency=0.25).until(lambda browser: _loading_overlay(browser) is None)
    except TimeoutException as exc:
        raise BMAServiceError("O Quick Report não terminou de salvar a OT.") from exc
    if _dismiss_required_fields_message(driver):
        return False
    if _value(driver, "Ordem de Trabalho") != number:
        raise BMAServiceError("O número da OT mudou durante o salvamento.")
    errors = _find(
        driver, By.CSS_SELECTOR, "[role='alert'],.fieldError,.errmsg,.messagebox-text",
        lambda item: item.is_displayed() and bool((item.text or "").strip())
        and "bmxaa4205i" not in _normalize(item.text)
        and "o registro foi salvo" not in _normalize(item.text),
    ) or []
    if errors:
        if any("bmxaa7998e" in _normalize(item.text) for item in errors):
            _dismiss_required_fields_message(driver)
            return False
        raise BMAServiceError("O BMA recusou o salvamento: " + " | ".join(item.text.strip() for item in errors))
    return True


def _add_labor_row(driver, index: int) -> None:
    if _find_control(driver, "Mão de obra", index) is not None:
        return

    try:
        button = WebDriverWait(driver, 15, poll_frequency=0.25).until(
            lambda browser: _find(
                browser, By.CSS_SELECTOR,
                "a[id$='_bg_button_addrow-pb_addrow_a']",
                lambda element: element.is_displayed() and element.is_enabled()
                and bool(element.find_elements(By.CSS_SELECTOR, "img[id$='_addrow']"))
                and maximo_ui_loaded(browser),
            )
        )
        button.click()
        WebDriverWait(driver, 10, poll_frequency=0.25).until(
            lambda browser: _find_control(browser, "Mão de obra", index) is not None
        )
    except TimeoutException as exc:
        raise BMAServiceError("A linha de mão de obra não ficou pronta.") from exc
    except (ElementClickInterceptedException, StaleElementReferenceException, WebDriverException) as exc:
        if _find_control(driver, "Mão de obra", index) is not None:
            return
        raise BMAServiceError(
            f"O botão + da mão de obra não foi ativado: {type(exc).__name__}: {exc}"
        ) from exc


def _complete_workflow(driver, timeout: int = 90) -> None:
    try:
        button = WebDriverWait(driver, 20, poll_frequency=0.25).until(
            lambda browser: _find(
                browser, By.CSS_SELECTOR, "a[title='Rotear Workflow']",
                lambda element: element.is_displayed() and element.is_enabled(),
            )
        )
        button.click()
        WebDriverWait(driver, timeout, poll_frequency=0.25).until(
            lambda browser: _find(browser, By.CSS_SELECTOR, "#inputwf-hb", lambda item: item.is_displayed())
        )
    except TimeoutException as exc:
        raise BMAServiceError("O modal de workflow do BMA não abriu.") from exc
    def is_complete_workflow_option(item):
        if not item.is_displayed():
            return False
        option_text = driver.execute_script(
            "const e=arguments[0], row=e.closest('tr'); return row?.innerText || e.parentElement?.innerText || e.value || '';",
            item,
        )
        return "completar a ordem de trabalho" in _normalize(str(option_text or ""))

    option = _find(
        driver, By.XPATH, "//input[@type='radio'] | //*[@role='radio']",
        is_complete_workflow_option,
    )
    if option is None:
        raise BMAServiceError("Opção 'Completar a Ordem de Trabalho' não encontrada no workflow.")
    if not option.is_selected():
        option.click()
    ok_button = _find(
        driver, By.CSS_SELECTOR, "button[title='OK']",
        lambda item: item.is_displayed() and item.is_enabled(),
    )
    if ok_button is None:
        raise BMAServiceError("Botão OK não encontrado no workflow.")
    ok_button.click()
    try:
        WebDriverWait(driver, timeout, poll_frequency=0.5).until(
            lambda browser: _normalize(_value(browser, "Status da OT")) == "comp"
        )
    except TimeoutException as exc:
        raise BMAServiceError("O workflow não confirmou status COMP para a OT.") from exc


def fill_ronda_quick_report_fields(
    driver,
    order: dict[str, Any],
    labor: list[dict[str, Any]],
    *,
    on_progress=None,
) -> list[tuple[str, str, int]]:
    """Quick Report sequence: title, long description, equipment, location, refers-to, status, type, then labor."""
    def report(message):
        if on_progress:
            on_progress(message)

    title = f"SITE-NFE-{order['ronda']}"
    equipment = str(order["equipment"])
    location = str(order.get("location") or "OFICINA-NFE")
    work_type = "T"
    refers_to = str(order.get("refers_to") or "3 AVAIL")
    equipment_status = "NA"
    expected = [
        ("Ordem de Trabalho description", title, 0),
        ("Equipamento", equipment, 0),
        ("Local", location, 0),
        ("Refere-se a", refers_to, 0),
        ("Status do Equipamento", equipment_status, 0),
        ("Tipo de trabalho", work_type, 0),
    ]

    _fill(driver, "Ordem de Trabalho description", title)
    report("Título preenchido.")
    _set_long_description(driver, str(order["description_longdescription"]))
    report("Descrição longa preenchida.")
    _fill(driver, "Equipamento", equipment)
    report("Equipamento preenchido.")
    _fill(driver, "Local", location)
    report("Local preenchido.")
    _fill(driver, "Refere-se a", refers_to)
    report("Campo Refere-se a preenchido.")
    _fill(driver, "Status do Equipamento", equipment_status)
    report("Status do equipamento preenchido.")
    _fill(driver, "Tipo de trabalho", work_type)
    report("Tipo de trabalho preenchido.")
    _confirm_work_type_change(driver)
    report("Confirmação do tipo de trabalho concluída.")

    for index, person in enumerate(labor):
        _add_labor_row(driver, index)
        report(f"Linha de mão de obra {index + 1} adicionada.")
        values = [
            ("Mão de obra", str(person["laborcode"])),
            ("Data de início", str(order["start_date"])),
            ("Hora de início", str(order["start_time"])),
            ("End Date", str(order["end_date"])),
            ("Hora de término", str(order["end_time"])),
            ("Horas normais", f"{int(float(order['hours']))}:{round((float(order['hours']) % 1) * 60):02d}"),
        ]
        for label, value in values:
            _fill(driver, label, value, index)
            expected.append((label, value, index))
            report(f"{label} preenchido para {person['laborcode']}.")

    return expected


def create_ronda_work_order(
    driver,
    order: dict[str, Any],
    *,
    on_number=None,
    on_saved=None,
    on_completed=None,
    on_progress=None,
) -> str:
    labor = order.get("labor")
    if not isinstance(labor, list) or not labor:
        raise BMAServiceError("A OT de Ronda não possui executantes válidos.")
    if not order.get("equipment") or not order.get("description_longdescription"):
        raise BMAServiceError("A OT de Ronda está sem equipamento ou descrição longa.")

    number = _open_new_order(driver)
    if on_number:
        on_number(number)
    if on_progress:
        on_progress(f"RES {number} gerado; começando o preenchimento.")

    expected = fill_ronda_quick_report_fields(driver, order, labor, on_progress=on_progress)

    missing = _verify_fields(driver, expected)
    if missing:
        if on_progress:
            on_progress("Revalidando campos que o BMA não confirmou.")
        for label, value, index in missing:
            if label == "Tipo de trabalho":
                _fill(driver, label, value, index, skip_if_matches=True)
                _confirm_work_type_change(driver)
            else:
                _fill(driver, label, value, index, skip_if_matches=True)
        missing = _verify_fields(driver, expected)
    if missing:
        labels = ", ".join(dict.fromkeys(label for label, _value, _index in missing))
        raise BMAServiceError(f"Campos obrigatórios continuam sem confirmação: {labels}.")
    if on_progress:
        on_progress("Campos validados; salvando no BMA.")
    saved = _save(driver, number)
    if not saved:
        if on_progress:
            on_progress("BMA pediu campos adicionais; completando e salvando novamente.")
        missing = _missing_fields(driver, expected)
        for label, value, index in missing:
            if label == "Tipo de trabalho":
                _fill(driver, label, value, index, skip_if_matches=True)
                _confirm_work_type_change(driver)
            else:
                _fill(driver, label, value, index, skip_if_matches=True)
        missing = _verify_fields(driver, expected)
        if missing or not _save(driver, number):
            raise BMAServiceError("O BMA voltou a recusar o Save após preencher os campos pendentes.")
    if on_saved:
        on_saved(number)
    if on_progress:
        on_progress("OT salva; roteando o workflow para COMP.")
    _complete_workflow(driver)
    if on_completed:
        on_completed(number)
    if on_progress:
        on_progress(f"RES {number} concluído em COMP.")
    return number