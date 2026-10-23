from dataclasses import dataclass
from typing import Optional


@dataclass
class ArquivoProcessado:
    id: int
    nome_arquivo: str
    data_upload: str
    total_registros: int
    registros_processados: int
    registros_ignorados: int = 0
    json_resultado: Optional[str] = None
    status: str = "processado"
