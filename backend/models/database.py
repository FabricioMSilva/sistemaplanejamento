import json
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from .workforce_identity import normalizar, vincular_ativos
from utils.runtime_paths import data_root, resource_root

ROOT_DIR = resource_root()
DB_PATH = data_root() / "database" / "data" / "bma_intranet.db"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _numero_ot_sharepoint(item: dict[str, Any]) -> str:
    raw = item.get("sharepoint_raw")
    return " ".join(str(
        item.get("numero_ot") or item.get("nOT")
        or (raw.get("nOT") if isinstance(raw, dict) else "")
        or ""
    ).split())


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS arquivos_processados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_arquivo TEXT NOT NULL,
                data_upload TEXT NOT NULL,
                total_registros INTEGER NOT NULL DEFAULT 0,
                registros_processados INTEGER NOT NULL DEFAULT 0,
                registros_ignorados INTEGER NOT NULL DEFAULT 0,
                json_resultado TEXT,
                status TEXT NOT NULL DEFAULT 'processado'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_hora TEXT NOT NULL,
                nivel TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                nome_arquivo TEXT,
                quantidade_processada INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ordens_trabalho (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                siteid TEXT NOT NULL,
                wonum TEXT NOT NULL,
                status TEXT,
                maintenanceshop TEXT NOT NULL,
                dados_json TEXT NOT NULL,
                sincronizado_em TEXT NOT NULL,
                UNIQUE (siteid, wonum)
            )
            """
        )
        order_columns = {row["name"] for row in conn.execute("PRAGMA table_xinfo(ordens_trabalho)")}
        generated_columns = {
            "lead": """CASE WHEN json_type(dados_json, '$.lead') = 'object'
                THEN COALESCE(json_extract(dados_json, '$.lead.value'),
                              json_extract(dados_json, '$.lead._value'),
                              json_extract(dados_json, '$.lead.description'))
                ELSE json_extract(dados_json, '$.lead') END""",
            "schedstart": """CASE WHEN json_type(dados_json, '$.schedstart') = 'object'
                THEN COALESCE(json_extract(dados_json, '$.schedstart.value'),
                              json_extract(dados_json, '$.schedstart._value'),
                              json_extract(dados_json, '$.schedstart.description'))
                ELSE json_extract(dados_json, '$.schedstart') END""",
            "planning_status": """CASE
                WHEN NULLIF(TRIM(COALESCE(lead, '')), '') IS NOT NULL
                     AND NULLIF(TRIM(COALESCE(schedstart, '')), '') IS NOT NULL
                    THEN 'Planejada'
                WHEN NULLIF(TRIM(COALESCE(lead, '')), '') IS NOT NULL
                     OR NULLIF(TRIM(COALESCE(schedstart, '')), '') IS NOT NULL
                    THEN 'Parcial'
                WHEN json_type(dados_json, '$.lead') IS NULL THEN 'Não verificada'
                ELSE 'Não planejada' END""",
        }
        for name, expression in generated_columns.items():
            if name not in order_columns:
                conn.execute(
                    f"ALTER TABLE ordens_trabalho ADD COLUMN {name} TEXT "
                    f"GENERATED ALWAYS AS ({expression}) VIRTUAL"
                )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ordens_trabalho_setor_status
            ON ordens_trabalho (maintenanceshop, status)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ordens_planejamento_status
            ON ordens_trabalho (maintenanceshop, planning_status)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ordens_inicio_planejado
            ON ordens_trabalho (schedstart)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ordens_trabalho_snapshots (
                snapshot_date TEXT NOT NULL,
                siteid TEXT NOT NULL,
                wonum TEXT NOT NULL,
                status TEXT,
                maintenanceshop TEXT NOT NULL,
                dados_json TEXT NOT NULL,
                capturado_em TEXT NOT NULL,
                PRIMARY KEY (snapshot_date, siteid, wonum)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ots_snapshots_data_setor
            ON ordens_trabalho_snapshots (snapshot_date, maintenanceshop)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ordens_trabalho_alteracoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                siteid TEXT NOT NULL,
                wonum TEXT NOT NULL,
                maintenanceshop TEXT NOT NULL,
                alterado_em TEXT NOT NULL,
                alteracoes_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ots_alteracoes_setor_data
            ON ordens_trabalho_alteracoes (maintenanceshop, alterado_em)
            """
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS especialidades (
                orgid TEXT NOT NULL,
                codigo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                PRIMARY KEY (orgid, codigo)
            )
        """)
        catalog_path = ROOT_DIR / "database" / "catalogos" / "especialidades.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        conn.executemany(
            """INSERT INTO especialidades (orgid, codigo, descricao) VALUES (?, ?, ?)
               ON CONFLICT(orgid, codigo) DO UPDATE SET descricao=excluded.descricao""",
            [(row["orgid"], row["codigo"], row["descricao"]) for row in catalog],
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mao_de_obra (
                orgid TEXT NOT NULL,
                laborcode TEXT NOT NULL,
                worksite TEXT NOT NULL,
                worklocation TEXT NOT NULL DEFAULT '',
                nome TEXT NOT NULL,
                setor TEXT NOT NULL,
                dados_json TEXT NOT NULL,
                sincronizado_em TEXT NOT NULL,
                PRIMARY KEY (orgid, laborcode)
            )
        """)
        labor_columns = {row["name"] for row in conn.execute("PRAGMA table_info(mao_de_obra)")}
        if "worklocation" not in labor_columns:
            conn.execute("ALTER TABLE mao_de_obra ADD COLUMN worklocation TEXT NOT NULL DEFAULT ''")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mao_de_obra_sync (
                worksite TEXT PRIMARY KEY,
                sincronizado_em TEXT NOT NULL,
                quantidade INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS planejamento_equipes (
                setores TEXT PRIMARY KEY,
                dados_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pcm_planos (
                id TEXT PRIMARY KEY, escopo TEXT NOT NULL UNIQUE,
                revisao INTEGER NOT NULL, status TEXT NOT NULL,
                atualizado_em TEXT NOT NULL, dados_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pcm_revisoes (
                plano_id TEXT NOT NULL, revisao INTEGER NOT NULL,
                salvo_em TEXT NOT NULL, motivo TEXT NOT NULL, dados_json TEXT NOT NULL,
                pdf BLOB NOT NULL,
                PRIMARY KEY (plano_id, revisao)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS planejamento_historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT, setores TEXT NOT NULL,
                salvo_em TEXT NOT NULL, dados_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS planejamento_padroes (
                setores TEXT NOT NULL, planejador TEXT NOT NULL, dados_json TEXT NOT NULL,
                PRIMARY KEY (setores, planejador)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS planejamento_equipes_salvas (
                setores TEXT NOT NULL, nome_normalizado TEXT NOT NULL, nome TEXT NOT NULL,
                salvo_em TEXT NOT NULL, dados_json TEXT NOT NULL,
                PRIMARY KEY (setores, nome_normalizado)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nf_ativos (
                id INTEGER PRIMARY KEY CHECK (id=1), dados_json TEXT NOT NULL,
                sincronizado_em TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nf_vinculos (
                sharepoint_id INTEGER PRIMARY KEY, orgid TEXT NOT NULL, matricula TEXT NOT NULL,
                UNIQUE (orgid, matricula)
            )
        """)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS planejamento_sync_runs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                etapa TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                erro TEXT,
                setores_json TEXT NOT NULL,
                pagina_atual INTEGER NOT NULL DEFAULT 0,
                ots_lidas INTEGER NOT NULL DEFAULT 0,
                ots_salvas INTEGER NOT NULL DEFAULT 0,
                iniciada_em TEXT NOT NULL,
                atualizada_em TEXT NOT NULL,
                concluida_em TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS planejamento_sync_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                nivel TEXT NOT NULL,
                etapa TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                pagina INTEGER,
                ots INTEGER,
                data_hora TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES planejamento_sync_runs(job_id)
                    ON DELETE CASCADE
            )
            """
        )
        sync_columns = {row["name"] for row in conn.execute("PRAGMA table_info(planejamento_sync_runs)")}
        if "tipo" not in sync_columns:
            conn.execute("ALTER TABLE planejamento_sync_runs ADD COLUMN tipo TEXT NOT NULL DEFAULT 'ots'")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_planejamento_sync_events_job
            ON planejamento_sync_events (job_id, id)
            """
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bma_envios_planejamento (
                id INTEGER PRIMARY KEY AUTOINCREMENT, envio_id TEXT NOT NULL, plano_id TEXT NOT NULL,
                numero_ot TEXT NOT NULL, situacao TEXT NOT NULL, registrado_em TEXT NOT NULL,
                dados_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historico_ots_programa (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                siteid TEXT NOT NULL DEFAULT 'RES',
                wonum TEXT NOT NULL DEFAULT '',
                acao TEXT NOT NULL,
                situacao TEXT NOT NULL,
                registrado_em TEXT NOT NULL,
                origem TEXT NOT NULL,
                dados_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_historico_ots_programa_data
            ON historico_ots_programa (registrado_em)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_historico_ots_programa_wonum
            ON historico_ots_programa (wonum)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ronda_funcionarios (
                nome_normalizado TEXT NOT NULL,
                matricula_lista TEXT NOT NULL DEFAULT '',
                nome TEXT NOT NULL,
                matricula_bma TEXT NOT NULL DEFAULT '',
                orgid TEXT NOT NULL DEFAULT '',
                vinculo TEXT NOT NULL,
                atualizado_em TEXT NOT NULL,
                PRIMARY KEY (nome_normalizado, matricula_lista)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ronda_funcionarios_matricula
            ON ronda_funcionarios (matricula_bma)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ronda_sharepoint_items (
                sharepoint_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                ronda TEXT NOT NULL DEFAULT '',
                apta_criacao INTEGER NOT NULL DEFAULT 0,
                criacao_status TEXT NOT NULL DEFAULT 'pendente',
                numero_ot TEXT,
                criacao_em TEXT,
                criacao_erro TEXT,
                sincronizado_em TEXT NOT NULL,
                dados_json TEXT NOT NULL
            )
        """)
        ronda_columns = {row["name"] for row in conn.execute("PRAGMA table_info(ronda_sharepoint_items)")}
        for column, definition in (
            ("criacao_status", "TEXT NOT NULL DEFAULT 'pendente'"),
            ("numero_ot", "TEXT"),
            ("criacao_em", "TEXT"),
            ("criacao_erro", "TEXT"),
        ):
            if column not in ronda_columns:
                conn.execute(f"ALTER TABLE ronda_sharepoint_items ADD COLUMN {column} {definition}")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ronda_sharepoint_status
            ON ronda_sharepoint_items (status, apta_criacao)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ronda_sharepoint_sync (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                sincronizado_em TEXT NOT NULL,
                total_itens INTEGER NOT NULL
            )
        """)
        interrupted = conn.execute(
            """SELECT sharepoint_id, criacao_status, numero_ot, dados_json
               FROM ronda_sharepoint_items
               WHERE criacao_status IN ('criando', 'numero_gerado', 'salva')"""
        ).fetchall()
        interrupted_message = (
            "Lote interrompido por reinicialização do backend. Confira número e status no BMA antes de continuar."
        )
        for row in interrupted:
            details = json.loads(row["dados_json"])
            state = row["criacao_status"]
            if state == "criando":
                state = "numero_gerado" if row["numero_ot"] else "erro"
            details.update({
                "criacao_status": state,
                "numero_ot_criada": row["numero_ot"],
                "criacao_erro": interrupted_message,
            })
            conn.execute(
                """UPDATE ronda_sharepoint_items
                   SET criacao_status=?, criacao_erro=?, dados_json=?
                   WHERE sharepoint_id=?""",
                (state, interrupted_message, json.dumps(details, ensure_ascii=False), row["sharepoint_id"]),
            )

        numbered_items = conn.execute(
            """SELECT sharepoint_id, criacao_status, numero_ot, apta_criacao, criacao_em,
                      criacao_erro, dados_json
               FROM ronda_sharepoint_items"""
        ).fetchall()
        for row in numbered_items:
            details = json.loads(row["dados_json"])
            sharepoint_number = _numero_ot_sharepoint(details)
            number = sharepoint_number or row["numero_ot"]
            if not number:
                continue
            state = row["criacao_status"]
            error = row["criacao_erro"]
            if sharepoint_number and state in {"pendente", "erro", "criando"}:
                state = "numero_existente"
                error = None
            elif state == "pendente":
                state = "numero_gerado"
            details.update({
                "criacao_status": state,
                "numero_ot_criada": number,
                "criacao_erro": error,
            })
            conn.execute(
                """UPDATE ronda_sharepoint_items
                   SET apta_criacao=0, criacao_status=?, numero_ot=?, criacao_erro=?, dados_json=?
                   WHERE sharepoint_id=?""",
                (state, number, error, json.dumps(details, ensure_ascii=False), row["sharepoint_id"]),
            )
        conn.commit()


def registrar_envio_bma(envio_id: str, plano_id: str, resultado: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO bma_envios_planejamento "
            "(envio_id, plano_id, numero_ot, situacao, registrado_em, dados_json) VALUES (?, ?, ?, ?, ?, ?)",
            (envio_id, plano_id, resultado["numero_ot"], resultado["situacao_consulta"],
             datetime.now(timezone.utc).isoformat(), json.dumps(resultado, ensure_ascii=False)),
        )


def listar_situacao_envios_bma(plano_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT numero_ot, situacao, registrado_em, dados_json FROM bma_envios_planejamento "
            "WHERE plano_id=? ORDER BY id", (plano_id,),
        ).fetchall()
    ultimos = {}
    for row in rows:
        ultimos[row["numero_ot"]] = {
            "numero_ot": row["numero_ot"], "situacao": row["situacao"], "registrado_em": row["registrado_em"],
            "erro": json.loads(row["dados_json"]).get("erro"),
        }
    return list(ultimos.values())


def registrar_historico_ot(
    acao: str, situacao: str, origem: str, *, wonum: str = "", siteid: str = "RES",
    detalhes: dict[str, Any] | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO historico_ots_programa
               (siteid, wonum, acao, situacao, registrado_em, origem, dados_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (siteid, wonum, acao, situacao, datetime.now(timezone.utc).isoformat(), origem,
             json.dumps(detalhes or {}, ensure_ascii=False)),
        )


def listar_historico_ots(busca: str = "", tipo: str = "todas", limite: int = 500) -> list[dict[str, Any]]:
    with get_connection() as conn:
        events = conn.execute(
            """SELECT id, siteid, wonum, acao, situacao, registrado_em, origem, dados_json
               FROM historico_ots_programa ORDER BY id DESC LIMIT ?""",
            (max(1, min(limite, 500)),),
        ).fetchall()
        sends = conn.execute(
            """SELECT id, numero_ot, situacao, registrado_em, dados_json
               FROM bma_envios_planejamento ORDER BY id DESC LIMIT ?""",
            (max(1, min(limite, 500)),),
        ).fetchall()

    history = []
    for row in events:
        details = json.loads(row["dados_json"] or "{}")
        history.append({
            "id": f"evento-{row['id']}", "siteid": row["siteid"], "wonum": row["wonum"],
            "acao": row["acao"], "situacao": row["situacao"],
            "status": details.get("status") or row["situacao"], "registrado_em": row["registrado_em"],
            "origem": row["origem"], "resumo": details.get("resumo", ""), "detalhes": details,
        })

    for row in sends:
        details = json.loads(row["dados_json"] or "{}")
        situacao = row["situacao"]
        observations = (details.get("dados_adicionais") or {}).get("observacoes") or []
        if situacao in {"planejada", "ja_planejada"}:
            acao = "alterada" if situacao == "planejada" and observations else "planejada"
        elif situacao == "pendente_planejador":
            acao = "pendente"
        elif situacao in {"erro", "nao_encontrada"}:
            acao = "erro"
        else:
            acao = "consulta"
        history.append({
            "id": f"envio-{row['id']}", "siteid": details.get("siteid", "RES"),
            "wonum": row["numero_ot"], "acao": acao, "situacao": situacao,
            "status": details.get("status") or situacao,
            "registrado_em": row["registrado_em"], "origem": "Envio de planejamento",
            "resumo": details.get("erro") or details.get("descricao") or "", "detalhes": details,
        })

    selected_actions = {
        "criadas": {"criada", "criacao_solicitada"},
        "planejadas": {"planejada"},
        "alteradas": {"alterada"},
    }.get(tipo)
    needle = busca.strip().casefold()
    if selected_actions:
        history = [item for item in history if item["acao"] in selected_actions]
    if needle:
        history = [item for item in history if needle in " ".join((
            item["siteid"], item["wonum"], item["acao"], item["situacao"], item["origem"],
            item["resumo"], json.dumps(item["detalhes"], ensure_ascii=False),
        )).casefold()]
    history.sort(key=lambda item: item["registrado_em"], reverse=True)
    return history[:max(1, min(limite, 500))]


def salvar_funcionarios_ronda(funcionarios: list[dict[str, Any]]) -> int:
    if not isinstance(funcionarios, list) or any(not isinstance(person, dict) for person in funcionarios):
        raise ValueError("Lista de executantes de Ronda inválida.")
    saved_at = datetime.now(timezone.utc).isoformat()
    unique = {}
    for person in funcionarios:
        name = " ".join(str(person.get("nome") or "").split())
        if not name:
            continue
        list_registration = " ".join(str(person.get("matricula_lista") or "").split()).upper()
        bma_registration = " ".join(str(person.get("matricula_bma") or "").split()).upper()
        orgid = " ".join(str(person.get("orgid") or "").split()).upper()
        key = (normalizar(name), normalizar(list_registration))
        unique[key] = (
            key[0], list_registration, name, bma_registration, orgid,
            str(person.get("vinculo") or "sem_vinculo"), saved_at,
        )
    if not unique:
        return 0
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO ronda_funcionarios
               (nome_normalizado, matricula_lista, nome, matricula_bma, orgid, vinculo, atualizado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(nome_normalizado, matricula_lista) DO UPDATE SET
               nome=excluded.nome, matricula_bma=excluded.matricula_bma, orgid=excluded.orgid,
               vinculo=excluded.vinculo, atualizado_em=excluded.atualizado_em""",
            list(unique.values()),
        )
    return len(unique)


def listar_funcionarios_ronda() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT nome, matricula_lista, matricula_bma, orgid, vinculo, atualizado_em
               FROM ronda_funcionarios ORDER BY nome_normalizado, matricula_lista""",
        ).fetchall()
    return [dict(row) for row in rows]

def salvar_itens_ronda_sharepoint(itens: list[dict[str, Any]]) -> int:
    if not isinstance(itens, list) or any(not isinstance(item, dict) for item in itens):
        raise ValueError("Snapshot da lista AbrirOTRonda inválido.")

    saved_at = datetime.now(timezone.utc).isoformat()
    rows = []
    seen = set()
    for item in itens:
        try:
            sharepoint_id = int(item.get("id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Item da lista AbrirOTRonda sem ID válido.") from exc
        if sharepoint_id <= 0 or sharepoint_id in seen:
            raise ValueError("ID inválido ou duplicado na lista AbrirOTRonda.")
        seen.add(sharepoint_id)
        status = " ".join(str(item.get("status") or "").split()).upper()
        ronda = " ".join(str(item.get("ronda") or "").split())
        executantes = item.get("executantes")
        blocked = item.get("bloqueios_matricula")
        sharepoint_ot_number = _numero_ot_sharepoint(item)
        apta = status == "PENDENTE" and not sharepoint_ot_number and not blocked and isinstance(executantes, list) and bool(executantes) and all(
            isinstance(person, dict) and str(person.get("matricula") or "").strip()
            for person in executantes
        )
        stored_item = {**item, "id": sharepoint_id, "status": status, "ronda": ronda}
        rows.append((sharepoint_id, status, ronda, int(apta), saved_at, stored_item))

    with get_connection() as conn:
        existing = {
            row["sharepoint_id"]: dict(row)
            for row in conn.execute(
                "SELECT sharepoint_id, criacao_status, numero_ot, criacao_em, criacao_erro "
                "FROM ronda_sharepoint_items"
            )
        }
        conn.execute("DELETE FROM ronda_sharepoint_items")
        persisted_rows = []
        for sharepoint_id, status, ronda, apta, synced_at, stored_item in rows:
            previous = existing.get(sharepoint_id, {})
            creation_status = previous.get("criacao_status", "pendente")
            if creation_status == "criando":
                creation_status = "erro"
            sharepoint_number = _numero_ot_sharepoint(stored_item)
            number = sharepoint_number or previous.get("numero_ot")
            creation_error = previous.get("criacao_erro")
            if sharepoint_number and creation_status in {"pendente", "erro"}:
                creation_status = "numero_existente"
                creation_error = None
            elif creation_status == "pendente" and number:
                creation_status = "numero_gerado"
            created_at = previous.get("criacao_em")
            apta = 0 if number else apta
            stored_item.update({
                "criacao_status": creation_status,
                "numero_ot_criada": number,
                "criacao_em": created_at,
                "criacao_erro": creation_error,
            })
            persisted_rows.append((
                sharepoint_id, status, ronda, apta, creation_status, number,
                created_at, creation_error, synced_at,
                json.dumps(stored_item, ensure_ascii=False),
            ))
        conn.executemany(
            """INSERT INTO ronda_sharepoint_items
               (sharepoint_id, status, ronda, apta_criacao, criacao_status, numero_ot,
                criacao_em, criacao_erro, sincronizado_em, dados_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            persisted_rows,
        )
        conn.execute(
            """INSERT INTO ronda_sharepoint_sync (id, sincronizado_em, total_itens)
               VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               sincronizado_em=excluded.sincronizado_em, total_itens=excluded.total_itens""",
            (saved_at, len(rows)),
        )
    return len(rows)


def listar_itens_ronda_sharepoint() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT sharepoint_id, status, ronda, apta_criacao, criacao_status,
                      numero_ot, criacao_em, criacao_erro, dados_json
               FROM ronda_sharepoint_items ORDER BY sharepoint_id"""
        ).fetchall()
    items = []
    for row in rows:
        item = json.loads(row["dados_json"])
        item.update({
            "id": row["sharepoint_id"], "status": row["status"], "ronda": row["ronda"],
            "apta_criacao": bool(row["apta_criacao"]), "criacao_status": row["criacao_status"],
            "numero_ot_criada": row["numero_ot"], "criacao_em": row["criacao_em"],
            "criacao_erro": row["criacao_erro"],
        })
        items.append(item)
    return items


def listar_itens_ronda_para_criacao(*, incluir_falhas: bool = True) -> list[dict[str, Any]]:
    statuses = "'pendente', 'erro'" if incluir_falhas else "'pendente'"
    with get_connection() as conn:
        rows = conn.execute(
            f"""SELECT sharepoint_id, criacao_status, numero_ot, criacao_em, criacao_erro, dados_json
                FROM ronda_sharepoint_items
                WHERE status='PENDENTE' AND apta_criacao=1
                  AND criacao_status IN ({statuses}) AND COALESCE(numero_ot, '')=''
                ORDER BY sharepoint_id"""
        ).fetchall()
    items = []
    for row in rows:
        item = json.loads(row["dados_json"])
        item.update({
            "id": row["sharepoint_id"], "criacao_status": row["criacao_status"],
            "numero_ot_criada": row["numero_ot"], "criacao_em": row["criacao_em"],
            "criacao_erro": row["criacao_erro"],
        })
        items.append(item)
    return items


def resumo_ronda_sharepoint() -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT sharepoint_id, status, ronda, apta_criacao, criacao_status,
                      numero_ot, criacao_em, criacao_erro
               FROM ronda_sharepoint_items"""
        ).fetchall()
        sync = conn.execute(
            "SELECT sincronizado_em, total_itens FROM ronda_sharepoint_sync WHERE id=1"
        ).fetchone()

    pending = [row for row in rows if row["status"] == "PENDENTE" and row["criacao_status"] in {"pendente", "erro"}]
    counts: dict[str, dict[str, int]] = {}
    for row in pending:
        name = row["ronda"] or "Não informado"
        count = counts.setdefault(name, {"total": 0, "aptas": 0})
        count["total"] += 1
        count["aptas"] += int(
            row["apta_criacao"] and row["criacao_status"] in {"pendente", "erro"}
            and not row["numero_ot"]
        )
    return {
        "total": len(rows),
        "pendentes": len(pending),
        "aptas": sum(
            int(row["apta_criacao"] and row["criacao_status"] in {"pendente", "erro"}
                and not row["numero_ot"])
            for row in pending
        ),
        "bloqueadas": sum(not int(row["apta_criacao"]) for row in pending),
        "criadas": sum(row["criacao_status"] == "criada" for row in rows),
        "salvas": sum(row["criacao_status"] == "salva" for row in rows),
        "numeros_gerados": sum(row["criacao_status"] == "numero_gerado" for row in rows),
        "falhas_criacao": sum(row["criacao_status"] == "erro" for row in rows),
        "falhas": [
            {"sharepoint_id": row["sharepoint_id"], "ronda": row["ronda"],
             "numero_ot": row["numero_ot"], "registrado_em": row["criacao_em"],
             "status": row["criacao_status"], "erro": row["criacao_erro"]}
            for row in sorted(rows, key=lambda item: item["sharepoint_id"], reverse=True)
            if row["criacao_status"] in {"erro", "numero_gerado", "salva"}
        ][:100],
        "rondas": [{"nome": name, **count} for name, count in sorted(counts.items())],
        "atualizado_em": sync["sincronizado_em"] if sync else None,
        "funcionarios": len(listar_funcionarios_ronda()),
    }


def iniciar_criacao_ronda(sharepoint_ids: list[int]) -> None:
    ids = list(dict.fromkeys(int(value) for value in sharepoint_ids))
    if not ids:
        raise ValueError("Não há itens aptos para criar OTs.")
    with get_connection() as conn:
        for sharepoint_id in ids:
            row = conn.execute(
                "SELECT dados_json FROM ronda_sharepoint_items WHERE sharepoint_id=?",
                (sharepoint_id,),
            ).fetchone()
            cursor = conn.execute(
                """UPDATE ronda_sharepoint_items SET criacao_status='criando', criacao_erro=NULL
                   WHERE sharepoint_id=? AND status='PENDENTE' AND apta_criacao=1
                                         AND criacao_status IN ('pendente', 'erro') AND numero_ot IS NULL""",
                (sharepoint_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Item de Ronda {sharepoint_id} não está mais disponível para criação.")
            details = json.loads(row["dados_json"])
            details.update({"criacao_status": "criando", "criacao_erro": None})
            conn.execute(
                "UPDATE ronda_sharepoint_items SET dados_json=? WHERE sharepoint_id=?",
                (json.dumps(details, ensure_ascii=False), sharepoint_id),
            )


def registrar_ot_ronda_criada(sharepoint_ids: list[int], numero_ot: str) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        for sharepoint_id in sharepoint_ids:
            row = conn.execute(
                                """SELECT dados_json FROM ronda_sharepoint_items
                                     WHERE sharepoint_id=? AND criacao_status IN ('criando', 'numero_gerado', 'salva')
                                         AND numero_ot=?""",
                                (int(sharepoint_id), numero_ot),
            ).fetchone()
            if row is None:
                raise ValueError(f"Item de Ronda {sharepoint_id} não está reservado para criação.")
            details = json.loads(row["dados_json"])
            details.update({
                "criacao_status": "criada", "numero_ot_criada": numero_ot,
                "criacao_em": created_at, "criacao_erro": None,
            })
            conn.execute(
                """UPDATE ronda_sharepoint_items
                   SET criacao_status='criada', numero_ot=?, criacao_em=?, criacao_erro=NULL, dados_json=?
                   WHERE sharepoint_id=?""",
                (numero_ot, created_at, json.dumps(details, ensure_ascii=False), int(sharepoint_id)),
            )


def registrar_numero_ot_ronda(sharepoint_ids: list[int], numero_ot: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        for sharepoint_id in sharepoint_ids:
            row = conn.execute(
                "SELECT dados_json, criacao_status FROM ronda_sharepoint_items WHERE sharepoint_id=?",
                (int(sharepoint_id),),
            ).fetchone()
            if row is None or row["criacao_status"] != "criando":
                raise ValueError(f"Item de Ronda {sharepoint_id} não está reservado para criação.")
            details = json.loads(row["dados_json"])
            details.update({"criacao_status": "numero_gerado", "numero_ot_criada": numero_ot})
            conn.execute(
                """UPDATE ronda_sharepoint_items
                   SET criacao_status='numero_gerado', numero_ot=?, criacao_em=?, criacao_erro=NULL, dados_json=?
                   WHERE sharepoint_id=?""",
                (numero_ot, now, json.dumps(details, ensure_ascii=False), int(sharepoint_id)),
            )


def marcar_ot_ronda_salva(sharepoint_ids: list[int], numero_ot: str) -> None:
    with get_connection() as conn:
        for sharepoint_id in sharepoint_ids:
            row = conn.execute(
                """SELECT dados_json FROM ronda_sharepoint_items
                   WHERE sharepoint_id=? AND criacao_status IN ('numero_gerado', 'salva') AND numero_ot=?""",
                (int(sharepoint_id), numero_ot),
            ).fetchone()
            if row is None:
                raise ValueError(f"OT {numero_ot} não está registrada para o item {sharepoint_id}.")
            details = json.loads(row["dados_json"])
            details.update({"criacao_status": "salva", "numero_ot_criada": numero_ot})
            conn.execute(
                """UPDATE ronda_sharepoint_items
                   SET criacao_status='salva', dados_json=? WHERE sharepoint_id=?""",
                (json.dumps(details, ensure_ascii=False), int(sharepoint_id)),
            )


def falhar_criacao_ronda(sharepoint_ids: list[int], message: str) -> None:
    with get_connection() as conn:
        for sharepoint_id in sharepoint_ids:
            row = conn.execute(
                     """SELECT dados_json, criacao_status, numero_ot FROM ronda_sharepoint_items
                         WHERE sharepoint_id=? AND criacao_status IN ('criando', 'numero_gerado', 'salva')""",
                (int(sharepoint_id),),
            ).fetchone()
            if row is None:
                continue
            details = json.loads(row["dados_json"])
            state = row["criacao_status"]
            if state == "criando":
                state = "erro"
            details.update({
                "criacao_status": state,
                "numero_ot_criada": row["numero_ot"],
                "criacao_erro": message,
            })
            conn.execute(
                """UPDATE ronda_sharepoint_items
                   SET criacao_status=?, criacao_erro=?, dados_json=? WHERE sharepoint_id=?""",
                (state, message[:1000], json.dumps(details, ensure_ascii=False), int(sharepoint_id)),
            )


def criar_sincronizacao(job_id: str, setores: list[str], tipo: str = "ots") -> None:
    now = datetime.now(timezone.utc).isoformat()
    message = "Sincronização recebida; aguardando iniciar o Firefox."
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO planejamento_sync_runs (
                job_id, status, etapa, mensagem, setores_json, iniciada_em, atualizada_em
            ) VALUES (?, 'queued', 'fila', ?, ?, ?, ?)
            """,
            (job_id, message, json.dumps(setores, ensure_ascii=False), now, now),
        )
        conn.execute("UPDATE planejamento_sync_runs SET tipo=? WHERE job_id=?", (tipo, job_id))
        conn.execute(
            """
            INSERT INTO planejamento_sync_events (job_id, nivel, etapa, mensagem, data_hora)
            VALUES (?, 'info', 'fila', ?, ?)
            """,
            (job_id, message, now),
        )


def atualizar_sincronizacao(
    job_id: str,
    *,
    status: str,
    etapa: str,
    mensagem: str,
    nivel: str = "info",
    erro: str | None = None,
    pagina: int | None = None,
    ots: int | None = None,
    ots_salvas: int | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    concluida_em = now if status in {"completed", "failed"} else None
    with get_connection() as conn:
        changed = conn.execute(
            """
            UPDATE planejamento_sync_runs SET
                status = ?, etapa = ?, mensagem = ?, erro = ?,
                pagina_atual = COALESCE(?, pagina_atual),
                ots_lidas = COALESCE(?, ots_lidas),
                ots_salvas = COALESCE(?, ots_salvas),
                atualizada_em = ?, concluida_em = COALESCE(?, concluida_em)
            WHERE job_id = ?
            """,
            (status, etapa, mensagem, erro, pagina, ots, ots_salvas, now, concluida_em, job_id),
        ).rowcount
        if changed:
            conn.execute(
                """
                INSERT INTO planejamento_sync_events (
                    job_id, nivel, etapa, mensagem, pagina, ots, data_hora
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, nivel, etapa, mensagem, pagina, ots, now),
            )


def obter_sincronizacao(job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        run = conn.execute(
            "SELECT * FROM planejamento_sync_runs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if run is None:
            return None
        events = conn.execute(
            """
            SELECT nivel, etapa, mensagem, pagina, ots, data_hora
            FROM planejamento_sync_events
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT 100
            """,
            (job_id,),
        ).fetchall()

    result = dict(run)
    result["setores"] = json.loads(result.pop("setores_json"))
    result["eventos"] = [dict(event) for event in reversed(events)]
    return result


def obter_ultima_sincronizacao() -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT job_id FROM planejamento_sync_runs WHERE tipo='ots' ORDER BY iniciada_em DESC LIMIT 1"
        ).fetchone()
    return obter_sincronizacao(row["job_id"]) if row else None


def _attribute_value(record: dict[str, Any], name: str, default: str = "") -> str:
    value = record.get(name, default)
    if isinstance(value, dict):
        value = value.get("value", value.get("_value", value.get("description", default)))
    return str(value) if value is not None else default


def upsert_ordens_trabalho(
    records: list[dict[str, Any]], setores: list[str],
    *, connection: sqlite3.Connection | None = None,
) -> int:
    selected_sectors = {setor.upper() for setor in setores}
    if not selected_sectors:
        raise ValueError("Selecione ao menos um setor de manutenção.")
    sincronizado_em = datetime.now(timezone.utc).isoformat()
    snapshot_date = datetime.now().astimezone().date().isoformat()
    salvas = 0

    with (nullcontext(connection) if connection is not None else get_connection()) as conn:
        for record in records:
            record = dict(record)
            wonum = _attribute_value(record, "wonum")
            if not wonum:
                raise ValueError("Uma OT recebida do BMA não contém o campo wonum.")

            siteid = _attribute_value(record, "siteid", "RES")
            status = _attribute_value(record, "status")
            maintenanceshop = _attribute_value(record, "maintenanceshop").upper()
            if maintenanceshop not in selected_sectors:
                raise ValueError(f"A OT {wonum} retornou com setor fora da seleção.")

            previous = conn.execute(
                "SELECT dados_json FROM ordens_trabalho WHERE siteid = ? AND wonum = ?",
                (siteid, wonum),
            ).fetchone()
            if previous:
                previous_record = json.loads(previous["dados_json"])
                if not record.get("wplabor") and previous_record.get("wplabor_lido_em"):
                    for field in ("wplabor", "wplabor_origem", "wplabor_lido_em"):
                        if field in previous_record:
                            record[field] = previous_record[field]
                changes = {
                    field: {
                        "anterior": previous_record.get(field),
                        "novo": record.get(field),
                    }
                    for field in sorted(previous_record.keys() | record.keys())
                    if previous_record.get(field) != record.get(field)
                }
                if changes:
                    conn.execute(
                        """
                        INSERT INTO ordens_trabalho_alteracoes (
                            siteid, wonum, maintenanceshop, alterado_em, alteracoes_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            siteid,
                            wonum,
                            maintenanceshop,
                            sincronizado_em,
                            json.dumps(changes, ensure_ascii=False),
                        ),
                    )

            serialized_record = json.dumps(record, ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO ordens_trabalho (
                    siteid, wonum, status, maintenanceshop, dados_json, sincronizado_em
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(siteid, wonum) DO UPDATE SET
                    status = excluded.status,
                    maintenanceshop = excluded.maintenanceshop,
                    dados_json = excluded.dados_json,
                    sincronizado_em = excluded.sincronizado_em
                """,
                (
                    siteid,
                    wonum,
                    status,
                    maintenanceshop,
                    serialized_record,
                    sincronizado_em,
                ),
            )
            conn.execute(
                """
                INSERT INTO ordens_trabalho_snapshots (
                    snapshot_date, siteid, wonum, status, maintenanceshop, dados_json, capturado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date, siteid, wonum) DO UPDATE SET
                    status = excluded.status,
                    maintenanceshop = excluded.maintenanceshop,
                    dados_json = excluded.dados_json,
                    capturado_em = excluded.capturado_em
                """,
                (
                    snapshot_date,
                    siteid,
                    wonum,
                    status,
                    maintenanceshop,
                    serialized_record,
                    sincronizado_em,
                ),
            )
            salvas += 1

    return salvas


def salvar_mao_de_obra_preparacao(siteid: str, wonum: str, linhas: list[dict[str, Any]]) -> int:
    if not isinstance(linhas, list) or any(not isinstance(linha, dict) for linha in linhas):
        raise ValueError("Linhas de mão de obra planejada inválidas.")
    coletado_em = datetime.now(timezone.utc).isoformat()
    snapshot_date = datetime.now().astimezone().date().isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT dados_json FROM ordens_trabalho WHERE siteid = ? AND wonum = ?",
            (siteid, wonum),
        ).fetchone()
        if not row:
            raise LookupError(f"OT {wonum} não está no banco local.")
        record = json.loads(row["dados_json"])
        record["wplabor"] = linhas
        record["wplabor_origem"] = "Preparação"
        record["wplabor_lido_em"] = coletado_em
        serialized = json.dumps(record, ensure_ascii=False)
        conn.execute(
            "UPDATE ordens_trabalho SET dados_json = ? WHERE siteid = ? AND wonum = ?",
            (serialized, siteid, wonum),
        )
        conn.execute(
            "UPDATE ordens_trabalho_snapshots SET dados_json = ?, capturado_em = ? "
            "WHERE snapshot_date = ? AND siteid = ? AND wonum = ?",
            (serialized, coletado_em, snapshot_date, siteid, wonum),
        )
    return len(linhas)


def salvar_planejamento(
    records: list[dict[str, Any]], setores: list[str], labor: list[dict[str, Any]],
    *, roster: list[dict] | None = None,
) -> int:
    """Substitui o cadastro de RES e grava OTs na mesma transação."""
    timestamp = datetime.now(timezone.utc).isoformat()
    keys: set[tuple[str, str]] = set()
    for record in labor:
        if (
            record.get("worksite") != "RES" or record.get("status") != "ACTIVE"
            or not record.get("laborcode") or not record.get("orgid")
        ):
            raise ValueError("Mão de obra inválida ou fora do escopo RES/ACTIVE.")
        key = (record["orgid"], record["laborcode"])
        if key in keys:
            raise ValueError("Mão de obra duplicada no cadastro recebido.")
        keys.add(key)
    with get_connection() as conn:
        saved = upsert_ordens_trabalho(records, setores, connection=conn)
        conn.execute("DELETE FROM mao_de_obra WHERE worksite = ?", ("RES",))
        conn.executemany(
            """INSERT INTO mao_de_obra
               (orgid, laborcode, worksite, worklocation, nome, setor, dados_json, sincronizado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(r["orgid"], r["laborcode"], r["worksite"], r.get("worklocation") or "", r.get("fullname") or "",
              r.get("maintenanceshop") or "", json.dumps(r, ensure_ascii=False), timestamp)
             for r in labor],
        )
        conn.execute(
            """INSERT INTO mao_de_obra_sync VALUES (?, ?, ?)
               ON CONFLICT(worksite) DO UPDATE SET
               sincronizado_em=excluded.sincronizado_em, quantidade=excluded.quantidade""",
            ("RES", timestamp, len(labor)),
        )
        if roster is not None:
            if not roster or len({r["id"] for r in roster}) != len(roster):
                raise ValueError("Lista NF vazia ou com IDs duplicados; cadastro anterior preservado.")
            conn.execute(
                """INSERT INTO nf_ativos VALUES (1, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET dados_json=excluded.dados_json,
                   sincronizado_em=excluded.sincronizado_em""",
                (json.dumps(roster, ensure_ascii=False), timestamp),
            )
            conn.execute(
                f"DELETE FROM nf_vinculos WHERE sharepoint_id NOT IN ({','.join('?' for _ in roster)})",
                [r["id"] for r in roster],
            )
    return saved


def listar_especialidades(orgid: str = "BR") -> list[dict[str, str]]:
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT orgid, codigo, descricao FROM especialidades WHERE orgid=? ORDER BY descricao",
            (orgid,),
        )]


def _chave_setores(setores: list[str]) -> str:
    return "|".join(sorted(set(s.upper() for s in setores)))


def obter_equipe(setores: list[str]) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT dados_json FROM planejamento_equipes WHERE setores=?", (_chave_setores(setores),),
        ).fetchone()
    return json.loads(row["dados_json"]) if row else None


def _salvar_equipe_atual(conn: sqlite3.Connection, plan: dict) -> None:
    sectors = _chave_setores(plan["setores"])
    serialized = json.dumps(plan, ensure_ascii=False)
    conn.execute(
        """INSERT INTO planejamento_equipes (setores, dados_json) VALUES (?, ?)
           ON CONFLICT(setores) DO UPDATE SET dados_json=excluded.dados_json""",
        (sectors, serialized),
    )
    conn.execute(
        "INSERT INTO planejamento_historico (setores, salvo_em, dados_json) VALUES (?, ?, ?)",
        (sectors, datetime.now(timezone.utc).isoformat(), serialized),
    )
    conn.execute(
        """DELETE FROM planejamento_historico WHERE setores=? AND id NOT IN
           (SELECT id FROM planejamento_historico WHERE setores=? ORDER BY id DESC LIMIT 10)""",
        (sectors, sectors),
    )


def salvar_equipe(plan: dict) -> None:
    with get_connection() as conn:
        _salvar_equipe_atual(conn, plan)


def listar_equipes_salvas(setores: list[str]) -> list[dict]:
    sectors = _chave_setores(setores)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT nome, salvo_em, dados_json FROM planejamento_equipes_salvas WHERE setores=? ORDER BY nome_normalizado",
            (sectors,),
        )
        return [{"nome": row["nome"], "salvo_em": row["salvo_em"], "planejamento": json.loads(row["dados_json"])}
                for row in rows]


def salvar_equipe_nomeada(plan: dict, nome: str, *, persistir_atual: bool = True) -> dict:
    name = " ".join(nome.split())
    if not name or len(name) > 80:
        raise ValueError("Informe um nome de equipe com até 80 caracteres.")
    sectors = _chave_setores(plan["setores"])
    serialized = json.dumps(plan, ensure_ascii=False)
    saved_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        if persistir_atual:
            _salvar_equipe_atual(conn, plan)
        conn.execute(
            """INSERT INTO planejamento_equipes_salvas
               (setores, nome_normalizado, nome, salvo_em, dados_json) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(setores, nome_normalizado) DO UPDATE SET
               nome=excluded.nome, salvo_em=excluded.salvo_em, dados_json=excluded.dados_json""",
            (sectors, name.casefold(), name, saved_at, serialized),
        )
    return {"nome": name, "salvo_em": saved_at, "planejamento": plan}


def listar_historico(setores: list[str]) -> list[dict]:
    with get_connection() as conn:
        return [{"id": r["id"], "salvo_em": r["salvo_em"], "planejamento": json.loads(r["dados_json"])}
                for r in conn.execute(
                    "SELECT * FROM planejamento_historico WHERE setores=? ORDER BY id DESC LIMIT 10",
                    (_chave_setores(setores),),
                )]


def equipe_padrao(setores: list[str], planejador: str, plan: dict | None = None) -> dict | None:
    identity = planejador.strip().casefold()
    if not identity:
        raise ValueError("Informe o nome/matrícula do planejador.")
    with get_connection() as conn:
        if plan is not None:
            conn.execute(
                """INSERT INTO planejamento_padroes VALUES (?, ?, ?)
                   ON CONFLICT(setores, planejador) DO UPDATE SET dados_json=excluded.dados_json""",
                (_chave_setores(setores), identity, json.dumps(plan, ensure_ascii=False)),
            )
        row = conn.execute(
            "SELECT dados_json FROM planejamento_padroes WHERE setores=? AND planejador=?",
            (_chave_setores(setores), identity),
        ).fetchone()
    return json.loads(row["dados_json"]) if row else None


def conferencia_nf(setores: list[str]) -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM nf_ativos WHERE id=1").fetchone()
        mappings = {str(r["sharepoint_id"]): dict(r) for r in conn.execute("SELECT * FROM nf_vinculos")}
    candidates = listar_mao_de_obra(None, filtrar_nf=False)["profissionais"]
    result = vincular_ativos(json.loads(row["dados_json"]) if row else [], candidates, mappings)
    return {**result, "verificada": row is not None,
            "sincronizado_em": row["sincronizado_em"] if row else None, "candidatos": candidates}


def salvar_vinculo_nf(setores: list[str], sharepoint_id: int, orgid: str, matricula: str) -> None:
    current = conferencia_nf(setores)
    rows = current["pendentes"] + current["vinculados"]
    if not any(r["id"] == sharepoint_id for r in rows):
        raise ValueError("Funcionário não consta na lista SharePoint atual.")
    if not any(p["orgid"] == orgid and p["matricula"] == matricula for p in current["candidatos"]):
        raise ValueError("Executante não pertence ao cadastro BMA da unidade RES.")
    if any(r["id"] != sharepoint_id and r["orgid"] == orgid and r["matricula_bma"] == matricula
           for r in current["vinculados"]):
        raise ValueError("Essa matrícula já está vinculada a outro funcionário SharePoint.")
    with get_connection() as conn:
        try:
            conn.execute(
                """INSERT INTO nf_vinculos VALUES (?, ?, ?)
                   ON CONFLICT(sharepoint_id) DO UPDATE SET orgid=excluded.orgid, matricula=excluded.matricula""",
                (sharepoint_id, orgid, matricula),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Essa matrícula já possui outro vínculo SharePoint.") from exc


def listar_mao_de_obra(setores: list[str] | None = None, *, filtrar_nf: bool = True) -> dict[str, Any]:
    query = "SELECT * FROM mao_de_obra WHERE worksite='RES'"
    parameters: list[str] = []
    nf_scope = bool(setores and "RES-TC-NF" in {s.upper() for s in setores})
    if setores is not None:
        parameters = sorted(set(setor.upper() for setor in setores))
        if not parameters:
            raise ValueError("Selecione ao menos um setor de manutenção.")
        if not (filtrar_nf and nf_scope):
            query += f" AND (UPPER(setor) IN ({','.join('?' for _ in parameters)}) OR UPPER(worklocation) = 'NFE')"
        else:
            parameters = []
    query += " ORDER BY nome, laborcode"
    with get_connection() as conn:
        sync = conn.execute(
            "SELECT sincronizado_em FROM mao_de_obra_sync WHERE worksite='RES'"
        ).fetchone()
        descriptions = {
            (r["orgid"], r["codigo"]): r["descricao"]
            for r in conn.execute("SELECT orgid, codigo, descricao FROM especialidades")
        }
        people = []
        for row in conn.execute(query, parameters):
            record = json.loads(row["dados_json"])
            crafts = []
            for craft in record.get("laborcraftrate", []):
                code = str(craft.get("craft") or "")
                crafts.append({
                    "codigo": code,
                    "descricao": descriptions.get((row["orgid"], code)),
                    "nivel": craft.get("skilllevel"),
                    "principal": craft.get("defaultcraft", False),
                })
            people.append({
                "orgid": row["orgid"], "matricula": row["laborcode"],
                "personid": record.get("personid"), "nome": row["nome"],
                "unidade": row["worksite"], "local_trabalho": row["worklocation"],
                "setor": row["setor"],
                "status": record["status"], "especialidades": crafts,
            })
    verification = {"necessaria": nf_scope,
                    "verificada": False, "sincronizado_em": None, "pendentes": 0}
    if filtrar_nf and verification["necessaria"]:
        nf = conferencia_nf(setores)
        allowed = {(r["orgid"], r["matricula_bma"]) for r in nf["vinculados"]}
        other_sectors = {s.upper() for s in setores} - {"RES-TC-NF"}
        people = [{**p, "nf_ativo": (p["orgid"], p["matricula"]) in allowed}
                  for p in people if (p["orgid"], p["matricula"]) in allowed
                  or (p["setor"].upper() in other_sectors and p["local_trabalho"].upper() != "NFE")]
        verification.update(verificada=nf["verificada"], sincronizado_em=nf["sincronizado_em"],
                            pendentes=len(nf["pendentes"]))
    return {"unidade": "RES", "sincronizado_em": sync["sincronizado_em"] if sync else None,
            "total": len(people), "profissionais": people, "verificacao_nf": verification}


def listar_ordens_trabalho(
    setores: list[str],
    statuses: list[str] | None = None,
) -> list[dict[str, Any]]:
    selected_sectors = list(dict.fromkeys(setor.upper() for setor in setores))
    if not selected_sectors:
        return []
    query = """
         SELECT siteid, wonum, status, maintenanceshop, dados_json, sincronizado_em,
             lead, schedstart, planning_status
        FROM ordens_trabalho
        WHERE maintenanceshop IN ({sector_placeholders})
    """
    query = query.format(sector_placeholders=", ".join("?" for _ in selected_sectors))
    parameters: list[Any] = selected_sectors
    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        query += f" AND status IN ({placeholders})"
        parameters.extend(statuses)
    query += " ORDER BY wonum"

    with get_connection() as conn:
        rows = conn.execute(query, parameters).fetchall()

    return [
        {
            "siteid": row["siteid"],
            "wonum": row["wonum"],
            "status": row["status"],
            "maintenanceshop": row["maintenanceshop"],
            "dados": json.loads(row["dados_json"]),
            "lead": row["lead"],
            "schedstart": row["schedstart"],
            "planning_status": row["planning_status"],
            "sincronizado_em": row["sincronizado_em"],
        }
        for row in rows
    ]


def listar_alteracoes_ordens_trabalho(
    setores: list[str], limit: int = 200,
) -> list[dict[str, Any]]:
    selected_sectors = list(dict.fromkeys(setor.upper() for setor in setores))
    if not selected_sectors:
        return []
    placeholders = ", ".join("?" for _ in selected_sectors)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, siteid, wonum, maintenanceshop, alterado_em, alteracoes_json
            FROM ordens_trabalho_alteracoes
            WHERE maintenanceshop IN ({placeholders})
            ORDER BY id DESC
            LIMIT ?
            """,
            [*selected_sectors, max(1, min(limit, 500))],
        ).fetchall()
    return [
        {
            "id": row["id"],
            "siteid": row["siteid"],
            "wonum": row["wonum"],
            "maintenanceshop": row["maintenanceshop"],
            "alterado_em": row["alterado_em"],
            "alteracoes": json.loads(row["alteracoes_json"]),
        }
        for row in rows
    ]
