from collections import defaultdict
from datetime import date
from io import BytesIO
from math import ceil
from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Circle, Drawing, Group, Line, PolyLine, Rect, String, Wedge
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    KeepTogether, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from services.pcm_planning import mode_for, order_key, text

BLUE = colors.HexColor("#003B80")
NAVY = colors.HexColor("#00245D")
YELLOW = colors.HexColor("#FFDD00")
PALE = colors.HexColor("#EAF2FC")
INK = colors.HexColor("#163252")
MUTED = colors.HexColor("#53677F")
GREEN = colors.HexColor("#19794A")
ORANGE = colors.HexColor("#A56800")
RED = colors.HexColor("#B83B38")
WEEKDAYS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
BRAND_IMAGE = Path(__file__).resolve().parents[1] / "assets" / "LogoMichelin-transparente.png"


def number(value):
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".").removesuffix(",00")


def formatted_day(value):
    return date.fromisoformat(value).strftime("%d/%m/%Y")


def formatted_optional_day(value):
    try:
        return formatted_day(str(value or "")[:10])
    except ValueError:
        return "—"


def icon(kind, x=0, y=0, size=22, color=BLUE):
    group = Group()
    def line(points):
        group.add(PolyLine(points, strokeColor=color, strokeWidth=1.7, fillColor=None))
    if kind == "orders":
        group.add(Rect(4, 1, 16, 20, rx=2, fillColor=None, strokeColor=color, strokeWidth=1.7))
        group.add(Rect(8, 19, 8, 4, rx=1, fillColor=colors.white, strokeColor=color, strokeWidth=1.5))
        for height in (7, 11, 15):
            line([8, height, 16, height])
    elif kind == "clock":
        group.add(Circle(12, 12, 10, fillColor=None, strokeColor=color, strokeWidth=1.8))
        line([12, 19, 12, 12, 17, 9])
    elif kind == "people":
        for cx, cy, radius in ((12, 17, 3.5), (4, 15, 2.5), (20, 15, 2.5)):
            group.add(Circle(cx, cy, radius, fillColor=color, strokeColor=None))
        for left, bottom, width, height in ((7, 3, 10, 9), (0, 4, 5, 7), (19, 4, 5, 7)):
            group.add(Rect(left, bottom, width, height, rx=2, fillColor=color, strokeColor=None))
    elif kind == "location":
        group.add(Circle(12, 15, 7, fillColor=color, strokeColor=None))
        group.add(PolyLine([6, 11, 12, 1, 18, 11], fillColor=color, strokeColor=color))
        group.add(Circle(12, 15, 2.6, fillColor=colors.white, strokeColor=None))
    else:
        for index, height in enumerate((8, 14, 21)):
            group.add(Rect(2 + index * 7, 2, 4.5, height, fillColor=color, strokeColor=None))
    group.scale(size / 24, size / 24)
    group.translate(x * 24 / size, y * 24 / size)
    return group


def kpi_strip(metrics, width):
    drawing = Drawing(width, 49)
    drawing.hAlign = "LEFT"
    cell = width / 5
    drawing.add(Rect(0, 0, width, 49, rx=4, fillColor=colors.HexColor("#F3F7FC"), strokeColor=colors.HexColor("#D4E0F1")))
    for index, (value, label) in enumerate(metrics):
        x = index * cell
        if index:
            drawing.add(Line(x, 10, x, 39, strokeColor=colors.HexColor("#D4E0F1"), strokeWidth=.5))
        drawing.add(icon(("orders", "clock", "people", "location", "load")[index], x + 9, 14, 22))
        drawing.add(String(x + 39, 27, str(value), fontName="Helvetica-Bold", fontSize=13, fillColor=BLUE))
        drawing.add(String(x + 39, 15, label, fontName="Helvetica", fontSize=5.6, fillColor=MUTED))
    return drawing


