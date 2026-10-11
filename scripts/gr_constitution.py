#!/usr/bin/env python3
"""Build syntagma/syntagma.md: the Constitution of Greece (Σύνταγμα της Ελλάδας, 1975) in the
full official text republished by order of the Speaker of Parliament in ΦΕΚ Α' 211/24.12.2019
(text as revised in 1986, 2001, 2008 and 2019)."""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gr_convert as g  # noqa: E402

URL = "https://ia37rg02wpsa01.blob.core.windows.net/fek/01/2019/20190100211.pdf"
PDF = os.path.join(g.RAW, "extra", "20190100211.pdf")


def main():
    if not os.path.exists(PDF):
        os.makedirs(os.path.dirname(PDF), exist_ok=True)
        subprocess.run(["curl", "-sf", "-A", "LawCodex/1.0 (+https://github.com/LawCodex)", "-o", PDF, URL],
                       check=True)
    pages, legacy = g.extract_lines(PDF)
    paras = g.build_paragraphs(pages)
    if ("\x00END", False) in paras:
        paras = paras[:paras.index(("\x00END", False))]
    start = next(i for i, (t, c) in enumerate(paras) if g.norm(t).lstrip("«").startswith("ΣΥΝΤΑΓΜΑ ΤΗΣ ΕΛΛΑΔΑΣ"))
    pstart = next((i for i, (t, c) in enumerate(paras[:start]) if g.norm(t).startswith("Ο ΠΡΟΕΔΡΟΣ ΤΗΣ ΒΟΥΛΗΣ")), 0)
    preamble = paras[pstart:start]
    seg = [(paras[start][0].lstrip("«"), True)] + paras[start + 1:]
    # the closing » and signature of the Speaker follow the last article
    _, body = g.to_markdown([("ΣΥΝΤΑΓΜΑ", True), ("", False)] + seg[1:], None, quotes=False,
                            any_case_titles=True)
    body = re.sub(r"^## (ΜΕΡΟΣ)", r"## \1", body, flags=re.M)
    pre = "\n\n".join(g.md_escape(t) for t, c in preamble)
    fm = """---
title: "Σύνταγμα της Ελλάδας"
identifier: "ΦΕΚ Α 211/24.12.2019"
type: constitution
jurisdiction: gr
language: el
date: 1975-06-09
last_amended: 2019-11-25
status: in_force
consolidated: true
source: "{url}"
retrieved: {today}
note: "Full official text as published by order of the Speaker of the Hellenic Parliament (ΦΕΚ Α' 211/24.12.2019), incorporating the revisions of 1986, 2001, 2008 and 2019."
---

# Σύνταγμα της Ελλάδας

""".format(url=URL, today=g.TODAY)
    out = os.path.join(g.OUT, "syntagma", "syntagma.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(fm + pre + "\n\n---\n\n" + body)
    print(out)


if __name__ == "__main__":
    main()
