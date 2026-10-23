from datetime import datetime

from models.database import get_connection


def registrar_log(
    mensagem: str,
    nivel: str = "info",
    nome_arquivo: str | None = None,
    quantidade_processada: int | None = None,
) -> dict:
    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO logs (data_hora, nivel, mensagem, nome_arquivo, quantidade_processada)
            VALUES (?, ?, ?, ?, ?)
            """,
            (data_hora, nivel, mensagem, nome_arquivo, quantidade_processada),
        )
        conn.commit()
    return {
        "data_hora": data_hora,
        "nivel": nivel,
        "mensagem": mensagem,
        "nome_arquivo": nome_arquivo,
        "quantidade_processada": quantidade_processada,
    }


def listar_logs(limite: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, data_hora, nivel, mensagem, nome_arquivo, quantidade_processada
            FROM logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
    return [dict(row) for row in rows]
