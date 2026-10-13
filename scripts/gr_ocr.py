#!/usr/bin/env python3
"""OCR a few major pre-2000 codes whose ΦΕΚ Α' PDFs are image-only scans (no text layer) and
write them to kodikes/ with `ocr: true` in the front matter.

Requires tesseract with the Greek model (ell.traineddata from tesseract-ocr/tessdata_best);
pass its directory with GR_TESSDATA (default: _raw/gr/tessdata).
OCR output is unreviewed machine text: expect recognition errors (including in article
numbers). The originals are linked in `source`.
"""
import os
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gr_convert as g  # noqa: E402

TESS = os.environ.get("GR_TESSDATA", os.path.join(g.RAW, "tessdata"))
WORK = os.path.join(g.RAW, "ocr")
UA = "LawCodex/1.0 (+https://github.com/LawCodex)"

# (fek file name, act label, slug, title, date)
CODES = [
    ("19840100164", "π.δ. 456/1984", "astikos-kodikas", "Αστικός Κώδικας και Εισαγωγικός του Νόμος", "1984-10-24"),
    ("19850100182", "π.δ. 503/1985", "kodikas-politikis-dikonomias", "Κώδικας Πολιτικής Δικονομίας και Εισαγωγικός του Νόμος", "1985-10-24"),
    ("19990100045", "ν. 2690/1999", "kodikas-dioikitikis-diadikasias", "Κώδικας Διοικητικής Διαδικασίας", "1999-03-09"),
    ("19990100097", "ν. 2717/1999", "kodikas-dioikitikis-dikonomias", "Κώδικας Διοικητικής Δικονομίας", "1999-05-17"),
    ("19990100291", "ν. 2776/1999", "sofronistikos-kodikas", "Σωφρονιστικός Κώδικας", "1999-12-24"),
    ("19990100057", "ν. 2696/1999", "kodikas-odikis-kykloforias-1999", "Κώδικας Οδικής Κυκλοφορίας (1999)", "1999-03-23"),
]


def monotonic(s):
    """Map polytonic artefacts of the OCR model to monotonic Greek; micro sign -> mu."""
    s = s.replace("µ", "μ")
    out = []
    for ch in s:
        if "ἀ" <= ch <= "῿" or ch in "ΆΈΉΊΌΎΏ":
            d = unicodedata.normalize("NFD", ch)
            base = d[0]
            accented = any(c in d for c in "́̀͂")
            ch = unicodedata.normalize("NFC", base + ("́" if accented else ""))
        out.append(ch)
    s = "".join(out)
    s = re.sub(r"[᾿᾽῾΄´`´’']\s?([ΑΆ])(ρθρ)", r"Ά\2", s)
    s = re.sub(r"^[᾿᾽῾΄´`´]", "", s)
    return s


def ocr_page(args):
    pdf, page, outdir = args
    txt = os.path.join(outdir, f"p{page:04d}.txt")
    if os.path.exists(txt):
        return
    base = os.path.join(outdir, f"p{page:04d}")
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "300", "-gray", "-singlefile", pdf, base],
                   check=True)
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    subprocess.run(["tesseract", base + ".pgm", base, "-l", "ell", "--tessdata-dir", TESS],
                   check=True, capture_output=True, env=env)
    os.remove(base + ".pgm")


DROP = re.compile(r"^(ΕΦΗΜΕΡΙ[ΣΔ]Α? ΤΗΣ ΚΥΒΕΡΝΗΣΕΩΣ.*|\(?ΤΕΥΧΟΣ ΠΡΩΤΟ\)?|\d{1,5}|ΑΡΙΘΜΟΣ ΦΥΛΛΟΥ.*|.{0,3})$")


OCR_ART = re.compile(r"^[^0-9A-Za-zΑ-Ωα-ωΆ-ώ]*[ΆΑ]{0,2}\s?ρθρ[οα]\s+([0-9A-Za-zΑ-Ωα-ωΆ-ώ]{1,5})\s*[^0-9A-Za-zΑ-Ωα-ωΆ-ώ]*$")
LOOK_DIGITS = str.maketrans("ΙΊIlΟOΖΒS", "111100285")


def clean_label(lbl):
    d = lbl.translate(LOOK_DIGITS)
    digits = re.sub(r"[^0-9]", "", d)
    if digits and len(d) - len(digits) <= 1:
        return digits
    if re.fullmatch(r"[0-9ΙΟΖΒIOlS]+", lbl):
        return d
    return lbl