def summary(doc):
    orders = {order_key(o): o for o in doc["ordens"]}
    allocated = defaultdict(float)
    daily = defaultdict(float)
    used_people = set()
    from services.pcm_capacity import overloaded_blocks
    conflicts = overloaded_blocks(doc)
    for block in doc["blocos"]:
        allocated[block["ot"]] += block["horas"]
        daily[block["dia"]] += block["horas"] * len(block["executantes"])
        used_people.update(block["executantes"])
    groups = {"Programadas": [], "Parciais": [], "Não alocadas": []}
    corrective_by_status = defaultdict(int)
    groups_by_type = {kind: {status: 0 for status in groups}
                      for kind in ("PM1", "PM2", "PM3", "Outras PM")}
    for key in orders:
        duration = doc["requisitos"][key]["duracao"]
        status = "Não alocadas" if not allocated[key] else (
            "Programadas" if duration and allocated[key] >= duration - 1e-6 else "Parciais")
        groups[status].append(key)
        mode = mode_for(orders[key])
        if mode != "corretiva":
            level = re.match(r"^PM\s*([123])\b", text(orders[key], "description").strip(), re.IGNORECASE)
            kind = f"PM{level.group(1)}" if level else "Outras PM"
            groups_by_type[kind][status] += 1
    absence = {(a["executante"], a["dia"]) for a in doc["indisponibilidades"]}
    capacity = sum(8 for p in doc["pessoas"] for day in p["dias"] if (p["id"], day) not in absence)
    locations = {text(orders[key], "location").strip() for key in allocated if allocated[key]}
    locations.discard("")
    unprogrammed_corrective = [key for key in groups["Não alocadas"]
                               if mode_for(orders[key]) == "corretiva"]
    for key in unprogrammed_corrective:
        corrective_by_status[text(orders[key], "status").strip().upper() or "SEM STATUS"] += 1
    return {"orders": orders, "allocated": allocated, "daily": dict(sorted(daily.items())),
            "groups": groups, "corrective_by_status": dict(sorted(corrective_by_status.items())),
            "unprogrammed_corrective": unprogrammed_corrective,
            "groups_by_type": groups_by_type,
            "hours": sum(daily.values()), "capacity": capacity,
            "people": len(used_people), "locations": len(locations), "conflicts": conflicts}


