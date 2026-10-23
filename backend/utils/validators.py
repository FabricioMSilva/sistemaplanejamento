from pathlib import Path
import unicodedata
import re

ALLOWED_EXTENSIONS = {".xlsx", ".xls"}
INVALID_FILE_MESSAGE = "Arquivo inválido. Utilize o modelo padrão de importação."

OT_COLUMN_ALIASES = {
    "n_ot_bma",
    "no_ot_bma",
    "n_o_ot_bma",
    "numero_ot_bma",
    "num_ot_bma",
    "nro_ot_bma",
    "nr_ot_bma",
}

STATUS_COLUMN_ALIASES = {
    "taskstatus",
    "task_status",
    "status_tarefa",
    "status_da_tarefa",
}

STATUS_INELEGIVEIS = {
    "planejado",
    "concluido",
    "preparado",
    "cancelado",
}


def slugify_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
    return slug


def validate_extension(filename: str) -> None:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Formato inválido. Envie apenas arquivos .xlsx ou .xls.")


def find_ot_column(columns: list[str]) -> str | None:
    for column in columns:
        slug = slugify_header(column)
        if slug in OT_COLUMN_ALIASES:
            return str(column)
        if "ot" in slug and "bma" in slug and slug.startswith(("n", "num", "nr")):
            return str(column)
    return None


def is_empty_value(value) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none", "nat", "null"}


def find_status_column(columns: list[str]) -> str | None:
    for column in columns:
        slug = slugify_header(column)
        if slug in STATUS_COLUMN_ALIASES or slug.replace("_", "") == "taskstatus":
            return str(column)
    return None


def normalize_status(value) -> str:
    if is_empty_value(value):
        return ""
    return slugify_header(str(value)).replace("_", "")


def is_status_inelegivel(value) -> bool:
    return normalize_status(value) in STATUS_INELEGIVEIS
