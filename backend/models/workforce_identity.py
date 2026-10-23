import re
import unicodedata


def normalizar(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", "".join(
        c for c in text.upper() if not unicodedata.combining(c)
    )).split())


def vincular_ativos(roster: list[dict], people: list[dict], mappings: dict) -> dict:
    identities = {(p["orgid"], p["matricula"]): p for p in people}
    proposals = []
    for row in roster:
        explicit = mappings.get(str(row["id"]))
        matches = []
        if explicit:
            key = (explicit["orgid"], explicit["matricula"])
            if key in identities:
                matches = [key]
        elif row.get("matricula"):
            matches = [key for key, p in identities.items()
                       if normalizar(row["matricula"]) in {normalizar(p["matricula"]), normalizar(p.get("personid") or "")}]
        else:
            matches = [key for key, p in identities.items() if normalizar(row["nome"]) == normalizar(p["nome"])]
        proposals.append((row, matches))
    counts = {}
    for _, matches in proposals:
        if len(matches) == 1:
            counts[matches[0]] = counts.get(matches[0], 0) + 1
    linked, pending = [], []
    for row, matches in proposals:
        if len(matches) == 1 and counts[matches[0]] == 1:
            linked.append({**row, "orgid": matches[0][0], "matricula_bma": matches[0][1]})
        else:
            pending.append({**row, "motivo": "Vínculo ausente ou ambíguo; confirme a identidade no BMA."})
    return {"vinculados": linked, "pendentes": pending}