def dashboard(data, width):
    height = 143
    drawing = Drawing(width, height)
    gap = 9
    panel = (width - 2 * gap) / 3
    for index, title in enumerate(("RESUMO DA SEMANA", "CARGA DIÁRIA · HH", "COBERTURA DA CARTEIRA")):
        x = index * (panel + gap)
        drawing.add(Rect(x, 0, panel, height, rx=4, fillColor=colors.white, strokeColor=colors.HexColor("#D4E0F1")))
        drawing.add(String(x + 9, height - 18, title, fontName="Helvetica-Bold", fontSize=8, fillColor=BLUE))
    for index, (value, label) in enumerate((
        (len(data["groups"]["Programadas"]), "OTs totalmente programadas"),
        (f'{number(data["hours"])} HH', "mão de obra comprometida"),
        (f'{number(data["capacity"] - data["hours"])} HH', "saldo da equipe no horizonte"),
        (data["people"], "executantes com alocação"),
    )):
        y = height - 40 - index * 28
        drawing.add(icon(("orders", "clock", "load", "people")[index], 10, y - 5, 19))
        drawing.add(String(38, y, str(value), fontName="Helvetica-Bold", fontSize=13, fillColor=BLUE))
        drawing.add(String(38, y - 10, label, fontName="Helvetica", fontSize=6.1, fillColor=MUTED))
    daily = list(data["daily"].items())
    # For long horizons, aggregate consecutive groups; the daily table retains exact values.
    group_size = max(1, ceil(len(daily) / 7))
    bars = [(daily[i][0], sum(value for _, value in daily[i:i + group_size]))
            for i in range(0, len(daily), group_size)]
    chart_x = panel + gap + 12
    chart_width = panel - 24
    if bars:
        max_hours = max(value for _, value in bars)
        step = chart_width / len(bars)
        for index, (day, value) in enumerate(bars):
            h = value / max_hours * 64 if max_hours else 0
            x = chart_x + index * step + step * .15
            drawing.add(Rect(x, 38, step * .7, h, fillColor=BLUE if index % 2 == 0 else YELLOW, strokeColor=None))
            drawing.add(String(x + step * .35, 43 + h, number(value), textAnchor="middle", fontSize=7, fillColor=BLUE))
            drawing.add(String(x + step * .35, 26, day[8:] + "/" + day[5:7], textAnchor="middle", fontSize=6.5, fillColor=MUTED))
        drawing.add(String(chart_x, 10, "Por dia" if group_size == 1 else f"Grupos de até {group_size} dias com carga", fontSize=6.5, fillColor=MUTED))
    else:
        drawing.add(String(chart_x, 75, "Sem carga alocada", fontSize=9, fillColor=MUTED))
    x = 2 * (panel + gap)
    cx, cy, radius = x + panel / 2, 82, 27
    total = len(data["orders"])
    start = 90
    for (label, keys), color in zip(data["groups"].items(), (GREEN, ORANGE, colors.HexColor("#9AACC4"))):
        angle = len(keys) / total * 360 if total else 0
        if angle:
            drawing.add(Wedge(cx, cy, radius, start, start + angle, fillColor=color, strokeColor=None))
            start += angle
    if not total:
        drawing.add(Circle(cx, cy, radius, fillColor=PALE, strokeColor=None))
    drawing.add(Circle(cx, cy, radius * .67, fillColor=colors.white, strokeColor=None))
    drawing.add(String(cx, cy + 1, str(total), textAnchor="middle", fontName="Helvetica-Bold", fontSize=16, fillColor=BLUE))
    drawing.add(String(cx, cy - 12, "OTs", textAnchor="middle", fontSize=8, fillColor=BLUE))
    for index, ((label, keys), color) in enumerate(zip(data["groups"].items(), (GREEN, ORANGE, colors.HexColor("#9AACC4")))):
        y = 39 - index * 13
        drawing.add(Circle(x + 12, y + 2, 3, fillColor=color, strokeColor=None))
        drawing.add(String(x + 20, y, f"{label}: {len(keys)}", fontSize=7, fillColor=INK))
    return drawing


def status_count_chart(data, width):
    height = 116
    drawing = Drawing(width, height)
    rows = list(data["corrective_by_status"].items())
    maximum = max((value for _, value in rows), default=0) or 1
    left, right, bottom, top = 42, width - 10, 24, 82
    plot_height = top - bottom
    drawing.add(String(0, 103, "BACKLOG · OTs TIPO E NÃO ALOCADAS POR STATUS", fontName="Helvetica-Bold", fontSize=8, fillColor=BLUE))
    drawing.add(Rect(8, 88, 8, 6, fillColor=BLUE, strokeColor=None))
    drawing.add(String(20, 88, "Quantidade", fontSize=6.5, fillColor=INK))
    for tick in range(5):
        fraction = tick / 4
        y = bottom + plot_height * fraction
        drawing.add(Line(left, y, right, y, strokeColor=colors.HexColor("#E4EAF2"), strokeWidth=.45))
        drawing.add(String(left - 5, y - 2, str(round(maximum * fraction)), textAnchor="end", fontSize=5.5, fillColor=MUTED))
    step = (right - left) / max(1, len(rows))
    bar_width = min(32, max(8, step * .58))
    status_font_size = max(4.4, min(6.5, step / 5))
    for index, (status, count) in enumerate(rows):
        center = left + step * (index + .5)
        bar_height = plot_height * count / maximum
        drawing.add(Rect(center - bar_width / 2, bottom, bar_width, bar_height, fillColor=BLUE, strokeColor=None))
        drawing.add(String(center, bottom + bar_height + 2, str(count), textAnchor="middle",
                           fontName="Helvetica-Bold", fontSize=6.5, fillColor=INK))
        drawing.add(String(center, bottom - 12, status, textAnchor="middle", fontSize=status_font_size, fillColor=INK))
    if not any(count for _, count in rows):
        drawing.add(String((left + right) / 2, 52, "Sem OTs tipo E", textAnchor="middle", fontSize=8, fillColor=MUTED))
    return drawing


