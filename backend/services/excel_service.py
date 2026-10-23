import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from models.database import get_connection
from services.log_service import registrar_log
from utils.validators import (
    INVALID_FILE_MESSAGE,
    find_ot_column,
    find_status_column,
    is_empty_value,
    is_status_inelegivel,
    slugify_header,
    validate_extension,
)

UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads"
PREVIEW_COLUMN_INDEXES = (0, 2, 3, 5)  # A, C, D, F


class InvalidSpreadsheetError(ValueError):
    def __init__(self, message: str = INVALID_FILE_MESSAGE):
        super().__init__(message)


def _read_spreadsheet(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    if suffix == ".xls":
        return pd.read_excel(path, engine="xlrd")
    raise InvalidSpreadsheetError()


def _cell_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, str):
        return value.strip()
    return value


def _row_to_json(row: pd.Series, ot_column: str) -> dict:
    payload = {}
    for column, value in row.items():
        if column == ot_column:
            continue
        key = slugify_header(str(column)) or str(column)
        payload[key] = _cell_value(value)
    return payload


def _preview_rows(df: pd.DataFrame, columns: list[str]) -> tuple[list[str], list[dict]]:
    preview_columns = [columns[index] for index in PREVIEW_COLUMN_INDEXES if index < len(columns)]
    rows = []
    for _, row in df.iterrows():
        rows.append({column: _cell_value(row[column]) for column in preview_columns})
    return preview_columns, rows


def processar_planilha(nome_arquivo: str, conteudo: bytes) -> dict:
    validate_extension(nome_arquivo)
    registrar_log(f"Arquivo carregado: {nome_arquivo}", nome_arquivo=nome_arquivo)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destino = UPLOAD_DIR / nome_arquivo
    destino.write_bytes(conteudo)

    try:
        df = _read_spreadsheet(destino)
    except InvalidSpreadsheetError:
        registrar_log("Erro: formato de planilha inválido.", nivel="error", nome_arquivo=nome_arquivo)
        raise
    except Exception as exc:
        registrar_log(f"Erro ao ler planilha: {exc}", nivel="error", nome_arquivo=nome_arquivo)
        raise InvalidSpreadsheetError() from exc

    df = df.dropna(how="all")
    columns = [str(column) for column in df.columns]
    ot_column = find_ot_column(columns)

    if not ot_column:
        registrar_log(
            "Erro: coluna obrigatória Nº OT BMA não encontrada.",
            nivel="error",
            nome_arquivo=nome_arquivo,
        )
        raise InvalidSpreadsheetError()

    total = int(len(df))
    empty_mask = df[ot_column].map(is_empty_value)
    status_column = find_status_column(columns)
    if status_column:
        status_inelegivel_mask = df[status_column].map(is_status_inelegivel)
    else:
        status_inelegivel_mask = pd.Series(False, index=df.index)

    elegivel_mask = empty_mask & ~status_inelegivel_mask
    elegiveis = df[elegivel_mask]
    ignorados = df[~elegivel_mask]
    json_dados = [_row_to_json(row, ot_column) for _, row in elegiveis.iterrows()]
    preview_colunas, preview = _preview_rows(elegiveis, columns)

    data_upload = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO arquivos_processados (
                nome_arquivo, data_upload, total_registros,
                registros_processados, registros_ignorados, json_resultado, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nome_arquivo,
                data_upload,
                total,
                len(json_dados),
                int(len(ignorados)),
                json.dumps(json_dados, ensure_ascii=False),
                "processado",
            ),
        )
        arquivo_id = cursor.lastrowid
        conn.commit()

    registrar_log(
        f"Processamento concluído. {len(json_dados)} registro(s) elegível(is).",
        nome_arquivo=nome_arquivo,
        quantidade_processada=len(json_dados),
    )

    return {
        "id": arquivo_id,
        "nome_arquivo": nome_arquivo,
        "data_upload": data_upload,
        "total_registros": total,
        "registros_processados": len(json_dados),
        "registros_ignorados": int(len(ignorados)),
        "coluna_ot": ot_column,
        "coluna_status": status_column,
        "colunas_identificadas": columns,
        "preview_colunas": preview_colunas,
        "preview": preview,
        "json": json_dados,
    }