def fix_article_numbers(paras):
    """Repair OCR misreadings of article numbers. Headings whose number is consistent with a
    neighbour (n-1 before or n+1 after) are anchors; headings between two anchors are
    renumbered by interpolation when the number of headings between them matches the gap
    (e.g. 'Άρθρο 961' between anchors 360 and 362 becomes 'Άρθρο 361')."""
    idx = [i for i, (t, c) in enumerate(paras) if re.match(r"^Άρθρο \S+$", t)]
    labels = [paras[i][0].split(" ", 1)[1] for i in idx]

    def val(lbl):
        d = lbl.translate(LOOK_DIGITS)
        if d.isdigit():
            return int(d)
        digits = re.sub(r"[^0-9]", "", d)
        if digits and len(d) - len(digits) <= 1:
            return int(digits)
        return None
    vals = [val(x) for x in labels]
    n = len(vals)
    for _ in range(3):
        anchor = [v is not None and ((j > 0 and vals[j - 1] == v - 1) or (j + 1 < n and vals[j + 1] == v + 1))
                  for j, v in enumerate(vals)]
        anchors = [j for j in range(n) if anchor[j]]
        for a1, a2 in zip(anchors, anchors[1:]):
            if a2 - a1 > 1 and vals[a2] - vals[a1] == a2 - a1:
                for j in range(a1 + 1, a2):
                    vals[j] = vals[a1] + (j - a1)
        for j in range(n):
            if anchor[j]:
                continue
            prv = vals[j - 1] if j > 0 else None
            nxt = vals[j + 1] if j + 1 < n else None
            cur = vals[j]
            bad = cur is None or (prv is not None and cur <= prv) or (nxt is not None and cur >= nxt)
            if not bad:
                continue
            if prv is not None and nxt is not None and nxt - prv == 2:
                vals[j] = prv + 1                      # single misread between two good numbers
            elif nxt is not None and j + 1 < n and anchor[j + 1] and nxt > 1 and (prv is None or prv < nxt - 1):
                vals[j] = nxt - 1                      # first heading of a run
            elif prv is not None and j > 0 and anchor[j - 1] and (nxt is None or nxt > prv + 1):
                vals[j] = prv + 1                      # last heading of a run
    fixed = 0
    for j in range(n):
        if vals[j] is not None and str(vals[j]) != labels[j]:
            paras[idx[j]] = (f"Άρθρο {vals[j]}", paras[idx[j]][1])
            fixed += 1
    return fixed


def paragraphs(outdir, npages):
    paras = []
    for p in range(1, npages + 1):
        t = open(os.path.join(outdir, f"p{p:04d}.txt"), encoding="utf-8").read()
        for block in re.split(r"\n\s*\n", t):
            lines = [monotonic(x.strip()) for x in block.split("\n") if x.strip()]
            lines = [x for x in lines if not DROP.match(g.norm(x))]
            lines = [("Άρθρο " + clean_label(OCR_ART.match(x).group(1))) if OCR_ART.match(x) else x for x in lines]
            lines = [re.sub(r"(\w)-{2,}$", r"\1-", x) for x in lines]
            if not lines:
                continue
            cur = []
            for ln in lines:
                is_art = bool(re.match(r"^Άρθρο \S{1,5}$", ln)) or bool(g.ART_LOOSE.match(ln))
                # article headings and numbered paragraphs start new paragraphs
                if cur and (is_art or (g.STRUCT_RE.match(g.norm(ln)) and g.is_upper_text(ln)) or re.match(r"^\d{1,2}\.\s", ln) and cur[-1].endswith((".", ":"))):
                    paras.append((g.join_lines(cur), False))
                    cur = []
                cur.append(ln)
                if is_art and len(ln) < 30:
                    paras.append((g.join_lines(cur), False))
                    cur = []
            if cur:
                paras.append((g.join_lines(cur), False))
    # strip trailing period of article headings ("Άρθρο 354.")
    paras = [(re.sub(r"^((?:Άρθρο|Άρθρα)\s+\S+?)\.$", r"\1", t), c) for t, c in paras]
    fixed = fix_article_numbers(paras)
    print("article numbers corrected:", fixed, flush=True)
    return paras


def main():
    only = sys.argv[1:] or None
    out_dir = os.path.join(g.OUT, "kodikes")
    os.makedirs(out_dir, exist_ok=True)
    for fek, act, slug, title, date in CODES:
        if only and slug not in only:
            continue
        year = fek[:4]
        url = f"{g.BLOB}/01/{year}/{fek}.pdf"
        pdf = os.path.join(WORK, fek + ".pdf")
        os.makedirs(WORK, exist_ok=True)
        n = None
        for attempt in range(4):
            if not os.path.exists(pdf):
                subprocess.run(["curl", "-sf", "--retry", "3", "-A", UA, "-o", pdf, url], check=True)
            m = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True,
                                                             text=True).stdout)
            if m:
                n = int(m.group(1))
                break
            os.remove(pdf)   # truncated download: retry
        if n is None:
            print("cannot download", url)
            continue
        outdir = os.path.join(WORK, fek)
        os.makedirs(outdir, exist_ok=True)
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(ocr_page, [(pdf, p, outdir) for p in range(1, n + 1)]))
        paras = paragraphs(outdir, n)
        _, body = g.to_markdown([("", True), ("", False)] + paras, None, quotes=False)
        fm = [
            "---",
            f"title: {g.yaml_str(title)}",
            f"identifier: {g.yaml_str(act)}",
            "type: code",
            "jurisdiction: gr",
            "language: el",
            f"date: {date}",
            f"gazette: \"ΦΕΚ Α {int(fek[6:])}/{year}\"",
            "status: unknown",
            "consolidated: false",
            "ocr: true",
            f"enacted_by: {g.yaml_str(act)}",
            f"source: \"{url}\"",
            f"retrieved: {g.TODAY}",
            "note: \"Machine OCR (tesseract, Greek model) of the image-only ΦΕΚ scan; unreviewed, contains recognition errors; article numbers misread by OCR were corrected from the running sequence. Original text as published; later amendments are not incorporated.\"",
            "---",
        ]
        md = "\n".join(fm) + f"\n\n# {title}\n\n*{act} (ΦΕΚ Α {int(fek[6:])}/{year}) — OCR text*\n\n" + body
        with open(os.path.join(out_dir, slug + ".md"), "w", encoding="utf-8") as f:
            f.write(md)
        print(slug, n, "pages", len(body), "chars", flush=True)


if __name__ == "__main__":
    main()
