"""Read the corporate active roster and link it to Maximo identities, never by fuzzy name."""

from urllib.parse import urljoin, urlsplit

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

from .BMAService import BMAServiceError

SITE = "https://michelingroup.sharepoint.com/sites/NF-RES"
LIST_URL = SITE + "/Lists/ListaFuncionario/AllItems.aspx"


def coletar_ativos(driver, timeout: int, progress=None) -> list[dict]:
    if progress:
        progress("sharepoint", "Conferindo ativos NF no SharePoint. Conclua o login corporativo se solicitado.", None, None)
    driver.get(LIST_URL)
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