def pm_status_chart(data, width):
    height = 124
    drawing = Drawing(width, height)
    statuses = (("Programadas", GREEN), ("Parciais", ORANGE),
                ("Não alocadas", colors.HexColor("#9AACC4")))
    groups = data["groups_by_type"]
    maximum = max((counts[status] for counts in groups.values() for status, _ in statuses), default=0) or 1
    left, right, bottom, top = 42, width - 10, 25, 88
    plot_height = top - bottom
    drawing.add(String(0, 111, "PM · QUANTIDADE POR TIPO E STATUS", fontName="Helvetica-Bold", fontSize=8, fillColor=BLUE))
    for index, (label, color) in enumerate(statuses):
        x = 8 + index * 126
        drawing.add(Rect(x, 96, 8, 7, fillColor=color, strokeColor=None))
        drawing.add(String(x + 12, 96, label, fontSize=6.2, fillColor=INK))
    for tick in range(4):
        fraction = tick / 3
        y = bottom + plot_height * fraction
        drawing.add(Line(left, y, right, y, strokeColor=colors.HexColor("#E4EAF2"), strokeWidth=.45))
        drawing.add(String(left - 5, y - 2, str(round(maximum * fraction)), textAnchor="end", fontSize=5.5, fillColor=MUTED))
    step = (right - left) / max(1, len(groups))
    bar_width = 15
    bar_gap = 3
    for index, (kind, counts) in enumerate(groups.items()):
        center = left + step * (index + .5)
        start = center - (len(statuses) * bar_width + (len(statuses) - 1) * bar_gap) / 2
        for bar_index, (status, color) in enumerate(statuses):
            count = counts[status]
            bar_height = plot_height * count / maximum
            x = start + bar_index * (bar_width + bar_gap)
            if count:
                drawing.add(Rect(x, bottom, bar_width, bar_height, fillColor=color, strokeColor=None))
            drawing.add(String(x + bar_width / 2, bottom + bar_height + 2, str(count), textAnchor="middle",
                               fontName="Helvetica-Bold", fontSize=5.5, fillColor=INK))
        drawing.add(String(center, 8, kind, textAnchor="middle", fontSize=6.5, fillColor=INK))
    return drawing


