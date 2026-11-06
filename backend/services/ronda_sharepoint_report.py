"""Build and upload the SharePoint round work-order register."""

from base64 import b64decode, b64encode
from datetime import date, datetime
from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.worksheet.table import Table, TableStyleInfo

from services.BMAService import BMAServiceError
from services.nf_workforce import SITE

FOLDER_SERVER_RELATIVE_PATH = (
    "/sites/NF-RES/Documentos Compartilhados/DigitalNFE/Arquivos de dados MPQ"
)
FILE_NAME = "OTS de Rondas.xlsx"
TABLE_NAME = "dadosOT"
HEADERS = [
    "ID da linha SharePoint", "Número da OT", "Ronda", "Status SharePoint",
    "Data", "Turno", "Equipe", "Executantes", "Matrículas",
    "Status da criação", "Criada em",
]


def _ot_number(item: dict) -> str:
    raw = item.get("sharepoint_raw")
    return " ".join(str(
        item.get("numero_ot") or item.get("nOT")
        or (raw.get("nOT") if isinstance(raw, dict) else "")
        or item.get("numero_ot_criada") or ""
    ).split())


def _row_values(item: dict) -> list:
    number = _ot_number(item)
    executantes = item.get("executantes") if isinstance(item.get("executantes"), list) else []
    names = "; ".join(str(person.get("nome") or "").strip() for person in executantes if isinstance(person, dict))
    registrations = "; ".join(str(person.get("matricula") or "").strip() for person in executantes if isinstance(person, dict))
    creation_status = item.get("criacao_status")
    if creation_status == "pendente" and number:
        creation_status = "numero_existente"
    return [
        item.get("id"), number, item.get("ronda"), item.get("status"), item.get("data"),
        item.get("turno"), item.get("equipe"), names, registrations,
        creation_status, item.get("criacao_em"),
    ]


def _clean_cell_value(value):
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def _normalized_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return " ".join(str(value).split())


def _row_signature(values: list) -> tuple[str, ...]:
    return tuple(_normalized_cell(value) for value in values)


def _append_rows(sheet, start_row: int, rows: list[list]) -> None:
    for row_index, values in enumerate(rows, start=start_row):
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row_index, column, _clean_cell_value(value))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if isinstance(cell.value, str):
                cell.data_type = "s"


