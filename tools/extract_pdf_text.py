# -*- coding: utf-8 -*-
"""批量提取目录下所有 PDF 的文本，用于知识库提炼。

用法: python tools/extract_pdf_text.py <目录>
输出: <目录>/_extracted/<原文件名>.txt（每页之间以 --- Page N --- 分隔）
"""
import sys
from pathlib import Path

import fitz  # pymupdf


def extract(pdf_path: Path, out_path: Path) -> int:
    doc = fitz.open(pdf_path)
    parts = []
    for i, page in enumerate(doc, 1):
        text = page.get_text("text").strip()
        if text:
            parts.append(f"--- Page {i} ---\n{text}")
    doc.close()
    content = "\n\n".join(parts)
    out_path.write_text(content, encoding="utf-8")
    return len(content)


def main():
    src = Path(sys.argv[1]).resolve()
    out_dir = src / "_extracted"
    out_dir.mkdir(exist_ok=True)
    for pdf in sorted(src.glob("*.pdf")):
        out = out_dir / (pdf.stem + ".txt")
        try:
            n = extract(pdf, out)
            print(f"{n:>8} chars  {pdf.name}")
        except Exception as e:
            print(f"    FAIL  {pdf.name}: {e}")


if __name__ == "__main__":
    main()
