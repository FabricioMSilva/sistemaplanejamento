from collections import defaultdict
from datetime import date, timedelta


def week_start(day: str) -> str:
    value = date.fromisoformat(day)
    return (value - timedelta(days=value.weekday())).isoformat()


def weekly_totals(documents: list[dict]) -> dict:
    available = defaultdict(set)
    absent = set()
    loads = defaultdict(float)
    for doc in documents:
        absent.update((a["executante"], a["dia"]) for a in doc["indisponibilidades"])
        for person in doc["pessoas"]:
            for day in person["dias"]:
                if doc["inicio"] <= day <= doc["fim"]:
                    available[(person["id"], week_start(day))].add(day)
        for block in doc["blocos"]:
            for person in block["executantes"]:
                loads[(person, week_start(block["dia"]))] += block["horas"]
    keys = available.keys() | loads.keys()
    return {key: {
        "capacidade": 8 * sum((key[0], day) not in absent for day in available[key]),
        "horas": loads[key],
    } for key in keys}


def overloaded_blocks(doc: dict) -> set[str]:
    totals = weekly_totals([doc])
    return {block["id"] for block in doc["blocos"] if any(
        totals[(person, week_start(block["dia"]))]["horas"]
        > totals[(person, week_start(block["dia"]))]["capacidade"] + 1e-6
        for person in block["executantes"])}