def render_schedule(doc):
    output = BytesIO()
    # Platypus adds 6 pt of frame padding; keep the visible content on the 24 pt grid.
    pdf = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=18, rightMargin=18, topMargin=92, bottomMargin=45,
        title=f"Planejamento semanal - revisão {doc['revisao']}", author="Centro PCM",
    )
    width = A4[0] - 48
    data = summary(doc)
    orders = data["orders"]
    people = {p["id"]: p["nome"] for p in doc["pessoas"]}
    styles = {
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=6.6, leading=8, textColor=INK, splitLongWords=True),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=6, leading=8, textColor=MUTED, splitLongWords=True),
        "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.white),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=BLUE, spaceAfter=7),
        "metric": ParagraphStyle("metric", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=BLUE, alignment=TA_CENTER),
    }
    for name in ("body", "small", "head"):
        styles[f"{name}_center"] = ParagraphStyle(f"{name}_center", parent=styles[name], alignment=TA_CENTER)
    styles["label"] = ParagraphStyle("label", parent=styles["small"], fontName="Helvetica-Bold", textColor=BLUE)
    def p(value, style="body"):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])
    def table(rows, widths, header=True):
        grid = LongTable(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT", splitInRow=1)
        rules = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                 ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#DCE4F0"))]
        if header:
            rules += [("BACKGROUND", (0, 0), (-1, 0), BLUE),
                      ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7FC")])]
        grid.setStyle(TableStyle(rules))
        return grid

    def page(canvas, document):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(NAVY)
        canvas.rect(0, h - 88, w, 88, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor("#F7F9FC"))
        canvas.rect(0, h - 88, 215, 88, fill=1, stroke=0)
        canvas.drawImage(str(BRAND_IMAGE), 8, h - 80, width=203, height=72,
                 mask="auto", preserveAspectRatio=True, anchor="c")
        canvas.setStrokeColor(colors.HexColor("#7F9DC4"))
        canvas.line(218, h - 12, 218, h - 76)
        canvas.setFillColor(YELLOW)
        path = canvas.beginPath()
        path.moveTo(505, h); path.lineTo(513, h)
        path.lineTo(485, h - 88); path.lineTo(477, h - 88); path.close()
        canvas.drawPath(path, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(228, h - 29, "PLANEJAMENTO SEMANAL")
        canvas.setFillColor(YELLOW)
        canvas.setFont("Helvetica-BoldOblique", 12)
        canvas.drawString(228 + canvas.stringWidth("PLANEJAMENTO SEMANAL ", "Helvetica-Bold", 12), h - 29, "NFE")
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(228, h - 47, f"{formatted_day(doc['inicio'])} a {formatted_day(doc['fim'])}")
        canvas.setFont("Helvetica-Oblique", 6.5)
        canvas.drawString(228, h - 67, "PLANEJAMENTO HOJE, PERFORMANCE SEMPRE")
        canvas.setFont("Helvetica-BoldOblique", 7)
        for index, line in enumerate(("PESSOAS", "DESEMPENHO", "RESULTADOS", "SEMPRE")):
            canvas.drawString(520, h - 29 - index * 10, line)
        canvas.setStrokeColor(colors.HexColor("#CCD9EA"))
        canvas.line(24, 34, w - 24, 34)
        canvas.setFillColor(BLUE)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawString(24, 23, "SEGURANÇA  •  PESSOAS  •  RESULTADOS")
        canvas.setFont("Helvetica", 6)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(w - 24, 23, f"Centro PCM | Revisão {doc['revisao']} | Página {document.page}")
        canvas.drawString(24, 12, f"Plano {doc['id']} | Registro {doc['atualizado_em']}")
        canvas.restoreState()

    metrics = [
        (len([key for key, value in data["allocated"].items() if value > 0]), "OTs com alocação"),
        (number(data["hours"]), "HH comprometidos"),
        (data["people"], "Recursos alocados"),
        (data["locations"], "Locais informados"),
        (f'{number(data["hours"] / data["capacity"] * 100)}%' if data["capacity"] else "—", "Ocupação da equipe"),
    ]
    cards = kpi_strip(metrics, width)
    metadata = Table([
        [p("PLANEJADOR", "label"), p(doc["planejador"]), p("REVISÃO / SITUAÇÃO", "label"), p(f"{doc['revisao']} · {doc['status'].upper()} LOCAL")],
        [p("SETORES", "label"), p(", ".join(doc["setores"])), "", ""],
        [p("MOTIVO", "label"), p(doc["motivo"]), "", ""],
    ], colWidths=[75, width * .5 - 75, 95, width * .5 - 95], hAlign="LEFT")
    metadata.setStyle(TableStyle([
        ("SPAN", (1, 1), (-1, 1)), ("SPAN", (1, 2), (-1, 2)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#DCE4F0")),
    ]))
    notice = Table([[p("Documento local. BMA: envio pendente de configuração. SharePoint: upload pendente. "
                 "Programação por dia, sem hora de início. Referência: 8 h/dia disponível; "
                 "carga diária flexível, limitada à capacidade semanal individual (segunda a domingo). "
                 "Programação não comprova execução nem liberação de segurança.", "small")]], colWidths=[width], hAlign="LEFT")
    notice.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F7FC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    content = [cards, Spacer(1, 7), metadata, Spacer(1, 6), notice,
               Spacer(1, 10), p("CRONOGRAMA INTEGRADO · PREVENTIVA + CORRETIVA", "title")]
    if data["conflicts"]:
        warning_style = ParagraphStyle("warning", parent=styles["body"], textColor=RED, fontName="Helvetica-Bold")
        content.extend([Paragraph(f'PRÉVIA COM SOBRECARGA SEMANAL: {len(data["conflicts"])} alocações excedem a capacidade semanal. '
                                 'Confirmação bloqueada até reorganizar. Programada indica duração alocada, não viabilidade.', warning_style),
                        Spacer(1, 8)])
    by_day = defaultdict(list)
    for block in doc["blocos"]:
        by_day[block["dia"]].append(block)
    for day, blocks in sorted(by_day.items()):
        label = f"{WEEKDAYS[date.fromisoformat(day).weekday()]} · {formatted_day(day)}"
        headers = ("Dia", "Recurso / equipe", "OT / tipo", "Local", "Descrição", "h / HH", "Data Limite")
        day_style = ParagraphStyle("day", parent=styles["body_center"], textColor=BLUE, fontName="Helvetica-Bold", fontSize=8, leading=12)
        day_label = Paragraph(f'{WEEKDAYS[date.fromisoformat(day).weekday()]}<br/>{date.fromisoformat(day).strftime("%d/%m")}', day_style)
        rows = [[p(h, "head_center" if index in (0, 2, 5, 6) else "head") for index, h in enumerate(headers)]]
        for block in blocks:
            key = block["ot"]
            order = orders[key]
            rows.append([
                day_label,
                p("\n".join(people[member] for member in block["executantes"])),
                p(f'{order["wonum"]}\n{text(order, "worktype").strip().upper() or "—"}', "body_center"),
                p(text(order, "location") or "Não informado"),
                p(text(order, "description")),
                p(f'{number(block["horas"])} h\n{number(block["horas"] * len(block["executantes"]))} HH', "body_center"),
                p(formatted_optional_day(text(order, "targcompdate")), "body_center"),
            ])
        total_row = [p(f'TOTAL DO DIA · {formatted_day(day)}', "label"), "", "", "", "",
                     p(f'{number(data["daily"][day])} HH', "body_center"), ""]
        rows.append(total_row)
        grid = table(rows, [35, 88, 61, 52, width - 35 - 88 - 61 - 52 - 43 - 55, 43, 55])
        # Short days stay visually grouped; lengthy days retain repeatable dates when paginated.
        if len(blocks) <= 8:
            grid.setStyle(TableStyle([("SPAN", (0, 1), (0, len(blocks)))]))
        accent = PALE if date.fromisoformat(day).weekday() % 2 == 0 else colors.HexColor("#FFF3B0")
        grid.setStyle(TableStyle([
            ("BACKGROUND", (0, 1), (0, len(blocks)), accent),
            ("SPAN", (0, -1), (4, -1)), ("SPAN", (5, -1), (6, -1)),
            ("BACKGROUND", (0, -1), (-1, -1), PALE),
            ("LINEABOVE", (0, -1), (-1, -1), .5, colors.HexColor("#B5CAE6")),
        ]))
        _, grid_height = grid.wrap(width, 10000)
        if grid_height <= 500:
            content.append(KeepTogether([grid, Spacer(1, 5)]))
        else:
            content.extend([grid, Spacer(1, 5)])
    if not by_day:
        content.extend([p("Nenhuma atividade alocada nesta revisão."), Spacer(1, 12)])
    content.extend([Spacer(1, 7), dashboard(data, width), Spacer(1, 6),
                    status_count_chart(data, width), Spacer(1, 4), pm_status_chart(data, width), Spacer(1, 8),
                    p("Tempo = duração do bloco. HH = duração × executantes simultâneos. "
                      "OTs distintas são contadas uma vez, mesmo quando divididas entre dias. "
                      "As categorias de situação indicam cobertura da alocação, não criticidade nem status de execução.", "small")])
    if doc["indisponibilidades"]:
        content.extend([PageBreak(), p("PREPARAÇÃO E PENDÊNCIAS DO PLANEJAMENTO", "title")])
    if doc["indisponibilidades"]:
        content.append(p("Indisponibilidades registradas", "title"))
        rows = [[p(h, "head") for h in ("Dia", "Integrante", "Motivo")]]
        for item in doc["indisponibilidades"]:
            rows.append([p(formatted_day(item["dia"])), p(people[item["executante"]]), p(item["motivo"])])
        content.append(table(rows, [75, 170, width - 245]))
    pdf.build(content, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
