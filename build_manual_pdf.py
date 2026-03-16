"""Build a styled PDF manual from docs/hermes-guide.md."""
import os
import re
from fpdf import FPDF

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
GUIDE_PATH = os.path.join(PROJECT_ROOT, "docs", "hermes-guide.md")
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "docs", "Portable-Hermes-Agent-Manual.pdf")


class ManualPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 10, "Portable Hermes Agent -- User Guide", align="C")
            self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def cover_page(self):
        self.add_page()
        self.ln(60)
        self.set_font("Helvetica", "B", 32)
        self.set_text_color(45, 45, 45)
        self.cell(0, 15, "Portable Hermes Agent", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(5)
        self.set_font("Helvetica", "", 16)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, "Complete User Guide", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(20)
        self.set_font("Helvetica", "", 11)
        self.set_text_color(80, 80, 80)
        lines = [
            "46+ tools | Desktop GUI | Local AI via LM Studio",
            "TTS, Music, and Image Generation Extensions",
            "Workflow Engine | Dynamic Tool Maker | Guided Mode",
            "",
            "No install. No Docker. No admin rights.",
            "",
            "Based on NousResearch/hermes-agent (MIT License)",
        ]
        for line in lines:
            self.cell(0, 7, line, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(30)
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(140, 140, 140)
        self.cell(0, 7, "github.com/rookiemann/portable-hermes-agent", align="C")

    def toc_page(self, sections):
        self.add_page()
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(45, 45, 45)
        self.cell(0, 12, "Table of Contents", new_x="LMARGIN", new_y="NEXT")
        self.ln(8)

        for i, (level, title) in enumerate(sections):
            if level == 1:
                self.set_font("Helvetica", "B", 11)
                self.set_text_color(45, 45, 45)
                indent = 0
            elif level == 2:
                self.set_font("Helvetica", "", 10)
                self.set_text_color(80, 80, 80)
                indent = 8
            else:
                self.set_font("Helvetica", "", 9)
                self.set_text_color(110, 110, 110)
                indent = 16

            self.set_x(15 + indent)
            # Truncate long titles
            display = title[:70] + "..." if len(title) > 70 else title
            self.cell(0, 6, display, new_x="LMARGIN", new_y="NEXT")


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
                # Flush table if active
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
            # Skip separator rows (|---|---|)
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
            i += 1
            continue
        if line.startswith("## "):
            elements.append(("h2", line[3:].strip()))
            i += 1
            continue
        if line.startswith("### "):
            elements.append(("h3", line[4:].strip()))
            i += 1
            continue
        if line.startswith("#### "):
            elements.append(("h4", line[5:].strip()))
            i += 1
            continue

        # Horizontal rule
        if line.strip() == "---":
            elements.append(("hr", ""))
            i += 1
            continue

        # Bullet points
        if re.match(r"^[-*] ", line.strip()):
            text = re.sub(r"^[-*] ", "", line.strip())
            elements.append(("bullet", text))
            i += 1
            continue

        # Numbered list
        m = re.match(r"^(\d+)\. (.+)", line.strip())
        if m:
            elements.append(("numbered", f"{m.group(1)}. {m.group(2)}"))
            i += 1
            continue

        # Regular text (skip empty lines)
        if line.strip():
            elements.append(("text", line.strip()))

        i += 1

    # Flush remaining
    if in_code and code_block:
        elements.append(("code", "\n".join(code_block)))
    if in_table and table_rows:
        elements.append(("table", table_rows))

    return elements


def clean_text(text):
    """Strip markdown formatting and non-latin1 chars for PDF."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
    text = re.sub(r"\*(.+?)\*", r"\1", text)  # italic
    text = re.sub(r"`(.+?)`", r"\1", text)  # inline code
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)  # links
    # Unicode replacements
    replacements = {
        "\u2014": " -- ", "\u2013": " - ", "\u2022": "-",
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2026": "...", "\u00a0": " ", "\u2192": "->", "\u2190": "<-",
        "\u2248": "~", "\u2265": ">=", "\u2264": "<=", "\u00d7": "x",
        "\u25cf": "*", "\u2715": "x", "\u2605": "*",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Strip any remaining non-latin1
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


def build_pdf():
    with open(GUIDE_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    elements = parse_markdown(content)
    pdf = ManualPDF()
    pdf.alias_nb_pages()

    # Cover page
    pdf.cover_page()

    # Collect TOC entries
    toc_entries = []
    for etype, edata in elements:
        if etype == "h2":
            toc_entries.append((1, clean_text(edata)))
        elif etype == "h3":
            toc_entries.append((2, clean_text(edata)))

    pdf.toc_page(toc_entries)

    # Content
    pdf.add_page()

    for etype, edata in elements:
        if etype == "h1":
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 22)
            pdf.set_text_color(45, 45, 45)
            pdf.cell(0, 12, clean_text(edata), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

        elif etype == "h2":
            pdf.ln(8)
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(50, 50, 50)
            pdf.cell(0, 10, clean_text(edata), new_x="LMARGIN", new_y="NEXT")
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(4)

        elif etype == "h3":
            pdf.ln(5)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(0, 8, clean_text(edata), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        elif etype == "h4":
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(70, 70, 70)
            pdf.cell(0, 7, clean_text(edata), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        elif etype == "text":
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(30, 30, 30)
            pdf.set_x(15)
            pdf.multi_cell(180, 5, clean_text(edata))
            pdf.ln(1)

        elif etype == "bullet":
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(30, 30, 30)
            pdf.set_x(20)
            pdf.multi_cell(170, 5, "  -  " + clean_text(edata))

        elif etype == "numbered":
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(30, 30, 30)
            pdf.set_x(20)
            pdf.multi_cell(170, 5, "  " + clean_text(edata))

        elif etype == "code":
            pdf.ln(2)
            pdf.set_fill_color(240, 240, 240)
            pdf.set_font("Courier", "", 8)
            pdf.set_text_color(40, 40, 40)
            for code_line in edata.split("\n"):
                cl = clean_text(code_line)
                if len(cl) > 95:
                    cl = cl[:92] + "..."
                pdf.set_x(18)
                pdf.cell(174, 4, "  " + cl, fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        elif etype == "table":
            rows = edata
            if not rows:
                continue
            pdf.ln(2)
            num_cols = len(rows[0])
            col_width = 175 / num_cols

            # Header row
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(220, 220, 220)
            pdf.set_text_color(30, 30, 30)
            pdf.set_x(18)
            for cell in rows[0]:
                pdf.cell(col_width, 6, clean_text(cell)[:30], border=1,
                        fill=True)
            pdf.ln()

            # Data rows
            pdf.set_font("Helvetica", "", 8)
            pdf.set_fill_color(250, 250, 250)
            for row in rows[1:]:
                pdf.set_x(18)
                for j, cell in enumerate(row):
                    text = clean_text(cell)
                    if len(text) > 35:
                        text = text[:32] + "..."
                    pdf.cell(col_width, 5, text, border=1)
                pdf.ln()
            pdf.ln(2)

        elif etype == "hr":
            pdf.ln(3)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(15, pdf.get_y(), 195, pdf.get_y())
            pdf.ln(3)

    pdf.output(OUTPUT_PATH)
    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"PDF created: {OUTPUT_PATH}")
    print(f"Pages: {pdf.page_no()}, Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    build_pdf()
