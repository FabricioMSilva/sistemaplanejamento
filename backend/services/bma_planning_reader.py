"""Envio das OTs PM do cronograma ao BMA pela tela Rastrear Ordem de Trabalho."""

from copy import deepcopy
from datetime import date, datetime
import json
import logging
import os
from pathlib import Path
import sqlite3
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

from selenium.common.exceptions import (
    InvalidSessionIdException, NoSuchWindowException, TimeoutException, WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from models.database import listar_situacao_envios_bma, registrar_envio_bma
from services.BMAService import BMAService, BMAServiceError
from services.pcm_planning import get_plan, order_key, text

# OTs preventivas (PM) tratadas neste fluxo.
TIPOS_PM = {"I", "S"}
TIPOS_ENVIO = TIPOS_PM | {"E"}
# Corretivas nestes status recebem o planejamento e são roteadas no workflow até PREPARED.
STATUS_WORKFLOW = {"WFSCH", "WSCH"}
OPCAO_WORKFLOW_PREPARED = "Pronta para execução - PREPARED"
# Validado na observação: botão "Rotear Workflow" da barra de ferramentas.
BOTAO_ROTEAR_WORKFLOW = "ROUTEWF_BMA-WF-WO_-tbb_image"

PASTA_DIAGNOSTICO = Path(__file__).resolve().parents[1] / "uploads" / "bma_leitura"
log = logging.getLogger("bma_envio")
if not log.handlers:
    PASTA_DIAGNOSTICO.mkdir(parents=True, exist_ok=True)
    _handler = logging.FileHandler(PASTA_DIAGNOSTICO / "envio.log", encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)

# Seletores no formato (By.<TIPO>, "valor"). Os comentados como "validado" já são usados no projeto.
# Substitua "INSERIR_SELETOR_REAL" pelo seletor real; enquanto não substituído, usa-se a busca existente.
BMA_SELECTORS = {
    # Validado pelo usuário: input#quicksearch ("Find Ordem de Trabalho") dentro do iframe do Maximo; busca com ENTER.
    "campo_numero_ot": (By.ID, "quicksearch"),
    # Validado: usado por BmaPageMonitor._switch_to_manage_frame.
    "frame_maximo": (By.CSS_SELECTOR, 'iframe[name="manage-shell_Iframe"]'),
    # INSERIR_SELETOR_REAL: item de menu; hoje usa BmaPageMonitor._open_work_order_app (texto do menu).
    "menu_rastrear_ordem": "INSERIR_SELETOR_REAL",
    # INSERIR_SELETOR_REAL: botão de pesquisa; hoje a busca é enviada com ENTER no campo quicksearch.
    "botao_pesquisar": "INSERIR_SELETOR_REAL",
    # INSERIR_SELETOR_REAL: aviso de lista vazia; sem ele, OT inexistente é detectada pelo tempo limite.
    "mensagem_sem_resultado": "INSERIR_SELETOR_REAL",
}

# Rótulos dos campos da aba "Ordem de Trabalho" (comparação sem acento e sem maiúsculas).
# "validado" = rótulo já usado no fluxo de gravação; "CONFIRMAR" = confira em dados_adicionais.campos_ordem
# da primeira leitura e ajuste aqui o rótulo real exibido pelo Maximo.
CAMPOS_ORDEM = {
    "numero_ot": ("Ordem de Trabalho",),  # validado
    "status": ("Status da OT",),  # validado
    "inicio_planejado": ("Início planejado",),  # validado
    "termino_planejado": ("Final planejado",),  # validado
    "descricao": ("Descrição",),  # CONFIRMAR
    "tipo_ordem": ("Tipo de trabalho",),  # CONFIRMAR
    "equipamento": ("Ativo",),  # CONFIRMAR
    "localizacao": ("Local",),  # CONFIRMAR
    "inicio_desejado": ("Início desejado",),  # CONFIRMAR
    "termino_desejado": ("Término desejado",),  # CONFIRMAR
    "equipe_responsavel": ("Equipe",),  # CONFIRMAR
    "duracao_planejada": ("Duração",),  # CONFIRMAR
    "prioridade": ("Prioridade",),  # CONFIRMAR
}
# Colunas da grade da aba "Atribuições" (validadas em BmaPageMonitor._find_assignment_grid).
COLUNAS_ATRIBUICAO = ("mao de obra", "inicio planejado", "horas")
# Colunas da grade "Mão de obra" da aba "Preparação" (validadas pelo usuário).
COLUNAS_PREPARACAO = ("especialidade", "quantidade", "horas normais")
SITUACOES_PLANEJADOR = {"pendente_planejador"}
SITUACOES_PLANEJADAS = {"planejada", "ja_planejada"}
# Recarrega o Rastrear Ordem periodicamente para o Maximo não acumular memória em filas longas (até 200 OTs).
OTS_POR_RECARGA = 25
SITUACOES_ERRO = {"erro", "nao_encontrada"}

# Registra ações do usuário (cliques, alterações, teclas) e o estado da tela; não altera nada no Maximo.
JS_OBSERVAR = """
const rotulo = (el) => {
  if (!el || !el.getAttribute) return '';
  const ids = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
  return [el.getAttribute('aria-label'), ...ids.map((id) => document.getElementById(id)?.innerText || ''),
    el.getAttribute('title'), el.getAttribute('alt')].map((v) => String(v || '').trim()).find(Boolean) || '';
};
const visivel = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
if (!window.__bmaObs) {
  window.__bmaObs = [];
  const registrar = (tipo, el, extra) => window.__bmaObs.push({
    hora: new Date().toLocaleTimeString('pt-BR'), tipo, tag: el.tagName, id: el.id || '', rotulo: rotulo(el),
    texto: String(el.innerText || '').trim().slice(0, 100), valor: el.value ?? '', ...extra });
  document.addEventListener('click', (e) => registrar('clique',
    e.target.closest('a,button,[role=tab],[role=button],[role=menuitem],[role=option],input,select,li') || e.target), true);
  document.addEventListener('change', (e) => registrar('alteracao', e.target), true);
  document.addEventListener('keydown', (e) => {
    if (['Enter', 'Tab', 'Escape'].includes(e.key)) registrar('tecla', e.target, { tecla: e.key });
  }, true);
}
const campo = (nome) => Array.from(document.querySelectorAll('input')).find((el) =>
  visivel(el) && rotulo(el).trim().toLowerCase() === nome.toLowerCase());
const dialogos = Array.from(document.querySelectorAll('[role=dialog],[role=alertdialog],.dijitDialog'))
  .filter(visivel).map((d) => ({
    titulo: String(d.querySelector('[id$="_title"],.dijitDialogTitle,h1,h2,h3')?.innerText || '').trim(),
    texto: String(d.innerText || '').trim().slice(0, 400),
    campos: Object.fromEntries(Array.from(d.querySelectorAll('input,select,textarea')).filter(visivel)
      .map((el) => [rotulo(el) || el.id, el.value ?? ''])) }));
const aba = document.querySelector('[role=tab][aria-selected=true]');
return {
  eventos: window.__bmaObs.splice(0),
  estado: { ot: campo('Ordem de Trabalho')?.value || '', status: campo('Status da OT')?.value || '',
    inicio_planejado: campo('Início planejado')?.value || '', final_planejado: campo('Final planejado')?.value || '',
    aba: String(aba?.innerText || '').trim(), dialogos },
};
"""


class LeituraInterrompida(BMAServiceError):
    pass


class SessaoBmaExpirada(BMAServiceError):
    pass


class NavegadorIndisponivel(BMAServiceError):
    pass


class OtNaoEncontrada(BMAServiceError):
    pass


class FalhaGravacao(BMAServiceError):
    pass


class WorkflowIndisponivel(BMAServiceError):
    pass


def resultado_ot(numero_ot: str, **valores) -> dict:
    resultado = {
        "numero_ot": numero_ot, "descricao": "", "tipo_ordem": "", "status": "",
        "equipamento": "", "localizacao": "", "data_planejada": "", "inicio_planejado": "",
        "termino_planejado": "", "janela_execucao": "", "dia_execucao": "", "executor": "",
        "equipe_responsavel": "", "duracao_planejada": "", "prioridade": "",
        "dados_adicionais": {}, "situacao_consulta": "sucesso", "erro": None,
    }
    resultado.update(valores)
    return resultado


def obter_ots_do_cronograma(plan_id: str) -> list[dict]:
    """OTs PM (tipos I e S) alocadas ou posicionadas no cronograma salvo, em ordem de dia."""
    plano = get_plan(plan_id)
    ordens = {order_key(ordem): ordem for ordem in plano.get("ordens", [])}
    pessoas = {pessoa["id"]: pessoa for pessoa in plano.get("pessoas", [])}
    itens = [(bloco["dia"], bloco["ot"], bloco["executantes"], bloco["horas"])
             for bloco in plano.get("blocos", [])]
    itens += [(item["dia"], item["ot"], [item["executante"]], 0)
              for item in plano.get("posicionamentos") or []]
    agenda: dict[str, dict] = {}
    for dia, chave, executantes, horas in sorted(itens, key=lambda item: (str(item[0]), item[1])):
        ordem = ordens.get(chave)
        if not ordem or text(ordem, "worktype").strip().upper() not in TIPOS_ENVIO:
            continue
        numero = str(ordem.get("wonum", "")).strip().upper()
        if not numero or not all(caractere.isalnum() or caractere == "-" for caractere in numero):
            continue
        item = agenda.setdefault(chave, {
            "numero_ot": numero, "siteid": ordem.get("siteid", ""),
            "tipo": text(ordem, "worktype").strip().upper(),
            "cronograma": {"dias": [], "executantes": [], "horas": 0},
            "planejamento": {"inicio": str(dia), "fim": str(dia), "atribuicoes": [], "sem_matricula": []},
        })
        cronograma = item["cronograma"]
        planejamento = item["planejamento"]
        planejamento["fim"] = max(planejamento["fim"], str(dia))
        if str(dia) not in cronograma["dias"]:
            cronograma["dias"].append(str(dia))
        for executante in executantes:
            pessoa = pessoas.get(executante, {})
            nome = pessoa.get("nome", executante)
            matricula = str(pessoa.get("matricula", "")).strip().upper()
            if matricula:
                nome = f"{nome} ({matricula})"
            if nome not in cronograma["executantes"]:
                cronograma["executantes"].append(nome)
            if not matricula or not all(c.isalnum() or c == "-" for c in matricula):
                if nome not in planejamento["sem_matricula"]:
                    planejamento["sem_matricula"].append(nome)
            elif matricula not in {a["laborcode"] for a in planejamento["atribuicoes"]}:
                planejamento["atribuicoes"].append({"laborcode": matricula, "dia": str(dia)})
        cronograma["horas"] = round(cronograma["horas"] + float(horas or 0), 2)
    return list(agenda.values())


class PlanningReadMixin:
    """Fluxo de envio do planejamento incorporado ao BmaPageMonitor."""

    def enviar_planejamento(self, plan_id: str):
        ots = obter_ots_do_cronograma(plan_id)
        if not ots:
            raise BMAServiceError(
                "Nenhuma OT PM (tipos I e S) ou corretiva (tipo E) no cronograma salvo. Planeje e salve antes de enviar."
            )
        ja_planejadas = {item["numero_ot"] for item in listar_situacao_envios_bma(plan_id)
                         if item["situacao"] in SITUACOES_PLANEJADAS}
        ots = [ot for ot in ots if ot["numero_ot"] not in ja_planejadas]
        if not ots:
            raise BMAServiceError("Todas as OTs do cronograma já estão planejadas no BMA.")
        monitor_id, driver_reutilizavel = self._nova_sessao_bma({
            "mode": "planning_send", "inspection_only": False, "plan_id": plan_id,
            "selected_wonums": [ot["numero_ot"] for ot in ots], "queue_total": len(ots),
            "processadas": 0, "planejadas": 0, "pendentes": 0, "com_erro": 0, "resultados": [],
        }, reutilizar=False)
        Thread(
            target=self._executar_leitura_planejamento,
            args=(monitor_id, ots, driver_reutilizavel), daemon=True,
        ).start()
        return {"monitor_id": monitor_id, "total": len(ots)}

    def abrir_ot_bma(self, wonum: str):
        wonum = str(wonum or "").strip().upper()
        if not wonum or not all(c.isalnum() or c == "-" for c in wonum):
            raise BMAServiceError("Número da OT inválido.")
        monitor_id, driver_reutilizavel = self._nova_sessao_bma({
            "mode": "open_ot", "inspection_only": True, "selected_wonums": [wonum], "queue_total": 1,
            "current_wonum": wonum,
        })
        Thread(target=self._executar_abertura, args=(monitor_id, wonum, driver_reutilizavel), daemon=True).start()
        return {"monitor_id": monitor_id}

    def _executar_abertura(self, monitor_id: str, wonum: str, driver_existente=None):
        driver = None
        self._browser_lock.acquire()
        try:
            driver, reutilizado = self.iniciar_firefox_bma(monitor_id, driver_existente)
            self.acessar_rastreamento_ordem(monitor_id, driver, reutilizado)
            self._update(monitor_id, stage="reading_order", progress=50, message=f"Consultando OT {wonum}...")
            self.pesquisar_ot(monitor_id, driver, wonum)
            self._update(
                monitor_id, status="completed", stage="opened", progress=100, opened_wonum=wonum,
                message=f"OT {wonum} aberta no BMA para consulta. Nenhum dado foi alterado.",
            )
        except LeituraInterrompida:
            self._update(monitor_id, status="stopped", stage="stopped", message="Abertura interrompida.")
        except BaseException as exc:
            log.exception("[%s] abertura da OT %s falhou", monitor_id, wonum)
            self._update(monitor_id, status="failed", stage="failed", failed_wonum=wonum,
                         message=f"Não foi possível abrir a OT {wonum}: {exc}")
        finally:
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session:
                    session["driver"] = driver
            self._browser_lock.release()

    def iniciar_observacao(self):
        monitor_id, driver_reutilizavel = self._nova_sessao_bma({
            "mode": "observe", "inspection_only": True, "selected_wonums": [], "queue_total": 0,
            "eventos": 0,
        })
        Thread(target=self._executar_observacao, args=(monitor_id, driver_reutilizavel), daemon=True).start()
        return {"monitor_id": monitor_id}

    def _nova_sessao_bma(self, estado: dict, *, reutilizar: bool = True):
        driver_reutilizavel = None
        drivers_to_close = []
        with self._lock:
            for session in self._sessions.values():
                if session["state"]["status"] in {"starting", "monitoring", "stopping"}:
                    session["stop"].set()
                    if session.get("driver"):
                        drivers_to_close.append(session["driver"])
                    session["state"].update(status="stopping", message="Substituindo a sessão BMA.")
                elif reutilizar and session.get("driver") and driver_reutilizavel is None:
                    driver_reutilizavel = session["driver"]
                    session["driver"] = None
            monitor_id = uuid4().hex
            self._sessions[monitor_id] = {
                "state": {
                    "monitor_id": monitor_id, "status": "starting", "stage": "starting", "progress": 0,
                    "message": "Abrindo BMA...", "fields": [], "elapsed_seconds": 0,
                    "current_order_index": 0, "current_wonum": None, "completed_wonums": [],
                    "failed_wonum": None, "opened_wonum": None, "page_url": "", "page_title": "",
                    **estado,
                },
                "stop": Event(),
                "driver": None,
                "orders": [],
            }
        for driver in drivers_to_close:
            Thread(target=self._close_browser, args=(driver,), daemon=True).start()
        return monitor_id, driver_reutilizavel

    def _executar_observacao(self, monitor_id: str, driver_existente=None):
        driver = None
        self._browser_lock.acquire()
        try:
            driver, reutilizado = self.iniciar_firefox_bma(monitor_id, driver_existente)
            self.acessar_rastreamento_ordem(monitor_id, driver, reutilizado)
            log.info("[%s] observação iniciada", monitor_id)
            anterior, eventos = None, 0
            while True:
                self._verificar_interrupcao(monitor_id)
                try:
                    self._verificar_leitura(monitor_id, driver)
                    self._switch_to_manage_frame(driver)
                    dados = driver.execute_script(JS_OBSERVAR) or {}
                except SessaoBmaExpirada:
                    self._update(monitor_id, message="Observando: aguardando login/MFA no Firefox.")
                    sleep(2)
                    continue
                except (LeituraInterrompida, NavegadorIndisponivel):
                    raise
                except (BMAServiceError, WebDriverException):
                    sleep(1)
                    continue
                for evento in dados.get("eventos") or []:
                    eventos += 1
                    log.info("[obs] ACAO %s", json.dumps(evento, ensure_ascii=False))
                estado = dados.get("estado")
                if estado != anterior:
                    log.info("[obs] ESTADO %s", json.dumps(estado, ensure_ascii=False))
                    anterior = estado
                estado = estado or {}
                self._update(
                    monitor_id, status="monitoring", stage="observing", eventos=eventos,
                    current_wonum=estado.get("ot") or None,
                    message=(f"Observando: OT {estado.get('ot') or '—'} · status {estado.get('status') or '—'} · "
                             f"aba {estado.get('aba') or '—'} · {eventos} ação(ões) registrada(s)."),
                )
                sleep(1)
        except LeituraInterrompida:
            log.info("[%s] observação encerrada", monitor_id)
            self._update(monitor_id, status="stopped", stage="stopped", message="Observação encerrada.")
        except BaseException as exc:
            log.exception("[%s] observação falhou", monitor_id)
            self._update(monitor_id, status="failed", stage="failed", message=f"Observação interrompida: {exc}")
        finally:
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session:
                    session["driver"] = driver
            self._browser_lock.release()

    def _executar_leitura_planejamento(self, monitor_id: str, ots: list[dict], driver_existente=None):
        driver = None
        oculto = os.getenv("BMA_ENVIO_VISIVEL", "0") != "1"
        fechar_navegador = oculto
        started_at = monotonic()
        log.info("[%s] envio iniciado (%s): %s", monitor_id, "oculto" if oculto else "visível",
                 [ot["numero_ot"] for ot in ots])
        self._browser_lock.acquire()
        try:
            driver, reutilizado = self.iniciar_firefox_bma(monitor_id, driver_existente, headless=oculto)
            self.acessar_rastreamento_ordem(monitor_id, driver, reutilizado)
            resultados = self.processar_ots_do_cronograma(monitor_id, driver, ots)
            planejadas = sum(1 for item in resultados if item["situacao_consulta"] in SITUACOES_PLANEJADAS)
            pendentes = sum(1 for item in resultados if item["situacao_consulta"] in SITUACOES_PLANEJADOR)
            erros = sum(1 for item in resultados if item["situacao_consulta"] in SITUACOES_ERRO)
            self._update(
                monitor_id, status="completed", stage="completed", progress=100,
                elapsed_seconds=round(monotonic() - started_at),
                message=(f"Envio concluído: {planejadas} OT(s) planejada(s) no BMA, "
                         f"{pendentes} para o planejador revisar, {erros} com erro."),
            )
        except LeituraInterrompida:
            log.info("[%s] envio interrompido pelo usuário", monitor_id)
            fechar_navegador = True
            self._update(monitor_id, status="stopped", stage="stopped", message="Envio interrompido pelo usuário.")
        except BaseException as exc:
            log.exception("[%s] envio falhou", monitor_id)
            state = self.get(monitor_id) or {}
            self._update(
                monitor_id, status="failed", stage="failed", failed_wonum=state.get("current_wonum"),
                elapsed_seconds=round(monotonic() - started_at),
                message=(f"Envio interrompido: {exc} Confira a OT no BMA antes de reenviar."),
            )
        finally:
            if fechar_navegador and driver:
                self._close_browser(driver)
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session:
                    session["driver"] = None if fechar_navegador else driver
            self._browser_lock.release()

    def iniciar_firefox_bma(self, monitor_id: str, driver_existente=None, *, headless: bool = False):
        self._update(monitor_id, status="monitoring", stage="opening_browser", progress=2, message="Abrindo BMA...")
        if driver_existente:
            try:
                driver_existente.current_url
                self._registrar_driver(monitor_id, driver_existente)
                return driver_existente, True
            except WebDriverException:
                self._close_browser(driver_existente)
        service = BMAService()
        driver = service._create_browser(page_load_strategy="eager", headless=headless)
        self._registrar_driver(monitor_id, driver)
        driver.set_page_load_timeout(service.timeout)
        return driver, False

    def _registrar_driver(self, monitor_id: str, driver):
        with self._lock:
            session = self._sessions.get(monitor_id)
            if session:
                session["driver"] = driver

    def acessar_rastreamento_ordem(self, monitor_id: str, driver, reutilizado: bool = False):
        self._verificar_interrupcao(monitor_id)
        self._update(
            monitor_id, stage="opening_wotrack", progress=5, message="Acessando Rastrear Ordem de Trabalho...",
        )
        service = BMAService()
        driver.switch_to.default_content()
        if reutilizado and self._campo_busca(monitor_id, driver):
            driver.switch_to.default_content()
            return
        try:
            driver.get(service.wotrack_url)
        except TimeoutException:
            pass
        try:
            # Reaproveita o login/MFA existente (WebDriverWait até o campo quicksearch aparecer).
            service._wait_for_work_tracking(
                driver, lambda _stage, message, *_: self._update(monitor_id, stage="authenticating", message=message),
            )
        except BMAServiceError:
            self._verificar_interrupcao(monitor_id)
            driver.switch_to.default_content()
            if not self._abrir_menu_rastrear_ordem(driver):
                raise
            self._aguardar(
                driver, lambda d: self._campo_busca(monitor_id, d), service.timeout,
                "Rastrear Ordem de Trabalho não abriu pelo menu do Maximo.",
            )
        driver.switch_to.default_content()
        self._update(monitor_id, stage="wotrack_ready", progress=10,
                     page_url=driver.current_url, page_title=driver.title,
                     message="Rastrear Ordem de Trabalho aberto.")

    def _abrir_menu_rastrear_ordem(self, driver) -> bool:
        seletor = self._seletor("menu_rastrear_ordem")
        if seletor:
            elementos = [item for item in driver.find_elements(*seletor) if item.is_displayed()]
            if elementos:
                elementos[0].click()
                return True
            return False
        return self._open_work_order_app(driver)

    def pesquisar_ot(self, monitor_id: str, driver, numero_ot: str):
        timeout = BMAService().timeout
        sem_resultado = self._seletor("mensagem_sem_resultado")

        def resultado(d):
            self._verificar_leitura(monitor_id, d)
            d.switch_to.default_content()
            if self._current_order_number_in_frames(d) == numero_ot:
                return True, None
            d.switch_to.default_content()
            link = self._find_order_link(d, numero_ot)
            if link:
                return False, link
            if sem_resultado:
                self._switch_to_manage_frame(d)
                if any(item.is_displayed() for item in d.find_elements(*sem_resultado)):
                    raise OtNaoEncontrada(f"OT {numero_ot} não encontrada em Rastrear Ordem de Trabalho.")
            return False

        prazo = monotonic() + timeout
        for tentativa in range(1, 4):
            campo = self._aguardar(
                driver, lambda d: self._campo_busca(monitor_id, d), timeout,
                "O campo Find Ordem de Trabalho não ficou disponível.",
            )
            self._update(monitor_id, message=f"Consultando OT {numero_ot}... (busca {tentativa}/3)")
            self._digitar_busca(driver, campo, numero_ot)
            driver.switch_to.default_content()
            try:
                aberta, link = self._aguardar(
                    driver, resultado, max(5, min(20, prazo - monotonic())),
                    f"OT {numero_ot} não encontrada em Rastrear Ordem de Trabalho.", erro=OtNaoEncontrada,
                )
                break
            except OtNaoEncontrada:
                if tentativa == 3 or monotonic() >= prazo:
                    raise
        if not aberta:
            try:
                link.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click();", link)

        def detalhes_abertos(d):
            self._verificar_leitura(monitor_id, d)
            d.switch_to.default_content()
            return self._current_order_number_in_frames(d) == numero_ot

        self._aguardar(driver, detalhes_abertos, timeout, f"Os detalhes da OT {numero_ot} não abriram.")
        self._update(monitor_id, opened_wonum=numero_ot)

    def _ler_aba_ordem(self, monitor_id: str, driver, numero_ot: str) -> dict:
        visto = {}

        def aba_ordem(d):
            self._verificar_leitura(monitor_id, d)
            try:
                self._switch_to_manage_frame(d)
                self._click_tab(d, "Ordem de Trabalho")
            except BMAServiceError as exc:
                if visto.get("erro") != str(exc):
                    log.info("[%s] aba Ordem de Trabalho %s: %s", monitor_id, numero_ot, exc)
                visto["erro"] = str(exc)
                return False
            campos = self._ler_campos_rotulados(d)
            aberta = d.execute_script("""
                return Array.from(document.querySelectorAll('input')).some((element) =>
                  element.id !== 'quicksearch' && String(element.value || '').trim().toUpperCase() === arguments[0]);
            """, numero_ot)
            atual = dict(aberta=aberta, rotulos=list(campos)[:25])
            if atual != {k: visto.get(k) for k in atual}:
                log.info("[%s] aba Ordem de Trabalho %s: %s", monitor_id, numero_ot, atual)
            visto.update(atual)
            return campos if aberta and campos else False

        try:
            return self._aguardar(
                driver, aba_ordem, BMAService().timeout,
                f"Os campos da OT {numero_ot} não carregaram na aba Ordem de Trabalho.",
            )
        except BMAServiceError as exc:
            raise BMAServiceError(f"{exc} Diagnóstico: {visto}") from exc

    def _ler_grade_aba(self, monitor_id: str, driver, aba: str, colunas) -> dict:
        def grade(d):
            self._verificar_leitura(monitor_id, d)
            try:
                self._switch_to_manage_frame(d)
                self._click_tab(d, aba)
            except BMAServiceError:
                return False
            return self._ler_grade(d, colunas) or False

        return self._aguardar(driver, grade, 30, f"A grade da aba {aba} não carregou.")

    def planejar_ot(self, monitor_id: str, driver, ot: dict) -> dict:
        numero = ot["numero_ot"]
        plano = ot["planejamento"]
        atribuicoes = plano["atribuicoes"]

        def pendente(motivo, **valores):
            return resultado_ot(numero, situacao_consulta="pendente_planejador", erro=motivo, **valores)

        self.pesquisar_ot(monitor_id, driver, numero)
        driver._bma_messages = []
        self._update(monitor_id, stage="checking", message=f"OT {numero}: verificando Início e Final planejado...")
        campos = self._ler_aba_ordem(monitor_id, driver, numero)
        rotulos = {self._normalize_text(rotulo) for rotulo in campos}
        ausentes = [r[0] for r in (CAMPOS_ORDEM["inicio_planejado"], CAMPOS_ORDEM["termino_planejado"])
                    if self._normalize_text(r[0]) not in rotulos]
        if ausentes:
            raise BMAServiceError(f"Campo(s) {', '.join(ausentes)} não encontrado(s) na aba Ordem de Trabalho.")
        inicio = self._valor_campo(campos, CAMPOS_ORDEM["inicio_planejado"])
        termino = self._valor_campo(campos, CAMPOS_ORDEM["termino_planejado"])
        status = self._valor_campo(campos, CAMPOS_ORDEM["status"]).strip().upper()
        rotear = ot.get("tipo") == "E" and status in STATUS_WORKFLOW
        if ot.get("tipo") == "E" and status != "PREPARED" and not rotear:
            return pendente(f"Corretiva com status {status or 'não identificado'}; só PREPARED, WFSCH ou WSCH. OT não alterada.")
        if plano["sem_matricula"]:
            return pendente(f"Executante(s) sem matrícula válida no cronograma: {', '.join(plano['sem_matricula'])}.")

        self._update(monitor_id, message=f"OT {numero}: conferindo quantidade de mão de obra na Preparação...")
        preparacao = self._ler_grade_aba(monitor_id, driver, "Preparação", COLUNAS_PREPARACAO)
        quantidade = sum(self._numero(linha.get("quantidade")) for linha in preparacao["linhas"])
        matriculas = ", ".join(a["laborcode"] for a in atribuicoes)
        if quantidade != len(atribuicoes):
            return pendente(
                f"O BMA (Preparação) exige {quantidade} pessoa(s) e o cronograma tem {len(atribuicoes)} "
                f"matrícula(s) ({matriculas}). OT não alterada.",
            )
        grade = self._ler_grade_aba(monitor_id, driver, "Atribuições", COLUNAS_ATRIBUICAO)
        if len(grade["linhas"]) != len(atribuicoes):
            return pendente(
                f"A aba Atribuições tem {len(grade['linhas'])} linha(s) e o cronograma tem "
                f"{len(atribuicoes)} matrícula(s). OT não alterada.",
            )
        # O planejamento é a referência: o que já confere fica, o que diverge é corrigido.
        inicio_plano = datetime.fromisoformat(f"{plano['inicio']}T00:01:00")
        fim_plano = datetime.fromisoformat(f"{plano['fim']}T23:59:00")
        inicio_atual = self._parse_maximo_datetime(inicio)
        fim_atual = self._parse_maximo_datetime(termino)
        # O Maximo recalcula o Final planejado pela duração; basta ficar dentro do período planejado.
        datas_ok = inicio_atual == inicio_plano and bool(fim_atual) and inicio_plano <= fim_atual <= fim_plano
        existentes = [linha.get("mao de obra", "").strip().upper() for linha in grade["linhas"]]
        usadas, linhas_alvo, faltando = set(), [], []
        for atribuicao in atribuicoes:
            indice = next((i for i, codigo in enumerate(existentes)
                           if i not in usadas and codigo.startswith(atribuicao["laborcode"])), None)
            if indice is None:
                faltando.append(atribuicao)
                continue
            usadas.add(indice)
            data = self._parse_maximo_datetime(grade["linhas"][indice].get("inicio planejado"))
            if not data or data.date() != date.fromisoformat(atribuicao["dia"]):
                linhas_alvo.append((indice, atribuicao, False))
        livres = [i for i in range(len(existentes)) if i not in usadas]
        linhas_alvo += [(i, atribuicao, True) for i, atribuicao in zip(livres, faltando)]
        observacoes = [f"matrícula {existentes[i]} substituída por {a['laborcode']}"
                       for i, a, troca in linhas_alvo if troca and existentes[i]]
        if datas_ok and not linhas_alvo and not rotear:
            return resultado_ot(
                numero, situacao_consulta="ja_planejada", status=status, inicio_planejado=inicio,
                termino_planejado=termino, executor=", ".join(c for c in existentes if c),
                erro="Já estava conforme o planejamento (datas e matrículas). OT não alterada.",
            )

        try:
            if not datas_ok:
                self._update(monitor_id, stage="saving_dates",
                             message=f"OT {numero}: ajustando Início e Final planejado ao planejamento...")
                self._fill_general_dates(monitor_id, driver, {
                    "wonum": numero, "planned_start": inicio_plano.isoformat(), "planned_finish": fim_plano.isoformat(),
                })
                self._aguardar_salvamento(monitor_id, driver, f"datas da OT {numero}")
                if inicio or termino:
                    observacoes.append(f"datas {inicio or '—'} a {termino or '—'} ajustadas ao planejamento")
            if linhas_alvo:
                self._update(monitor_id, stage="saving_assignments",
                             message=f"OT {numero}: ajustando matrícula(s) {matriculas} em Atribuições...")
                self._ler_grade_aba(monitor_id, driver, "Atribuições", COLUNAS_ATRIBUICAO)
                for indice, atribuicao, preencher_matricula in linhas_alvo:
                    self._preencher_atribuicao(monitor_id, driver, indice, atribuicao, matricula=preencher_matricula)
                self._salvar_e_aguardar(monitor_id, driver, f"atribuições da OT {numero}")
            self._update(monitor_id, stage="verifying",
                         message=f"OT {numero}: conferindo datas planejadas em Atribuições...")
            self._conferir_atribuicoes(monitor_id, driver, numero, atribuicoes)
            aviso_workflow = None
            if rotear:
                self._update(monitor_id, stage="workflow",
                             message=f"OT {numero}: Rotear Workflow → {OPCAO_WORKFLOW_PREPARED}...")
                try:
                    self._rotear_workflow_prepared(monitor_id, driver, numero)
                except WorkflowIndisponivel as exc:
                    aviso_workflow = str(exc)
            final = self.extrair_dados_planejamento_ot(monitor_id, driver, numero)
        except (LeituraInterrompida, NavegadorIndisponivel):
            raise
        except (BMAServiceError, WebDriverException) as exc:
            detalhe = (str(exc).strip().splitlines() or [type(exc).__name__])[0][:240]
            raise FalhaGravacao(f"OT {numero}: falha ao gravar no BMA ({detalhe}).") from exc
        mensagens = list(getattr(driver, "_bma_messages", None) or [])
        if mensagens:
            final["dados_adicionais"]["mensagens_bma"] = mensagens
        if aviso_workflow:
            final.update(situacao_consulta="pendente_planejador", erro=aviso_workflow)
            return final
        final["situacao_consulta"] = "planejada"
        observacoes += [f"aviso do BMA {mensagem}" for mensagem in mensagens]
        if observacoes:
            final["dados_adicionais"]["observacoes"] = observacoes
            final["erro"] = f"Planejada com observações: {'; '.join(observacoes)}."
        return final

    def _dialogo_workflow(self, driver, acao: str):
        return driver.execute_script("""
            const visivel = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
            const norm = (v) => String(v || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const dialogo = Array.from(document.querySelectorAll('[role=dialog],[role=alertdialog],.dijitDialog'))
              .filter(visivel).pop();
            if (!dialogo) return null;
            const acao = arguments[0];
            if (acao === 'ler') return { texto: String(dialogo.innerText || '').trim().slice(0, 400) };
            const alvo = norm(acao.slice(6));
            if (acao.startsWith('opcao:')) {
              const label = Array.from(dialogo.querySelectorAll('label')).find((item) => norm(item.innerText) === alvo);
              if (!label) return { ok: false };
              const input = document.getElementById(label.getAttribute('for') || '')
                || document.getElementById(label.id.replace(/-lb1$/, '-rb'));
              return { ok: true, label, input };
            }
            const botao = Array.from(dialogo.querySelectorAll('button,[role=button]'))
              .find((item) => visivel(item) && norm(item.innerText) === alvo);
            return botao ? { ok: true, botao } : { ok: false };
        """, acao)

    def _rotear_workflow_prepared(self, monitor_id: str, driver, numero_ot: str):
        def botao_workflow(d):
            self._verificar_leitura(monitor_id, d)
            self._switch_to_manage_frame(d)
            return next((item for item in d.find_elements(By.ID, BOTAO_ROTEAR_WORKFLOW) if item.is_displayed()), None)

        def dialogo_aberto(d):
            self._verificar_leitura(monitor_id, d)
            self._switch_to_manage_frame(d)
            return self._dialogo_workflow(d, "ler")

        dialogo = None
        for tentativa in range(3):
            botao = self._aguardar(driver, botao_workflow, 30, "Botão Rotear Workflow não encontrado.")
            if tentativa == 0:
                self._click_when_idle(driver, botao)
            else:
                self._wait_maximo_idle(driver)
                driver.execute_script("(arguments[0].closest('a') || arguments[0]).click();", botao)
            try:
                dialogo = self._aguardar(driver, dialogo_aberto, 10, "A janela do workflow não abriu.")
                break
            except (LeituraInterrompida, NavegadorIndisponivel, SessaoBmaExpirada):
                raise
            except BMAServiceError:
                log.info("[%s] OT %s: janela do workflow não abriu (tentativa %s)", monitor_id, numero_ot, tentativa + 1)
        if not dialogo:
            raise BMAServiceError("A janela do workflow não abriu após 3 tentativas de clicar em Rotear Workflow.")
        log.info("[%s] OT %s workflow: %s", monitor_id, numero_ot, dialogo["texto"][:200])
        opcao = self._dialogo_workflow(driver, f"opcao:{OPCAO_WORKFLOW_PREPARED}")
        if not opcao or not opcao.get("ok"):
            cancelar = self._dialogo_workflow(driver, "botao:Cancelar")
            if cancelar and cancelar.get("ok"):
                self._click_when_idle(driver, cancelar["botao"])
            raise WorkflowIndisponivel(
                f"Datas e matrículas gravadas, mas o workflow não ofereceu '{OPCAO_WORKFLOW_PREPARED}' "
                f"(janela: {' '.join(dialogo['texto'].split())[:160]}). Workflow cancelado; conclua manualmente.",
            )
        self._click_when_idle(driver, opcao["label"])
        if opcao.get("input") and not opcao["input"].is_selected():
            self._click_when_idle(driver, opcao["input"])
        confirmar = self._dialogo_workflow(driver, "botao:OK")
        if not confirmar or not confirmar.get("ok"):
            raise BMAServiceError("Botão OK da janela do workflow não encontrado.")
        self._click_when_idle(driver, confirmar["botao"])
        ultimo = {}

        def preparado(d):
            self._verificar_leitura(monitor_id, d)
            self._switch_to_manage_frame(d)
            ultimo["dialogo"] = self._dialogo_workflow(d, "ler")
            ultimo["status"] = self._valor_campo(self._ler_campos_rotulados(d), CAMPOS_ORDEM["status"]).upper()
            return not ultimo["dialogo"] and ultimo["status"] == "PREPARED"

        try:
            self._aguardar(driver, preparado, 60, "O status não mudou para PREPARED após o workflow.")
        except BMAServiceError as exc:
            dialogo = (ultimo.get("dialogo") or {}).get("texto", "")
            raise BMAServiceError(
                f"{exc} Status atual: {ultimo.get('status') or '—'}."
                + (f" Janela aberta: {' '.join(dialogo.split())[:160]}" if dialogo else ""),
            ) from exc
        log.info("[%s] OT %s roteada para PREPARED", monitor_id, numero_ot)

    def _input_atribuicao(self, driver, linha: int, coluna: str):
        self._switch_to_manage_frame(driver)
        grade = self._ler_grade(driver, COLUNAS_ATRIBUICAO)
        if not grade or linha >= len(grade["linhas"]):
            return None
        celula = driver.find_element(
            By.ID, f"{grade['prefixo']}_tdrow_[C:{grade['colunas'][coluna]}]-c[R:{linha}]",
        )
        campos = celula.find_elements(By.CSS_SELECTOR, "input")
        return campos[0] if campos else None

    def _preencher_celula(self, monitor_id: str, driver, linha: int, coluna: str, valor: str, conferir):
        def campo(d):
            self._verificar_leitura(monitor_id, d)
            return self._input_atribuicao(d, linha, coluna)

        def aceito(d):
            self._verificar_leitura(monitor_id, d)
            return conferir(self._input_value(self._input_atribuicao(d, linha, coluna)))

        self._replace_input(self._aguardar(driver, campo, 30, f"Campo {coluna} da linha {linha + 1} ausente."), valor)
        self._aguardar(driver, aceito, 30, f"O BMA não aceitou '{valor}' em {coluna} (linha {linha + 1}).")

    def _preencher_atribuicao(self, monitor_id: str, driver, linha: int, atribuicao: dict, *, matricula=True):
        dia = date.fromisoformat(atribuicao["dia"])
        if matricula:
            self._preencher_celula(
                monitor_id, driver, linha, "mao de obra", atribuicao["laborcode"],
                lambda valor: valor.upper().startswith(atribuicao["laborcode"]),
            )
        self._preencher_celula(
            monitor_id, driver, linha, "inicio planejado", f"{dia.strftime('%d/%m/%Y')} 00:01",
            lambda valor: bool(data := self._parse_maximo_datetime(valor)) and data.date() == dia,
        )

    def _conferir_atribuicoes(self, monitor_id: str, driver, numero_ot: str, atribuicoes: list[dict]):
        for tentativa in (1, 2):
            linhas = self._ler_grade_aba(monitor_id, driver, "Atribuições", COLUNAS_ATRIBUICAO)["linhas"]
            divergentes = []
            for atribuicao in atribuicoes:
                indice = next((i for i, linha in enumerate(linhas)
                               if linha.get("mao de obra", "").upper().startswith(atribuicao["laborcode"])), None)
                if indice is None:
                    raise BMAServiceError(f"Matrícula {atribuicao['laborcode']} não ficou salva em Atribuições.")
                data = self._parse_maximo_datetime(linhas[indice].get("inicio planejado"))
                if not data or data.date() != date.fromisoformat(atribuicao["dia"]):
                    divergentes.append((indice, atribuicao))
            if not divergentes:
                return
            if tentativa == 2:
                raise BMAServiceError(
                    f"Data planejada divergente em Atribuições da OT {numero_ot} após salvar "
                    f"({', '.join(a['laborcode'] for _, a in divergentes)}).",
                )
            for indice, atribuicao in divergentes:
                self._preencher_atribuicao(monitor_id, driver, indice, atribuicao, matricula=False)
            self._salvar_e_aguardar(monitor_id, driver, f"datas das atribuições da OT {numero_ot}")

    def _salvar_e_aguardar(self, monitor_id: str, driver, contexto: str):
        self._save_current_order(driver)
        self._aguardar_salvamento(monitor_id, driver, contexto)

    def _aguardar_salvamento(self, monitor_id: str, driver, contexto: str):
        # O Maximo marca o disquete (toolactions_SAVE-tbb_anchor) como disabled quando não há alterações pendentes.
        def salvo(d):
            self._verificar_leitura(monitor_id, d)
            self._switch_to_manage_frame(d)
            if self._handle_maximo_message(d):
                return False
            botao = d.find_element(By.ID, "toolactions_SAVE-tbb_anchor")
            return botao.get_attribute("disabled") is not None or botao.get_attribute("aria-disabled") == "true"

        self._aguardar(
            driver, salvo, BMAService().timeout,
            f"O BMA não confirmou o salvamento ({contexto}); verifique mensagens na janela do Firefox.",
        )

    @staticmethod
    def _numero(valor) -> int:
        try:
            return int(float(str(valor or "0").replace(",", ".")))
        except ValueError:
            return 0

    def extrair_dados_planejamento_ot(self, monitor_id: str, driver, numero_ot: str) -> dict:
        timeout = BMAService().timeout
        campos = self._ler_aba_ordem(monitor_id, driver, numero_ot)

        def grade_atribuicoes(d):
            self._verificar_leitura(monitor_id, d)
            try:
                self._switch_to_manage_frame(d)
                self._click_tab(d, "Atribuições")
            except BMAServiceError:
                return False
            linhas = self._ler_atribuicoes(d)
            return ("ok", linhas) if linhas is not None else False

        atribuicoes, aviso = [], None
        try:
            _, atribuicoes = self._aguardar(
                driver, grade_atribuicoes, min(timeout, 20), "A grade de Atribuições não carregou.",
            )
        except (LeituraInterrompida, SessaoBmaExpirada, NavegadorIndisponivel):
            raise
        except BMAServiceError as exc:
            aviso = str(exc)

        def valor(chave):
            return self._valor_campo(campos, CAMPOS_ORDEM[chave])

        inicio, termino = valor("inicio_planejado"), valor("termino_planejado")
        inicio_desejado, termino_desejado = valor("inicio_desejado"), valor("termino_desejado")
        janela = (f"{inicio_desejado} a {termino_desejado}" if inicio_desejado and termino_desejado
                  else f"{inicio} a {termino}" if inicio and termino else "")
        executores = list(dict.fromkeys(item["laborcode"] for item in atribuicoes if item["laborcode"]))
        dias = list(dict.fromkeys(self._dia_maximo(item["inicio"]) for item in atribuicoes if item["inicio"]))
        adicionais = {"campos_ordem": campos, "atribuicoes": atribuicoes}
        if aviso:
            adicionais["aviso_atribuicoes"] = aviso
        return resultado_ot(
            numero_ot,
            descricao=valor("descricao"), tipo_ordem=valor("tipo_ordem"), status=valor("status"),
            equipamento=valor("equipamento"), localizacao=valor("localizacao"),
            data_planejada=inicio_desejado or self._dia_maximo(inicio),
            inicio_planejado=inicio, termino_planejado=termino, janela_execucao=janela,
            dia_execucao=", ".join(dias), executor=", ".join(executores),
            equipe_responsavel=valor("equipe_responsavel"), duracao_planejada=valor("duracao_planejada"),
            prioridade=valor("prioridade"), dados_adicionais=adicionais,
        )

    def processar_ots_do_cronograma(self, monitor_id: str, driver, ots: list[dict]) -> list[dict]:
        resultados = []
        total = len(ots)
        envio = self.get(monitor_id) or {}
        for indice, ot in enumerate(ots, start=1):
            self._verificar_interrupcao(monitor_id)
            numero = ot["numero_ot"]
            if indice > 1 and (indice - 1) % OTS_POR_RECARGA == 0:
                self.acessar_rastreamento_ordem(monitor_id, driver)
            self._update(
                monitor_id, stage="reading_order", current_order_index=indice, current_wonum=numero,
                progress=10 + round(88 * (indice - 1) / total), message=f"Consultando OT {numero}...",
            )
            for tentativa in (1, 2):
                try:
                    resultado = self.planejar_ot(monitor_id, driver, ot)
                    break
                except SessaoBmaExpirada:
                    if tentativa == 2:
                        raise
                    self._update(monitor_id, stage="authenticating", message=(
                        f"Sessão do BMA expirou durante a OT {numero}. "
                        "Conclua o login/MFA no Firefox; o envio continuará."
                    ))
                    self.acessar_rastreamento_ordem(monitor_id, driver)
                except (LeituraInterrompida, NavegadorIndisponivel):
                    raise
                except FalhaGravacao as exc:
                    resultado = resultado_ot(numero, situacao_consulta="erro", erro=str(exc))
                    break
                except OtNaoEncontrada as exc:
                    resultado = resultado_ot(numero, situacao_consulta="nao_encontrada", erro=str(exc))
                    break
                except (BMAServiceError, WebDriverException) as exc:
                    detalhe = (str(exc).strip().splitlines() or [type(exc).__name__])[0][:240]
                    resultado = resultado_ot(numero, situacao_consulta="erro", erro=detalhe)
                    break
            resultado["dados_adicionais"]["cronograma_local"] = ot["cronograma"]
            if resultado["situacao_consulta"] in SITUACOES_ERRO:
                resultado["dados_adicionais"]["captura_tela"] = self._salvar_captura(driver, numero)
            try:
                registrar_envio_bma(monitor_id, envio.get("plan_id", ""), resultado)
            except sqlite3.Error as exc:
                resultado["dados_adicionais"]["aviso_historico"] = f"Histórico não gravado: {exc}"
            resultados.append(resultado)
            log.info("[%s] OT %s: %s - %s", monitor_id, numero, resultado["situacao_consulta"], resultado["erro"])
            situacoes = [item["situacao_consulta"] for item in resultados]
            self._update(
                monitor_id, processadas=len(resultados), resultados=deepcopy(resultados),
                planejadas=sum(1 for s in situacoes if s in SITUACOES_PLANEJADAS),
                pendentes=sum(1 for s in situacoes if s in SITUACOES_PLANEJADOR),
                com_erro=sum(1 for s in situacoes if s in SITUACOES_ERRO),
                completed_wonums=[item["numero_ot"] for item in resultados if item["situacao_consulta"] == "planejada"],
                message=f"OT {numero}: {resultado['erro'] or 'planejada e conferida no BMA'}",
            )
            if resultado["situacao_consulta"] == "erro" and indice < total:
                self._recuperar_tela(monitor_id, driver, numero)
        return resultados

    def _recuperar_tela(self, monitor_id: str, driver, numero_ot: str):
        # Recarregar o Rastrear Ordem descarta alterações não salvas e janelas abertas da OT com erro.
        log.info("[%s] recuperando a tela após erro na OT %s", monitor_id, numero_ot)
        try:
            driver.switch_to.alert.accept()
        except WebDriverException:
            pass
        try:
            self.acessar_rastreamento_ordem(monitor_id, driver)
        except (LeituraInterrompida, NavegadorIndisponivel):
            raise
        except (BMAServiceError, WebDriverException) as exc:
            raise BMAServiceError(f"Não foi possível recuperar o BMA após o erro na OT {numero_ot}: {exc}") from exc

    def _campo_busca(self, monitor_id: str, driver):
        self._verificar_leitura(monitor_id, driver)
        try:
            self._switch_to_manage_frame(driver)
        except BMAServiceError:
            driver.switch_to.default_content()
            return self._find_order_filter(driver)
        campos = driver.find_elements(*BMA_SELECTORS["campo_numero_ot"])
        if not campos:
            return False
        campo = campos[0]
        if not campo.is_displayed():
            # O Maximo deixa #quicksearch_wrapper com visibility:hidden/opacity:0 até o hover na barra.
            driver.execute_script("""
                const wrapper = arguments[0].closest('#quicksearch_wrapper') || arguments[0].parentElement;
                wrapper.style.visibility = 'visible';
                wrapper.style.opacity = '1';
            """, campo)
        return campo if campo.is_displayed() and campo.is_enabled() else False

    def _digitar_busca(self, driver, campo, numero_ot: str):
        # bound="true" indica que o Maximo já ligou os eventos do campo; antes disso o texto é descartado.
        try:
            WebDriverWait(driver, 15, poll_frequency=0.25).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
                and campo.get_attribute("bound") == "true",
            )
        except TimeoutException:
            pass
        botao = self._seletor("botao_pesquisar")
        self._wait_maximo_idle(driver)
        try:
            campo.click()
        except WebDriverException:
            driver.execute_script("arguments[0].focus();", campo)
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(numero_ot)
        try:
            WebDriverWait(driver, 5, poll_frequency=0.25).until(
                lambda _d: (campo.get_attribute("value") or "").strip().upper() == numero_ot,
            )
        except TimeoutException:
            driver.execute_script("""
                const field = arguments[0];
                field.focus();
                field.value = arguments[1];
                field.dispatchEvent(new Event('input', { bubbles: true }));
                field.dispatchEvent(new Event('change', { bubbles: true }));
            """, campo, numero_ot)
        if botao:
            driver.find_element(*botao).click()
        else:
            campo.send_keys(Keys.ENTER)

    @staticmethod
    def _salvar_captura(driver, numero_ot: str):
        pasta = Path(__file__).resolve().parents[1] / "uploads" / "bma_leitura"
        try:
            pasta.mkdir(parents=True, exist_ok=True)
            driver.switch_to.default_content()
            caminho = pasta / f"{numero_ot}.png"
            driver.save_screenshot(str(caminho))
            return str(caminho)
        except (OSError, WebDriverException):
            return None

    def _verificar_interrupcao(self, monitor_id: str):
        with self._lock:
            session = self._sessions.get(monitor_id)
            if not session or session["stop"].is_set():
                raise LeituraInterrompida("Leitura interrompida pelo usuário.")

    def _verificar_leitura(self, monitor_id: str, driver):
        self._verificar_interrupcao(monitor_id)
        try:
            url = driver.current_url
        except (NoSuchWindowException, InvalidSessionIdException) as exc:
            raise NavegadorIndisponivel("A janela do Firefox usada pela leitura foi fechada.") from exc
        if "auth.rbmanca4" in url or "login-fed.michelin.com" in url:
            raise SessaoBmaExpirada("A sessão do BMA expirou; é necessário refazer o login/MFA.")

    @staticmethod
    def _aguardar(driver, condicao, timeout, mensagem, erro=BMAServiceError):
        try:
            return WebDriverWait(
                driver, timeout, poll_frequency=0.5, ignored_exceptions=(WebDriverException,),
            ).until(condicao)
        except TimeoutException as exc:
            raise erro(mensagem) from exc

    @staticmethod
    def _seletor(nome: str):
        valor = BMA_SELECTORS.get(nome)
        return valor if isinstance(valor, tuple) else None

    def _valor_campo(self, campos: dict, rotulos) -> str:
        normalizados = {self._normalize_text(rotulo): valor for rotulo, valor in campos.items()}
        return next((normalizados[chave] for chave in map(self._normalize_text, rotulos)
                     if normalizados.get(chave)), "")

    def _dia_maximo(self, valor: str) -> str:
        data = self._parse_maximo_datetime(valor)
        return data.strftime("%d/%m/%Y") if data else str(valor or "")

    @staticmethod
    def _ler_campos_rotulados(driver) -> dict:
        return driver.execute_script("""
            const campos = {};
            for (const element of document.querySelectorAll('input, textarea, select')) {
              const rect = element.getBoundingClientRect();
              if (!rect.width || !rect.height || /_tdrow_/.test(element.id || '')) continue;
              const ids = (element.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
              const labels = [element.getAttribute('aria-label'),
                ...(element.labels ? Array.from(element.labels).map((item) => item.innerText) : []),
                ...ids.map((id) => document.getElementById(id)?.innerText || ''),
                element.getAttribute('title')].map((item) => String(item || '').trim()).filter(Boolean);
              const value = element.tagName === 'SELECT'
                ? element.options[element.selectedIndex]?.text || '' : element.value || '';
              for (const label of labels) if (!campos[label]) campos[label] = String(value).trim();
            }
            return campos;
        """) or {}

    @staticmethod
    def _ler_grade(driver, colunas):
        # Grades do Maximo: cabeçalho "<prefixo>_ttrow_[C:n]-c" e células "<prefixo>_tdrow_[C:n]-c[R:r]".
        return driver.execute_script("""
            const norm = (value) => String(value || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
              .trim().toLowerCase().replace(/\\s+/g, ' ');
            const wanted = arguments[0];
            const grids = {};
            for (const header of document.querySelectorAll('[id*="_ttrow_[C:"]')) {
              const match = header.id.match(/^(.+)_ttrow_\\[C:(\\d+)\\]-c$/);
              const rect = header.getBoundingClientRect();
              if (!match || !rect.width || !rect.height) continue;
              (grids[match[1]] = grids[match[1]] || {})[norm(header.innerText)] = Number(match[2]);
            }
            for (const [prefixo, colunas] of Object.entries(grids)) {
              if (!wanted.every((label) => label in colunas)) continue;
              const linhas = [];
              for (let r = 0; r < 500; r++) {
                const cell = (c) => document.getElementById(`${prefixo}_tdrow_[C:${c}]-c[R:${r}]`);
                if (!cell(colunas[wanted[0]])) break;
                const linha = {};
                for (const [label, c] of Object.entries(colunas)) {
                  const element = cell(c);
                  if (!element || !label) continue;
                  const input = element.querySelector('input, textarea, select');
                  linha[label] = String(input ? input.value : element.innerText || '').trim();
                }
                linhas.push(linha);
              }
              return { prefixo, colunas, linhas };
            }
            return null;
        """, list(colunas))

    def _ler_atribuicoes(self, driver):
        grade = self._ler_grade(driver, COLUNAS_ATRIBUICAO)
        if grade is None:
            return None
        return [
            {"laborcode": linha["mao de obra"].upper(), "inicio": linha.get("inicio planejado", ""),
             "horas": linha.get("horas", ""), "colunas": linha}
            for linha in grade["linhas"]
            if linha.get("mao de obra") and all(c.isalnum() or c == "-" for c in linha["mao de obra"])
        ]
