"""Build a styled PDF manual from docs/hermes-guide.md."""
import os
import re
from fpdf import FPDF
from fpdf.enums import TableCellFillMode

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GUIDE_PATH = os.path.join(PROJECT_ROOT, "docs", "hermes-guide.md")
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "docs", "Portable-Hermes-Agent-Manual.pdf")

LEFT_MARGIN = 15
RIGHT_MARGIN = 15
PAGE_WIDTH = 210  # A4 mm


class ManualPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=25)
        self.set_left_margin(LEFT_MARGIN)
        self.set_right_margin(RIGHT_MARGIN)

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(130, 130, 130)
            self.cell(0, 6, "Portable Hermes Agent -- User Guide", align="C")
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def cover_page(self):
        self.add_page()
        self.ln(55)
        self.set_font("Helvetica", "B", 30)
        self.set_text_color(40, 40, 40)
        self.cell(0, 14, "Portable Hermes Agent", align="C",
                  new_x="LMARGIN", new_y="NEXT")
        self.ln(4)
        self.set_font("Helvetica", "", 15)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, "Complete User Guide", align="C",
                  new_x="LMARGIN", new_y="NEXT")
        self.ln(18)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(80, 80, 80)
        for line in [
            "46+ tools  |  Desktop GUI  |  Local AI via LM Studio",
            "TTS, Music, and Image Generation Extensions",
            "Workflow Engine  |  Dynamic Tool Maker  |  Guided Mode",
            "",
            "No install. No Docker. No admin rights.",
            "",
            "Based on NousResearch/hermes-agent (MIT License)",
        ]:
            self.cell(0, 6, line, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(25)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, "github.com/aivrar/portable-hermes-agent",
                  align="C")

    def toc_page(self, sections):
        self.add_page()
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(40, 40, 40)
        self.cell(0, 10, "Table of Contents", new_x="LMARGIN", new_y="NEXT")
        self.ln(6)

        for level, title in sections:
            if level == 1:
                self.set_font("Helvetica", "B", 10)
                self.set_text_color(40, 40, 40)
                indent = 0
                self.ln(2)
            elif level == 2:
                self.set_font("Helvetica", "", 9)
                self.set_text_color(80, 80, 80)
                indent = 6
            else:
                self.set_font("Helvetica", "", 9)
                self.set_text_color(110, 110, 110)
                indent = 12

            self.set_x(LEFT_MARGIN + indent)
            display = title[:75] + "..." if len(title) > 75 else title
            self.cell(0, 5.5, display, new_x="LMARGIN", new_y="NEXT")


def parse_markdown(text):
    """Parse markdown into structured elements."""
    elements = []
    lines = text.split("\n")
    i = 0
    in_code = False
    code_block = []
    in_table = False
    table_rows = []

    while i < len(lines):
        line = lines[i]

        # Code blocks
        if line.strip().startswith("```"):
            if in_code:
                elements.append(("code", "\n".join(code_block)))
                code_block = []
                in_code = False
            else:
                if in_table:
                    elements.append(("table", table_rows))
                    table_rows = []
                    in_table = False
                in_code = True
            i += 1
            continue

        if in_code:
            code_block.append(line)
            i += 1
            continue

        # Tables
        if "|" in line and line.strip().startswith("|"):
            stripped = line.strip()
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                i += 1
                continue
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if cells:
                if not in_table:
                    in_table = True
                table_rows.append(cells)
            i += 1
            continue
        elif in_table:
            elements.append(("table", table_rows))
            table_rows = []
            in_table = False

        # Headers
        if line.startswith("# ") and not line.startswith("##"):
            elements.append(("h1", line[2:].strip()))
        elif line.startswith("## "):
            elements.append(("h2", line[3:].strip()))
        elif line.startswith("### "):
            elements.append(("h3", line[4:].strip()))
        elif line.startswith("#### "):
            elements.append(("h4", line[5:].strip()))
        elif line.strip() == "---":
            elements.append(("hr", ""))
        elif re.match(r"^[-*] ", line.strip()):
            elements.append(("bullet", re.sub(r"^[-*] ", "", line.strip())))
        elif re.match(r"^\d+\. ", line.strip()):
            elements.append(("numbered", line.strip()))
        elif line.strip():
            elements.append(("text", line.strip()))

        i += 1

    if in_code and code_block:
        elements.append(("code", "\n".join(code_block)))
    if in_table and table_rows:
        elements.append(("table", table_rows))

    return elements


