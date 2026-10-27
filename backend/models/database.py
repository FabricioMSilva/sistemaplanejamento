import json
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from .workforce_identity import vincular_ativos

ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = ROOT_DIR / "database" / "data" / "bma_intranet.db"


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
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ordens_trabalho_setor_status
            ON ordens_trabalho (maintenanceshop, status)
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
        conn.commit()


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
    salvas = 0

    with (nullcontext(connection) if connection is not None else get_connection()) as conn:
        for record in records:
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
            serialized_record = json.dumps(record, ensure_ascii=False)
            if previous:
                previous_record = json.loads(previous["dados_json"])
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
            salvas += 1

    return salvas


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


def salvar_equipe(plan: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO planejamento_equipes (setores, dados_json) VALUES (?, ?)
               ON CONFLICT(setores) DO UPDATE SET dados_json=excluded.dados_json""",
            (_chave_setores(plan["setores"]), json.dumps(plan, ensure_ascii=False)),
        )
        conn.execute(
            "INSERT INTO planejamento_historico (setores, salvo_em, dados_json) VALUES (?, ?, ?)",
            (_chave_setores(plan["setores"]), datetime.now(timezone.utc).isoformat(), json.dumps(plan, ensure_ascii=False)),
        )
        conn.execute(
            """DELETE FROM planejamento_historico WHERE setores=? AND id NOT IN
               (SELECT id FROM planejamento_historico WHERE setores=? ORDER BY id DESC LIMIT 10)""",
            (_chave_setores(plan["setores"]), _chave_setores(plan["setores"])),
        )


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
        SELECT siteid, wonum, status, maintenanceshop, dados_json, sincronizado_em
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
