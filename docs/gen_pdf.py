"""Generate styled HTML manual from hermes-guide.md, then convert to PDF."""
import markdown
from pathlib import Path

md_path = Path(__file__).parent / "hermes-guide.md"
html_path = Path(__file__).parent / "Portable-Hermes-Agent-Manual.html"

md_text = md_path.read_text(encoding="utf-8")

# Convert markdown to HTML with table support
html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

# Wrap in styled HTML document
html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Hermes Agent - Complete User Guide</title>
<style>
  @media print {{
    body {{ font-size: 11pt; }}
    h1 {{ page-break-before: always; }}
    h1:first-of-type {{ page-break-before: avoid; }}
    table {{ page-break-inside: avoid; }}
  }}

  body {{
    font-family: 'Segoe UI', Calibri, Arial, sans-serif;
    max-width: 800px;
    margin: 40px auto;
    padding: 0 30px;
    color: #1a1a1a;
    line-height: 1.6;
    font-size: 14px;
  }}

  h1 {{
    color: #1a5276;
    border-bottom: 3px solid #2980b9;
    padding-bottom: 8px;
    margin-top: 40px;
    font-size: 28px;
  }}

  h2 {{
    color: #2471a3;
    border-bottom: 1px solid #aed6f1;
    padding-bottom: 5px;
    margin-top: 35px;
    font-size: 22px;
  }}

  h3 {{
    color: #2e86c1;
    margin-top: 25px;
    font-size: 17px;
  }}

  h4 {{
    color: #5499c7;
    margin-top: 18px;
    font-size: 15px;
  }}

  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
    font-size: 13px;
  }}

  th {{
    background: #2c3e50;
    color: white;
    padding: 10px 12px;
    text-align: left;
    font-weight: 600;
  }}

  td {{
    padding: 8px 12px;
    border-bottom: 1px solid #d5dbdb;
  }}

  tr:nth-child(even) {{
    background: #f4f6f7;
  }}

  tr:hover {{
    background: #eaf2f8;
  }}

  code {{
    background: #f0f3f4;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 13px;
    color: #c0392b;
  }}

  pre {{
    background: #2c3e50;
    color: #ecf0f1;
    padding: 14px 18px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 13px;
  }}

  pre code {{
    background: none;
    color: inherit;
    padding: 0;
  }}

  blockquote {{
    border-left: 4px solid #2980b9;
    margin: 12px 0;
    padding: 8px 16px;
    background: #eaf2f8;
    color: #2c3e50;
  }}

  ul, ol {{
    padding-left: 24px;
  }}

  li {{
    margin: 4px 0;
  }}

  hr {{
    border: none;
    border-top: 2px solid #d5dbdb;
    margin: 30px 0;
  }}

  strong {{
    color: #1a5276;
  }}

  a {{
    color: #2980b9;
    text-decoration: none;
  }}

  a:hover {{
    text-decoration: underline;
  }}

  /* Title page styling */
  h1:first-of-type {{
    text-align: center;
    font-size: 36px;
    border-bottom: none;
    margin-top: 80px;
    margin-bottom: 5px;
  }}
</style>
</head>
<body>

<div style="text-align:center; margin-bottom: 60px;">
  <p style="font-size: 18px; color: #5d6d7e;">Complete User Guide</p>
  <p style="font-size: 14px; color: #95a5a6;">Version 0.4.0 &mdash; March 2026</p>
</div>

{html_body}

</body>
</html>"""

html_path.write_text(html, encoding="utf-8")
print(f"HTML generated: {html_path} ({html_path.stat().st_size // 1024} KB)")

# Try to convert to PDF via wkhtmltopdf or Chrome
pdf_path = Path(__file__).parent / "Portable-Hermes-Agent-Manual.pdf"
converted = False

# Try wkhtmltopdf
try:
    import pdfkit
    pdfkit.from_file(str(html_path), str(pdf_path), options={
        "page-size": "Letter",
        "margin-top": "15mm",
        "margin-bottom": "15mm",
        "margin-left": "15mm",
        "margin-right": "15mm",
        "encoding": "UTF-8",
        "enable-local-file-access": "",
    })
    converted = True
    print(f"PDF generated via wkhtmltopdf: {pdf_path} ({pdf_path.stat().st_size // 1024} KB)")
except Exception as e:
    print(f"wkhtmltopdf not available: {e}")

if not converted:
    print(f"\nOpen the HTML file in your browser and print to PDF:")
    print(f"  {html_path}")
