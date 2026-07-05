"""
md → PDF 转换器（Chrome headless 打印）
用法：python md2pdf.py input.md output.pdf
"""
import sys
import sys as _sys
from pathlib import Path

try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import markdown
import subprocess

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
@page { size: A4; margin: 18mm 15mm; }
body { font-family: "Microsoft YaHei", "PingFang SC", "SimHei", sans-serif;
       font-size: 11pt; line-height: 1.6; color: #222; }
h1 { font-size: 22pt; color: #1a1a1a; border-bottom: 3px solid #1a1a1a;
     padding-bottom: 8px; margin-top: 24pt; }
h2 { font-size: 16pt; color: #c0392b; border-bottom: 1px solid #ddd;
     padding-bottom: 4px; margin-top: 20pt; }
h3 { font-size: 13pt; color: #2c3e50; margin-top: 16pt; }
h4 { font-size: 11pt; color: #555; margin-top: 12pt; }
p { margin: 6pt 0; }
strong { color: #c0392b; }
em { color: #666; }
code { font-family: Consolas, "Courier New", monospace;
       background: #f5f5f5; padding: 2px 5px; border-radius: 3px;
       font-size: 9.5pt; color: #c7254e; }
pre { background: #f5f5f5; padding: 10px; border-radius: 4px;
      overflow-x: auto; font-size: 9.5pt; line-height: 1.45; }
pre code { background: transparent; color: #333; padding: 0; }
blockquote { border-left: 4px solid #c0392b; padding: 4px 12px;
             color: #666; background: #fafafa; margin: 6pt 0; }
table { border-collapse: collapse; width: 100%; margin: 10pt 0; font-size: 10pt; }
th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
th { background: #f0f0f0; font-weight: bold; }
tr:nth-child(even) { background: #fafafa; }
ul, ol { margin: 6pt 0; padding-left: 24pt; }
li { margin: 3pt 0; }
hr { border: none; border-top: 1px solid #ddd; margin: 18pt 0; }
a { color: #c0392b; text-decoration: none; }
"""


def md_to_html(md_path):
    text = Path(md_path).read_text(encoding="utf-8")
    html_body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>{CSS}</style>
</head>
<body>
{html_body}
</body>
</html>"""


def html_to_pdf(html_content, pdf_path):
    """直接接受 HTML 字符串，写到英文临时路径再让 Chrome 打印"""
    import os, shutil
    tmp_dir = os.environ.get("TEMP", r"C:\Users\86150\AppData\Local\Temp")
    tmp_html = os.path.join(tmp_dir, "md2pdf_input.html")
    tmp_pdf = os.path.join(tmp_dir, "md2pdf_output.pdf")

    Path(tmp_html).write_text(html_content, encoding="utf-8")

    html_url = "file:///" + tmp_html.replace("\\", "/")
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--no-margins",
        "--no-sandbox",
        f"--print-to-pdf={tmp_pdf}",
        html_url,
    ]
    subprocess.run(cmd, capture_output=True, timeout=60)
    if Path(tmp_pdf).exists() and Path(tmp_pdf).stat().st_size > 2000:
        shutil.move(str(tmp_pdf), str(pdf_path))
        return True
    return False


def main():
    if len(sys.argv) < 3:
        print("用法: python md2pdf.py input.md output.pdf")
        sys.exit(1)
    md_in = sys.argv[1]
    pdf_out = sys.argv[2]

    print(f"[md2pdf] {md_in} -> HTML")
    html = md_to_html(md_in)

    print(f"[md2pdf] HTML -> PDF ({pdf_out})")
    ok = html_to_pdf(html, pdf_out)
    if ok and Path(pdf_out).exists():
        size_kb = Path(pdf_out).stat().st_size // 1024
        print(f"[md2pdf] 完成: {pdf_out} ({size_kb} KB)")
    else:
        print("[md2pdf] 失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
