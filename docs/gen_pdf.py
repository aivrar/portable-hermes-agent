"""Generate PDF manual from hermes-guide.md using fpdf2."""
from fpdf import FPDF
from pathlib import Path

md_path = Path(__file__).parent / "hermes-guide.md"
out_path = Path(__file__).parent / "Portable-Hermes-Agent-Manual.pdf"

text = md_path.read_text(encoding="utf-8")
# Sanitize unicode characters that latin-1 can't handle
text = text.replace("\u2014", "-").replace("\u2013", "-")
text = text.replace("\u2018", "'").replace("\u2019", "'")
text = text.replace("\u201c", '"').replace("\u201d", '"')
text = text.replace("\u2026", "...").replace("\u2022", "-")
text = text.replace("\u2248", "~").replace("\u2265", ">=").replace("\u2264", "<=")
# Replace double-dash (causes fpdf ligature width bug)
text = text.replace("--", "-")
# Strip any remaining non-latin1 chars
text = text.encode("latin-1", errors="replace").decode("latin-1")

pdf = FPDF()
pdf.set_margins(15, 15, 15)
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()
pdf.set_font("Helvetica", "B", 24)
pdf.cell(0, 15, "Hermes Agent", new_x="LMARGIN", new_y="NEXT", align="C")
pdf.set_font("Helvetica", "", 14)
pdf.cell(0, 10, "Complete User Guide", new_x="LMARGIN", new_y="NEXT", align="C")
pdf.cell(0, 8, "Version 0.4.0 - March 2026", new_x="LMARGIN", new_y="NEXT", align="C")
pdf.ln(10)

for line in text.split("\n"):
    s = line.strip()
    if not s:
        pdf.ln(3)
        continue
    # Strip markdown formatting
    clean = s.replace("**", "").replace("`", "")
    try:
        if s.startswith("# ") and not s.startswith("## "):
            pdf.set_font("Helvetica", "B", 18)
            pdf.ln(5)
            pdf.multi_cell(0, 8, s.lstrip("# "), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
        elif s.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.ln(4)
            pdf.multi_cell(0, 7, s.lstrip("# "), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif s.startswith("### "):
            pdf.set_font("Helvetica", "B", 12)
            pdf.ln(3)
            pdf.multi_cell(0, 6, s.lstrip("# "), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif s.startswith("#### "):
            pdf.set_font("Helvetica", "BI", 11)
            pdf.multi_cell(0, 6, s.lstrip("# "), new_x="LMARGIN", new_y="NEXT")
        elif s.startswith("---"):
            pdf.ln(2)
        elif s.startswith("| "):
            # Skip separator rows like |---|---|
            if s.replace("|", "").replace("-", "").replace(" ", "") == "":
                continue
            cells = [c.strip() for c in clean.split("|") if c.strip()]
            if not cells:
                continue
            pdf.set_font("Helvetica", "", 9)
            if len(cells) >= 2:
                label = cells[0]
                rest = ", ".join(cells[1:])
                row_text = f"  {label}: {rest}"
            else:
                row_text = "  " + cells[0]
            if len(row_text) > 110:
                row_text = row_text[:107] + "..."
            pdf.multi_cell(0, 5, row_text, new_x="LMARGIN", new_y="NEXT")
        elif s.startswith(("- ", "* ")):
            pdf.set_font("Helvetica", "", 10)
            bullet = s.lstrip("-* ").replace("**", "").replace("`", "")
            pdf.multi_cell(0, 5, "  - " + bullet, new_x="LMARGIN", new_y="NEXT")
        elif len(s) > 2 and s[0].isdigit() and ". " in s[:5]:
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, "  " + clean, new_x="LMARGIN", new_y="NEXT")
        elif s.startswith("```"):
            continue
        else:
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, clean, new_x="LMARGIN", new_y="NEXT")
    except Exception as e:
        import sys
        print(f"RENDER ERROR line: {s[:60]}... -> {e}", file=sys.stderr)

pdf.output(str(out_path))
print(f"PDF generated: {out_path} ({out_path.stat().st_size // 1024} KB)")