def clean_text(text):
    """Strip markdown formatting and non-latin1 chars for PDF."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    replacements = {
        "\u2014": "--", "\u2013": "-", "\u2022": "-",
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2026": "...", "\u00a0": " ", "\u2192": "->", "\u2190": "<-",
        "\u2248": "~", "\u2265": ">=", "\u2264": "<=", "\u00d7": "x",
        "\u25cf": "*", "\u2715": "x", "\u2605": "*",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


def build_pdf():
    with open(GUIDE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    elements = parse_markdown(content)
    pdf = ManualPDF()
    pdf.alias_nb_pages()
    usable_width = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

    # Cover page
    pdf.cover_page()

    # TOC
    toc_entries = []
    for etype, edata in elements:
        if etype == "h2":
            toc_entries.append((1, clean_text(edata)))
        elif etype == "h3":
            toc_entries.append((2, clean_text(edata)))
    pdf.toc_page(toc_entries)

    # Content pages
    pdf.add_page()

    for etype, edata in elements:
        if etype == "h1":
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 20)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(usable_width, 10, clean_text(edata))
            pdf.ln(2)

        elif etype == "h2":
            # Check if there's enough room, otherwise new page
            if pdf.get_y() > 250:
                pdf.add_page()
            else:
                pdf.ln(6)
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(45, 45, 45)
            pdf.multi_cell(usable_width, 8, clean_text(edata))
            pdf.set_draw_color(180, 180, 180)
            pdf.line(LEFT_MARGIN, pdf.get_y(), PAGE_WIDTH - RIGHT_MARGIN,
                     pdf.get_y())
            pdf.ln(3)

        elif etype == "h3":
            if pdf.get_y() > 260:
                pdf.add_page()
            else:
                pdf.ln(4)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(55, 55, 55)
            pdf.multi_cell(usable_width, 7, clean_text(edata))
            pdf.ln(2)

        elif etype == "h4":
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(65, 65, 65)
            pdf.multi_cell(usable_width, 6, clean_text(edata))
            pdf.ln(1)

        elif etype == "text":
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(usable_width, 5, clean_text(edata))
            pdf.ln(1.5)

        elif etype == "bullet":
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(30, 30, 30)
            x = pdf.get_x()
            pdf.set_x(LEFT_MARGIN + 5)
            pdf.multi_cell(usable_width - 5, 5,
                           "  -  " + clean_text(edata))
            pdf.ln(0.5)

        elif etype == "numbered":
            pdf.set_font("Helvetica", "", 9.5)
            pdf.set_text_color(30, 30, 30)
            pdf.set_x(LEFT_MARGIN + 5)
            pdf.multi_cell(usable_width - 5, 5,
                           "  " + clean_text(edata))
            pdf.ln(0.5)

        elif etype == "code":
            pdf.ln(1)
            pdf.set_fill_color(242, 242, 242)
            pdf.set_draw_color(210, 210, 210)
            pdf.set_font("Courier", "", 7.5)
            pdf.set_text_color(40, 40, 40)
            for code_line in edata.split("\n"):
                cl = clean_text(code_line)
                if len(cl) > 100:
                    cl = cl[:97] + "..."
                pdf.set_x(LEFT_MARGIN + 2)
                pdf.cell(usable_width - 4, 4, "  " + cl, fill=True,
                         new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        elif etype == "table":
            rows = edata
            if not rows:
                continue
            pdf.ln(2)
            num_cols = len(rows[0])

            # Normalize all rows to same column count
            for ri in range(len(rows)):
                while len(rows[ri]) < num_cols:
                    rows[ri].append("")

            # Use fpdf2 built-in table
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(30, 30, 30)

            # Calculate proportional column widths
            col_max = [0] * num_cols
            for row in rows:
                for j in range(num_cols):
                    col_max[j] = max(col_max[j],
                                     len(clean_text(row[j])))
            total = max(sum(col_max), 1)
            col_widths = tuple(
                max(15, usable_width * (col_max[j] / total))
                for j in range(num_cols)
            )
            # Scale to fit
            scale = usable_width / sum(col_widths)
            col_widths = tuple(w * scale for w in col_widths)

            with pdf.table(
                col_widths=col_widths,
                text_align="LEFT",
                cell_fill_color=(248, 248, 248),
                cell_fill_mode=TableCellFillMode.EVEN_ROWS,
                line_height=pdf.font_size * 2.2,
                first_row_as_headings=True,
                borders_layout="SINGLE_TOP_LINE",
                padding=1.5,
            ) as table:
                for ri, row in enumerate(rows):
                    data_row = table.row()
                    for j in range(num_cols):
                        text = clean_text(row[j]) if j < len(row) else ""
                        if ri == 0:
                            pdf.set_font("Helvetica", "B", 8)
                        else:
                            pdf.set_font("Helvetica", "", 8)
                        data_row.cell(text)

            pdf.ln(2)

        elif etype == "hr":
            pdf.ln(2)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(LEFT_MARGIN, pdf.get_y(),
                     PAGE_WIDTH - RIGHT_MARGIN, pdf.get_y())
            pdf.ln(2)

    pdf.output(OUTPUT_PATH)
    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"PDF created: {OUTPUT_PATH}")
    print(f"Pages: {pdf.page_no()}, Size: {size_kb:.0f} KB")


if __name__ == "__main__":
    build_pdf()