def criar_excel_ots_ronda(items: list[dict]) -> tuple[bytes, int]:
    if not isinstance(items, list):
        raise ValueError("A lista de OTs de Ronda é inválida.")
    rows = [_row_values(item) for item in items if isinstance(item, dict) and _ot_number(item)]
    if not rows:
        raise ValueError("Ainda não há OTs com número para incluir no arquivo.")

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "OTS de Rondas"
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F5A75")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    _append_rows(sheet, 2, rows)

    for column, width in enumerate((20, 18, 30, 20, 16, 12, 16, 42, 24, 20, 24), start=1):
        sheet.column_dimensions[chr(64 + column)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:K{sheet.max_row}"
    table = Table(displayName=TABLE_NAME, ref=f"A1:K{sheet.max_row}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False,
        showRowStripes=True, showColumnStripes=False,
    )
    sheet.add_table(table)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue(), len(rows)


def atualizar_excel_ots_ronda(existing_content: bytes | None, items: list[dict]) -> tuple[bytes, int, bool]:
    if not isinstance(items, list):
        raise ValueError("A lista de OTs de Ronda é inválida.")
    rows = [_row_values(item) for item in items if isinstance(item, dict) and _ot_number(item)]
    if existing_content is None:
        content, added = criar_excel_ots_ronda(items)
        return content, added, True
    if not existing_content:
        raise BMAServiceError("O arquivo OTS de Rondas.xlsx existe, mas está vazio; nenhum dado foi alterado.")

    try:
        workbook = load_workbook(BytesIO(existing_content))
    except Exception as exc:
        raise BMAServiceError("Não foi possível ler o Excel existente; nenhum dado foi alterado.") from exc

    match = next((
        (sheet, table)
        for sheet in workbook.worksheets
        for table in sheet.tables.values()
        if table.displayName.casefold() == TABLE_NAME.casefold()
    ), None)
    if match is None:
        raise BMAServiceError(
            f"O Excel existente não contém a tabela {TABLE_NAME}; nenhum dado foi alterado."
        )
    sheet, table = match
    min_col, header_row, max_col, table_end = range_boundaries(table.ref)
    headers = [sheet.cell(header_row, column).value for column in range(min_col, max_col + 1)]
    if headers != HEADERS:
        raise BMAServiceError(
            f"As colunas da tabela {TABLE_NAME} não correspondem ao formato esperado; nenhum dado foi alterado."
        )

    existing_signatures = set()
    last_data_row = table_end
    for row_index in range(header_row + 1, sheet.max_row + 1):
        existing_values = [sheet.cell(row_index, column).value for column in range(min_col, max_col + 1)]
        if any(value is not None for value in existing_values):
            last_data_row = row_index
            existing_signatures.add(_row_signature(existing_values))

    missing_rows = []
    for row in rows:
        signature = _row_signature(row)
        if signature not in existing_signatures:
            missing_rows.append(row)
            existing_signatures.add(signature)
    if not missing_rows:
        return existing_content, 0, False

    append_start = max(table_end, last_data_row) + 1
    _append_rows(sheet, append_start, missing_rows)
    table_end = append_start + len(missing_rows) - 1
    new_ref = f"{get_column_letter(min_col)}{header_row}:{get_column_letter(max_col)}{table_end}"
    table.ref = new_ref
    if table.autoFilter:
        table.autoFilter.ref = new_ref
    output = BytesIO()
    workbook.save(output)
    return output.getvalue(), len(missing_rows), False


def baixar_excel_ots_ronda(driver) -> bytes | None:
    server_relative_path = f"{FOLDER_SERVER_RELATIVE_PATH}/{FILE_NAME}"
    encoded_path = quote(server_relative_path, safe="/")
    download_url = f"{SITE}/_api/web/GetFileByServerRelativeUrl('{encoded_path}')/$value"
    result = driver.execute_async_script("""
        const [downloadUrl, done] = arguments;
        (async () => {
          const response = await fetch(downloadUrl, {credentials: "same-origin"});
          if (response.status === 404) { done({exists: false}); return; }
          if (!response.ok) {
            done({error: "SharePoint HTTP " + response.status + " ao baixar o Excel existente."});
            return;
          }
          const bytes = new Uint8Array(await response.arrayBuffer());
          let binary = "";
          const chunkSize = 0x8000;
          for (let offset = 0; offset < bytes.length; offset += chunkSize) {
            binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
          }
          done({exists: true, base64: btoa(binary)});
        })().catch(error => done({error: String(error)}));
    """, download_url)
    if not isinstance(result, dict):
        raise BMAServiceError("O SharePoint não retornou o arquivo Excel existente.")
    if result.get("error"):
        raise BMAServiceError(f"Falha ao ler {FILE_NAME}: {result['error']}")
    if not result.get("exists"):
        return None
    try:
        return b64decode(result.get("base64", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise BMAServiceError("O conteúdo do Excel retornado pelo SharePoint é inválido.") from exc


def enviar_excel_ots_ronda(driver, content: bytes) -> str:
    if not isinstance(content, bytes) or not content:
        raise ValueError("O arquivo Excel está vazio ou inválido.")
    folder_path = quote(FOLDER_SERVER_RELATIVE_PATH, safe="/")
    file_name = quote(FILE_NAME, safe="")
    upload_url = (
        f"{SITE}/_api/web/GetFolderByServerRelativeUrl('{folder_path}')/"
        f"Files/add(url='{file_name}',overwrite=true)"
    )
    result = driver.execute_async_script("""
        const [site, uploadUrl, encoded, fileName, done] = arguments;
        (async () => {
          const context = await fetch(site + "/_api/contextinfo", {
            method: "POST", credentials: "same-origin",
            headers: {Accept: "application/json;odata=verbose"}
          });
          if (!context.ok) {
            done({error: "SharePoint HTTP " + context.status + " ao solicitar o token de gravação."});
            return;
          }
          const contextBody = await context.json();
          const digest = contextBody?.d?.GetContextWebInformation?.FormDigestValue;
          if (!digest) {
            done({error: "SharePoint não retornou o token de gravação."});
            return;
          }
          const raw = atob(encoded);
          const bytes = new Uint8Array(raw.length);
          for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
          const response = await fetch(uploadUrl, {
            method: "POST", credentials: "same-origin",
            headers: {
              Accept: "application/json;odata=verbose",
              "Content-Type": "application/octet-stream",
              "X-RequestDigest": digest
            },
            body: bytes
          });
          const responseText = await response.text();
          if (!response.ok) {
            done({error: "SharePoint HTTP " + response.status + ": " + responseText.slice(0, 400)});
            return;
          }
          let file = {};
          try { file = responseText ? JSON.parse(responseText) : {}; } catch (_) {}
          done({
            fileName: file?.d?.Name || file?.Name || fileName,
            serverRelativeUrl: file?.d?.ServerRelativeUrl || file?.ServerRelativeUrl || ""
          });
        })().catch(error => done({error: String(error)}));
    """, SITE, upload_url, b64encode(content).decode("ascii"), FILE_NAME)
    if not isinstance(result, dict):
        raise BMAServiceError("O SharePoint não confirmou o upload do arquivo.")
    if result.get("error"):
        raise BMAServiceError(f"Falha ao atualizar {FILE_NAME}: {result['error']}")
    return str(result.get("serverRelativeUrl") or result.get("fileName") or FILE_NAME)