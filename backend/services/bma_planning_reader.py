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
from services.pcm_planning import get_plan, import_bma_schedule, order_key, text
from utils.runtime_paths import uploads_dir

# OTs preventivas (PM) tratadas neste fluxo.
TIPOS_PM = {"I", "S"}
TIPOS_ENVIO = TIPOS_PM | {"E"}
# OTs nestes status recebem o planejamento e podem ter o status alterado para PREPARED.
STATUS_WORKFLOW = {"WFSCH", "WSCH"}
MAX_ASSIGNMENTS_PER_ORDER = 5
PREPARED_STATUS_OPTION = 'a[id$="_ns_menu_PREPARED_OPTION_a"]'

PASTA_DIAGNOSTICO = uploads_dir() / "bma_leitura"
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
    "inicio_desejado": ("Não iniciar antes de", "Início desejado"),
    "termino_desejado": ("Terminar antes de", "Término desejado"),
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
STATUS_TERMINAIS = {"COMP", "CLOSE", "CAN", "CANCELADA"}
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


class MatriculaNaoConfirmada(BMAServiceError):
    pass


class WorkflowIndisponivel(BMAServiceError):
    pass


def resultado_ot(numero_ot: str, **valores) -> dict:
    resultado = {
        "numero_ot": numero_ot, "descricao": "", "tipo_ordem": "", "status": "",
        "equipamento": "", "localizacao": "", "data_planejada": "", "inicio_planejado": "",
        "termino_planejado": "", "janela_execucao": "", "dia_execucao": "", "executor": "",
        "equipe_responsavel": "", "duracao_planejada": "", "prioridade": "",
        "dados_adicionais": {}, "requisitos_mao_de_obra": [],
        "situacao_consulta": "sucesso", "erro": None,
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

    def importar_planejamento_bma(self, plan_id: str):
        plan = get_plan(plan_id)
        if plan["status"] != "rascunho":
            raise BMAServiceError("Importe o planejamento do BMA em um rascunho não confirmado.")
        monitor_id, driver_reutilizavel = self._nova_sessao_bma({
            "mode": "planning_import", "inspection_only": True, "plan_id": plan_id,
            "selected_wonums": [], "queue_total": 0,
            "processadas": 0, "com_erro": 0, "importadas": [], "avisos_importacao": [],
            "import_applied": False, "resultados": [],
        }, reutilizar=False)
        Thread(
            target=self._executar_importacao_planejamento_bma,
            args=(monitor_id, plan_id, plan["setores"], plan["inicio"], plan["fim"], driver_reutilizavel), daemon=True,
        ).start()
        return {"monitor_id": monitor_id, "total": 0}

    def _executar_importacao_planejamento_bma(
        self, monitor_id: str, plan_id: str, setores: list[str], inicio: str, fim: str, driver_existente=None,
    ):
        driver = None
        hidden = os.getenv("BMA_ENVIO_VISIVEL", "1") != "1"
        close_browser = hidden
        started_at = monotonic()
        self._browser_lock.acquire()
        try:
            driver, reused = self.iniciar_firefox_bma(monitor_id, driver_existente, headless=hidden)
            self.acessar_rastreamento_ordem(monitor_id, driver, reused)
            service = BMAService()
            ots = service.coletar_ots_programadas(
                setores, inicio, fim,
                lambda stage, message, page, count: self._update(
                    monitor_id, stage=stage, page_atual=page, message=message,
                    progress=max(5, min(10, 5 + (page or 0))),
                ),
                driver=driver,
            )
            self._update(
                monitor_id, queue_total=len(ots), selected_wonums=[order["wonum"] for order in ots],
                progress=10, message=f"{len(ots)} OT(s) programada(s) encontradas no BMA para o período.",
            )
            if not ots:
                self._update(
                    monitor_id, status="completed", stage="completed", progress=100,
                    elapsed_seconds=round(monotonic() - started_at),
                    message="Nenhuma OT programada foi encontrada no BMA com os filtros selecionados.",
                )
                return
            results = []
            for index, order in enumerate(ots, start=1):
                self._verificar_interrupcao(monitor_id)
                number = order["wonum"]
                if index > 1 and (index - 1) % OTS_POR_RECARGA == 0:
                    self.acessar_rastreamento_ordem(monitor_id, driver)
                self._update(
                    monitor_id, stage="reading_order", current_order_index=index, current_wonum=number,
                    progress=10 + round(80 * (index - 1) / len(ots)),
                    message=f"Lendo programação da OT {number} no BMA...",
                )
                try:
                    for attempt in (1, 2):
                        try:
                            self.pesquisar_ot(monitor_id, driver, number)
                            result = self.extrair_dados_planejamento_ot(monitor_id, driver, number)
                            result["siteid"] = order["siteid"]
                            result["ordem_bma"] = order
                            result["status"] = result.get("status") or text(order, "status")
                            result["inicio_planejado"] = result.get("inicio_planejado") or text(order, "schedstart")
                            result["termino_planejado"] = result.get("termino_planejado") or text(order, "schedfinish")
                            result["duracao_planejada"] = result.get("duracao_planejada") or text(order, "estdur")
                            result["situacao_consulta"] = "sucesso"
                            break
                        except SessaoBmaExpirada:
                            if attempt == 2:
                                raise
                            self._update(
                                monitor_id, stage="authenticating",
                                message="Sessão BMA expirada. Conclua o login/MFA; a leitura continuará.",
                            )
                            self.acessar_rastreamento_ordem(monitor_id, driver)
                except (LeituraInterrompida, NavegadorIndisponivel):
                    raise
                except (BMAServiceError, WebDriverException) as exc:
                    detail = (str(exc).strip().splitlines() or [type(exc).__name__])[0][:240]
                    result = resultado_ot(number, situacao_consulta="erro", erro=detail)
                    if index < len(ots):
                        self._recuperar_tela(monitor_id, driver, number)
                results.append(result)
                errors = sum(item["situacao_consulta"] == "erro" for item in results)
                self._update(
                    monitor_id, processadas=len(results), com_erro=errors, resultados=deepcopy(results),
                    progress=10 + round(80 * len(results) / len(ots)),
                    message=f"OT {number}: {result.get('erro') or 'programação lida.'}",
                )
            self._update(
                monitor_id, status="completed", stage="completed", progress=100,
                elapsed_seconds=round(monotonic() - started_at),
                message=(f"Leitura concluída: {len(results)} OT(s) coletada(s). Revise os dados e clique em "
                         "Colocar no cronograma para aplicar as atribuições localmente. Nenhuma alteração foi enviada ao BMA."),
            )
        except LeituraInterrompida:
            close_browser = True
            self._update(monitor_id, status="stopped", stage="stopped", message="Importação cancelada; plano local não alterado.")
        except BaseException as exc:
            log.exception("[%s] importação reversa do BMA falhou", monitor_id)
            self._update(
                monitor_id, status="failed", stage="failed", failed_wonum=(self.get(monitor_id) or {}).get("current_wonum"),
                elapsed_seconds=round(monotonic() - started_at), message=f"Importação interrompida: {exc}",
            )
        finally:
            if close_browser and driver:
                self._close_browser(driver)
            with self._lock:
                session = self._sessions.get(monitor_id)
                if session:
                    session["driver"] = None if close_browser else driver
            self._browser_lock.release()

    def aplicar_importacao_planejamento_bma(self, monitor_id: str, plan_id: str):
        with self._lock:
            session = self._sessions.get(monitor_id)
            if not session:
                raise BMAServiceError("A coleta do BMA não foi encontrada. Faça uma nova leitura.")
            state = session["state"]
            if state.get("mode") != "planning_import" or state.get("plan_id") != plan_id:
                raise BMAServiceError("A coleta não pertence a este planejamento.")
            if state.get("status") != "completed":
                raise BMAServiceError("Aguarde a coleta das OTs terminar antes de colocá-las no cronograma.")
            if state.get("import_applied"):
                return deepcopy(state)

            imported = import_bma_schedule(plan_id, deepcopy(state.get("resultados", [])))
            state.update(
                importadas=imported["importadas"], avisos_importacao=imported["avisos"],
                plan_revision=imported["plano"]["revisao"], import_applied=True,
                message=(f"Cronograma atualizado: {len(imported['importadas'])} OT(s) colocada(s) localmente; "
                         f"{len(imported['avisos'])} aviso(s). Nenhuma alteração foi enviada ao BMA."),
            )
            return deepcopy(state)

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
        oculto = os.getenv("BMA_ENVIO_VISIVEL", "1") != "1"
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

    def acessar_rastreamento_ordem(
        self, monitor_id: str, driver, reutilizado: bool = False, *, service: BMAService | None = None,
    ):
        self._verificar_interrupcao(monitor_id)
        self._update(
            monitor_id, stage="opening_wotrack", progress=5, message="Acessando Rastrear Ordem de Trabalho...",
        )
        service = service or BMAService()
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
        if status in STATUS_TERMINAIS:
            return pendente(f"OT com status {status}; não será alterada. Revise o estado no BMA.", status=status)
        rotear = status in STATUS_WORKFLOW
        if ot.get("tipo") == "E" and status not in {"PREPARED", "INPRG", *STATUS_WORKFLOW}:
            return pendente(f"Corretiva com status {status or 'não identificado'}; só PREPARED, WFSCH ou WSCH. OT não alterada.")
        grade = None
        if status == "INPRG":
            grade = self._ler_grade_aba(monitor_id, driver, "Atribuições", COLUNAS_ATRIBUICAO)
            executores_em_execucao = [linha.get("mao de obra", "").strip().upper() for linha in grade["linhas"]]
            if (self._parse_maximo_datetime(inicio) and self._parse_maximo_datetime(termino)
                    and any(executores_em_execucao)):
                return resultado_ot(
                    numero, situacao_consulta="ja_planejada", status=status, inicio_planejado=inicio,
                    termino_planejado=termino, executor=", ".join(c for c in executores_em_execucao if c),
                    erro="OT em execução com período planejado e executante informado; nenhuma alteração feita.",
                )
            return pendente(
                "OT INPRG sem início, fim ou executante completo; não será alterada durante a execução.",
                status=status,
            )
        if plano["sem_matricula"]:
            return pendente(f"Executante(s) sem matrícula válida no cronograma: {', '.join(plano['sem_matricula'])}.")

        self._update(monitor_id, message=f"OT {numero}: conferindo quantidade de mão de obra na Preparação...")
        preparacao = self._ler_grade_aba(monitor_id, driver, "Preparação", COLUNAS_PREPARACAO)
        quantidade = sum(self._numero(linha.get("quantidade")) for linha in preparacao["linhas"])
        requisitos_mao_de_obra = [{
            "especialidade": str(linha.get("especialidade") or "").strip(),
            "orgid": str(linha.get("orgid") or "").strip(),
            "quantidade": self._numero(linha.get("quantidade")),
            "horas_normais": str(linha.get("horas normais") or "").strip(),
        } for linha in preparacao["linhas"]]
        matriculas = ", ".join(a["laborcode"] for a in atribuicoes)
        if quantidade > MAX_ASSIGNMENTS_PER_ORDER:
            return pendente(
                f"O BMA exige {quantidade} pessoas, acima do limite automatizado de "
                f"{MAX_ASSIGNMENTS_PER_ORDER}. OT não alterada.",
                requisitos_mao_de_obra=requisitos_mao_de_obra,
            )
        if quantidade != len(atribuicoes):
            return pendente(
                f"O BMA (Preparação) exige {quantidade} pessoa(s) e o cronograma tem {len(atribuicoes)} "
                f"matrícula(s) ({matriculas}). OT não alterada.",
                requisitos_mao_de_obra=requisitos_mao_de_obra,
            )
        grade = grade or self._ler_grade_aba(monitor_id, driver, "Atribuições", COLUNAS_ATRIBUICAO)
        if len(grade["linhas"]) < len(atribuicoes):
            try:
                grade = self._garantir_linhas_atribuicao(monitor_id, driver, numero, len(atribuicoes))
            except BMAServiceError as exc:
                return pendente(
                    f"Não foi possível preparar linhas suficientes em Atribuições: {exc}",
                    status=status, requisitos_mao_de_obra=requisitos_mao_de_obra,
                )
        if len(grade["linhas"]) < len(atribuicoes):
            return pendente(
                f"A aba Atribuições ficou com {len(grade['linhas'])} linha(s) e o cronograma tem "
                f"{len(atribuicoes)} matrícula(s). OT não alterada.",
                requisitos_mao_de_obra=requisitos_mao_de_obra,
            )
        # O planejamento é a referência: o que já confere fica, o que diverge é corrigido.
        inicio_plano = datetime.fromisoformat(f"{plano['inicio']}T00:01:00")
        fim_plano = datetime.fromisoformat(f"{plano['fim']}T23:59:00")
        inicio_atual = self._parse_maximo_datetime(inicio)
        fim_atual = self._parse_maximo_datetime(termino)
        # O Maximo recalcula o Final planejado pela duração; basta ficar dentro do período planejado.
        datas_ok = inicio_atual == inicio_plano and fim_atual == fim_plano
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
        if (status in {"PREPARED", *STATUS_WORKFLOW} and inicio_atual and fim_atual
                and not faltando):
            return resultado_ot(
                numero, situacao_consulta="ja_planejada", status=status, inicio_planejado=inicio,
                termino_planejado=termino, executor=", ".join(c for c in existentes if c),
                erro="Datas e matrículas do cronograma já preenchidas. OT não alterada.",
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
                for posicao, (indice, atribuicao, preencher_matricula) in enumerate(linhas_alvo, start=1):
                    self._update(
                        monitor_id,
                        message=f"OT {numero}: executante {posicao}/{len(linhas_alvo)} "
                        f"({atribuicao['laborcode']}) na linha {indice + 1} de Atribuições...",
                    )
                    self._preencher_atribuicao(monitor_id, driver, indice, atribuicao, matricula=preencher_matricula)
                self._salvar_e_aguardar(monitor_id, driver, f"atribuições da OT {numero}")
            self._update(monitor_id, stage="verifying",
                         message=f"OT {numero}: conferindo datas planejadas em Atribuições...")
            self._conferir_atribuicoes(monitor_id, driver, numero, atribuicoes)
            aviso_workflow = None
            if rotear:
                self._update(monitor_id, stage="workflow",
                             message=f"OT {numero}: Alterar Status para Prepared...")
                try:
                    self._alterar_status_prepared(monitor_id, driver, numero)
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
        status_final = str(final.get("status") or "").strip().upper()
        if status_final not in {"PREPARED", "INPRG"}:
            final.update(
                situacao_consulta="pendente_planejador",
                erro=f"Dados conferidos, mas status final {status_final or 'não identificado'} não é PREPARED.",
            )
            return final
        final["situacao_consulta"] = "planejada"
        observacoes += [f"aviso do BMA {mensagem}" for mensagem in mensagens]
        if observacoes:
            final["dados_adicionais"]["observacoes"] = observacoes
            final["erro"] = f"Planejada com observações: {'; '.join(observacoes)}."
        return final

    def _garantir_linhas_atribuicao(self, monitor_id: str, driver, numero_ot: str, quantidade: int) -> dict:
        if quantidade > MAX_ASSIGNMENTS_PER_ORDER:
            raise BMAServiceError(
                f"A OT {numero_ot} exige {quantidade} linhas, acima do limite de {MAX_ASSIGNMENTS_PER_ORDER}.",
            )
        self._verificar_leitura(monitor_id, driver)
        self._switch_to_manage_frame(driver)
        self._click_tab(driver, "Atribuições")
        grade = self._find_assignment_grid(driver)
        while len(grade[2]) < quantidade:
            anterior = len(grade[2])
            botao = next((element for element in driver.find_elements(
                By.CSS_SELECTOR, 'a[title="New Row"]',
            ) if element.is_displayed() and element.is_enabled()), None)
            if not botao:
                raise BMAServiceError(f"Não foi possível adicionar linha de atribuição na OT {numero_ot}.")
            self._click_when_idle(driver, botao)

            def nova_linha(d):
                self._verificar_leitura(monitor_id, d)
                self._switch_to_manage_frame(d)
                self._click_tab(d, "Atribuições")
                atual = self._find_assignment_grid(d)
                return atual if len(atual[2]) > anterior else False

            grade = self._aguardar(
                driver, nova_linha, 30,
                f"A nova linha de atribuição não apareceu na OT {numero_ot}.",
            )
        self._switch_to_manage_frame(driver)
        self._click_tab(driver, "Atribuições")
        resultado = self._ler_grade(driver, COLUNAS_ATRIBUICAO)
        if not resultado:
            raise BMAServiceError(f"Não foi possível ler as linhas de atribuição da OT {numero_ot}.")
        return resultado

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

    def _alterar_status_prepared(self, monitor_id: str, driver, numero_ot: str):
        def acao_status(d):
            self._verificar_leitura(monitor_id, d)
            self._switch_to_manage_frame(d)
            return next((item for item in d.find_elements(By.CSS_SELECTOR, PREPARED_STATUS_OPTION)
                         if item.is_displayed() and item.is_enabled()), None)

        acao = self._aguardar(
            driver, acao_status, 30,
            "A ação 'Alterar Status para Prepared' não está disponível na OT.",
        )
        self._click_when_idle(driver, acao)

        def confirmacao_status(d):
            self._verificar_leitura(monitor_id, d)
            self._switch_to_manage_frame(d)
            fields = self._ler_campos_rotulados(d)
            novo_status = self._valor_campo(fields, ("Novo status",)).upper()
            if novo_status != "PREPARED":
                return False
            confirmar = next((item for item in d.find_elements(By.XPATH, "//*[@role='button' or self::button]")
                              if item.is_displayed() and self._normalize_text(item.text) == "ok"), None)
            return confirmar

        confirmar = self._aguardar(
            driver, confirmacao_status, 30,
            "O diálogo de status não confirmou 'Novo status: Prepared'.",
        )
        self._click_when_idle(driver, confirmar)
        ultimo_status = {}

        def preparado(d):
            self._verificar_leitura(monitor_id, d)
            self._switch_to_manage_frame(d)
            ultimo_status["valor"] = self._valor_campo(self._ler_campos_rotulados(d), CAMPOS_ORDEM["status"]).upper()
            return ultimo_status["valor"] == "PREPARED"

        try:
            self._aguardar(driver, preparado, 60, "O status não mudou para PREPARED após a confirmação.")
        except BMAServiceError as exc:
            raise BMAServiceError(
                f"{exc} Status atual: {ultimo_status.get('valor') or '—'}.",
            ) from exc
        log.info("[%s] OT %s alterada para PREPARED", monitor_id, numero_ot)

    def _input_atribuicao(self, driver, linha: int, coluna: str):
        self._switch_to_manage_frame(driver)
        grade = self._ler_grade(driver, COLUNAS_ATRIBUICAO)
        if not grade or linha >= len(grade["linhas"]):
            return None
        input_id = f"{grade['prefixo']}_tdrow_[C:{grade['colunas'][coluna]}]_txt-tb[R:{linha}]"
        campo = next((item for item in driver.find_elements(By.ID, input_id)
                      if item.is_displayed() and item.is_enabled()), None)
        if campo:
            return campo
        celula = driver.find_element(
            By.ID, f"{grade['prefixo']}_tdrow_[C:{grade['colunas'][coluna]}]-c[R:{linha}]",
        )
        return next((item for item in celula.find_elements(By.CSS_SELECTOR, "input")
                     if item.is_displayed() and item.is_enabled()), None)

    def _preencher_celula(self, monitor_id: str, driver, linha: int, coluna: str, valor: str, conferir):
        def campo(d):
            self._verificar_leitura(monitor_id, d)
            return self._input_atribuicao(d, linha, coluna)

        def aceito(d):
            self._verificar_leitura(monitor_id, d)
            return conferir(self._input_value(self._input_atribuicao(d, linha, coluna)))

        tentativa = 0
        while True:
            self._verificar_leitura(monitor_id, driver)
            tentativa += 1
            self._replace_input(
                self._aguardar(driver, campo, 30, f"Campo {coluna} da linha {linha + 1} ausente."), valor,
                focus_on_table_filter_interception=True,
            )
            try:
                self._aguardar(
                    driver, aceito, 30, f"O valor '{valor}' não permaneceu em {coluna} (linha {linha + 1}).",
                    MatriculaNaoConfirmada if coluna == "mao de obra" else BMAServiceError,
                )
                return
            except MatriculaNaoConfirmada:
                self._update(
                    monitor_id,
                    message=f"Matrícula {valor} não confirmada na linha {linha + 1}; "
                    f"tentando novamente (tentativa {tentativa + 1}).",
                )

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
            data_planejada=self._dia_maximo(inicio),
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
        pendentes_mao_de_obra = [
            item for item in resultados
            if item["situacao_consulta"] == "pendente_planejador" and item.get("requisitos_mao_de_obra")
        ]
        if pendentes_mao_de_obra and envio.get("plan_id"):
            self._reprocessar_pendencias_mao_de_obra(monitor_id, driver, ots, resultados)
        return resultados

    def _reprocessar_pendencias_mao_de_obra(self, monitor_id: str, driver, ots: list[dict], resultados: list[dict]):
        try:
            atualizadas = {ot["numero_ot"]: ot for ot in obter_ots_do_cronograma((self.get(monitor_id) or {})["plan_id"])}
        except (LookupError, KeyError):
            return
        originais = {ot["numero_ot"]: ot for ot in ots}
        for indice, resultado_anterior in enumerate(list(resultados)):
            numero = resultado_anterior["numero_ot"]
            if (resultado_anterior["situacao_consulta"] != "pendente_planejador"
                    or not resultado_anterior.get("requisitos_mao_de_obra")):
                continue
            original, atualizada = originais.get(numero), atualizadas.get(numero)
            if not original or not atualizada:
                continue
            assinatura = lambda ot: sorted(
                (str(item.get("laborcode", "")).strip().upper(), str(item.get("dia", "")))
                for item in ot.get("planejamento", {}).get("atribuicoes", [])
            )
            if assinatura(original) == assinatura(atualizada):
                continue
            self._verificar_interrupcao(monitor_id)
            self._update(monitor_id, stage="rechecking_labor", current_wonum=numero,
                         message=f"OT {numero}: conferindo a equipe escolhida pelo planejador...")
            for tentativa in (1, 2):
                try:
                    resultado = self.planejar_ot(monitor_id, driver, atualizada)
                    break
                except SessaoBmaExpirada:
                    if tentativa == 2:
                        raise
                    self._update(monitor_id, stage="authenticating", message=(
                        f"Sessão do BMA expirou durante a revisão da OT {numero}. "
                        "Conclua o login/MFA no Firefox; a conferência continuará."
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
            resultado["dados_adicionais"]["cronograma_local"] = atualizada["cronograma"]
            if resultado["situacao_consulta"] in SITUACOES_ERRO:
                resultado["dados_adicionais"]["captura_tela"] = self._salvar_captura(driver, numero)
            try:
                registrar_envio_bma(monitor_id, (self.get(monitor_id) or {}).get("plan_id", ""), resultado)
            except sqlite3.Error as exc:
                resultado["dados_adicionais"]["aviso_historico"] = f"Histórico não gravado: {exc}"
            resultados[indice] = resultado
            situacoes = [item["situacao_consulta"] for item in resultados]
            self._update(
                monitor_id, resultados=deepcopy(resultados),
                planejadas=sum(1 for status in situacoes if status in SITUACOES_PLANEJADAS),
                pendentes=sum(1 for status in situacoes if status in SITUACOES_PLANEJADOR),
                com_erro=sum(1 for status in situacoes if status in SITUACOES_ERRO),
                completed_wonums=[item["numero_ot"] for item in resultados
                                  if item["situacao_consulta"] == "planejada"],
                message=f"OT {numero}: {resultado['erro'] or 'equipe atualizada e conferida no BMA'}",
            )

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
        pasta = uploads_dir() / "bma_leitura"
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
        if any(host in url for host in (
            "auth.rbmanca4", "login-fed.michelin.com", "login.microsoftonline.com",
        )):
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
