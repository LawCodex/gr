#!/usr/bin/env python3
"""Convert ΦΕΚ Α' PDFs (downloaded by gr_fetch.py) to LawCodex Markdown.

For every entry of the search.et.gr legislation index (laws, presidential decrees, acts of
legislative content) whose ΦΕΚ issue PDF has a text layer, the text is extracted with
`pdftotext -bbox-layout` (poppler), page furniture (running headers, page numbers, digital
signature box, barcode, National Printing Office back-page notice) is removed, lines are
re-flowed into paragraphs using the geometry of the justified two-column layout, the act is
cut out of the issue (an issue can contain several acts) and headings are rebuilt for
Μέρος / Τίτλος / Κεφάλαιο / Τμήμα / Άρθρο.

Old ΦΕΚ (c. 1996-2006) use legacy 8-bit Greek fonts whose glyph codes are Windows-1253; they
are transcoded transparently.

Usage: python gr_convert.py [--types 1,2,3] [--from-year 1996] [--to-year 2100] [--only NAME]
"""
import argparse
import collections
import datetime
import html
import json
import os
import re
import statistics
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

from lxml import etree

RAW = os.environ.get("GR_RAW", "/Users/magicaltux/projects/lawcodex/_raw/gr")
OUT = os.environ.get("GR_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BLOB = "https://ia37rg02wpsa01.blob.core.windows.net/fek"
TODAY = datetime.date.today().isoformat()
TRACE = bool(os.environ.get("GR_TRACE"))

TYPES = {
    "1": dict(dir="nomoi", prefix="n", kind="act", label="Νόμος", short="ν.",
              head=r"ΝΟΜΟΣ"),
    "2": dict(dir="pd", prefix="pd", kind="decree", label="Προεδρικό Διάταγμα", short="π.δ.",
              head=r"ΠΡΟΕΔΡΙΚΟ\s*ΔΙΑΤΑΓΜΑ"),
    "3": dict(dir="pnp", prefix="pnp", kind="act", label="Πράξη Νομοθετικού Περιεχομένου",
              short="Π.Ν.Π.", head=r"ΠΡΑΞΗ\s*ΝΟΜΟΘΕΤΙΚΟΥ\s*ΠΕΡΙΕΧΟΜΕΝΟΥ"),
}

# Latin look-alikes -> Greek capitals (used only for matching, never for output)
LOOK = str.maketrans("ABEHIKMNOPTXYZ∆Ω", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖΔΩ")
# glyph-mapping artefacts that are safe to fix in the output
FIX = str.maketrans({"∆": "Δ", "Ω": "Ω", "­": "", "﻿": ""})

ACT_HEAD = re.compile(
    r"^(?:ΝΟΜΟΣ|ΠΡΟΕΔΡΙΚΟ\s*ΔΙΑΤΑΓΜΑ|ΠΡΑΞΗ\s*ΝΟΜΟΘΕΤΙΚΟΥ\s*ΠΕΡΙΕΧΟΜΕΝΟΥ|ΑΠΟΦΑΣΕΙΣ|ΑΠΟΦΑΣΗ|"
    r"ΔΙΟΡΘΩΣΕΙΣ\s*ΣΦΑΛΜΑΤΩΝ|ΔΙΟΡΘΩΣΗ\s*ΣΦΑΛΜΑΤΟΣ|ΨΗΦΙΣΜΑ|ΔΙΑΤΑΓΜΑ|ΚΑΝΟΝΙΣΜΟΣ|ΑΝΑΚΟΙΝΩΣΗ|"
    r"ΠΡΑΞΗ\s*ΥΠΟΥΡΓΙΚΟΥ\s*ΣΥΜΒΟΥΛΙΟΥ|ΠΡΑΞΕΙΣ\s*ΥΠΟΥΡΓΙΚΟΥ\s*ΣΥΜΒΟΥΛΙΟΥ|ΔΙΕΘΝΕΙΣ\s*ΣΥΜΒΑΣΕΙΣ|"
    r"ΠΡΟΕΔΡΙΚΑ\s*ΔΙΑΤΑΓΜΑΤΑ|ΝΟΜΟΙ)\b(.*)$")
NUM_RE = re.compile(r"ΑΡΙΘ[^\d]{0,6}(\d+)")
STRUCT = [("ΠΑΡΑΡΤΗΜΑ", 1), ("ΒΙΒΛΙΟ", 1), ("ΜΕΡΟΣ", 2), ("ΤΙΤΛΟΣ", 3), ("ΚΕΦΑΛΑΙΟ", 4), ("ΤΜΗΜΑ", 5),
          ("ΥΠΟΚΕΦΑΛΑΙΟ", 5), ("ΕΝΟΤΗΤΑ", 6)]
STRUCT_RE = re.compile(r"^(ΠΑΡΑΡΤΗΜΑ|ΒΙΒΛΙΟ|ΜΕΡΟΣ|ΤΙΤΛΟΣ|ΚΕΦΑΛΑΙΟ|ΥΠΟΚΕΦΑΛΑΙΟ|ΤΜΗΜΑ|ΕΝΟΤΗΤΑ)\s+"
                       r"([Α-ΩA-Z0-9]{1,6}[΄'’`]?|ΠΡΩΤΟ|ΔΕΥΤΕΡΟ|ΤΡΙΤΟ|ΤΕΤΑΡΤΟ|ΠΕΜΠΤΟ|ΕΚΤΟ|ΕΒΔΟΜΟ|"
                       r"ΟΓΔΟΟ|ΕΝΑΤΟ|ΔΕΚΑΤΟ\S*|ΠΡΩΤΟΣ|ΔΕΥΤΕΡΟΣ|ΤΡΙΤΟΣ|ΤΕΤΑΡΤΟΣ|ΠΕΜΠΤΟΣ|ΕΚΤΟΣ|ΕΒΔΟΜΟΣ|ΟΓΔΟΟΣ|ΕΝΑΤΟΣ)"
                       r"(\s.*)?$")
ART_RE = re.compile(r"^(\**\s?(?:Άρθρο|Αρθρο|ΑΡΘΡΟ|Άρθρον|Αρθρον|ΑΡΘΡΟΝ))\s+(\d+[α-ω]?\s*[΄'’]?|[Α-ΩΆ-Ώα-ωά-ώ]+(?:\s[Α-ΩΆ-Ώα-ωά-ώ]+)?)"
                    r"\s*(?:[-–—:.]\s*(.*))?$")
ART_LOOSE = re.compile(r"^\**\s?(Άρθρο|Αρθρο|ΑΡΘΡΟ|Άρθρον|ΑΡΘΡΟΝ)\s+(\d+|[Α-ΩΆ-Ώ][Α-ΩΆ-Ώα-ωά-ώ]*)\b")

DROP_RE = [re.compile(p) for p in [
    r"^ΕΦΗΜΕΡΙ[ΣΔ]Α?\s*ΤΗΣ\s*ΚΥΒΕΡΝΗΣΕΩΣ",
    r"^ΕΦΗΜΕΡΙ[ΣΔ]Α?$",
    r"^ΤΗΣ\s*ΚΥΒΕΡΝΗΣΕΩΣ$",
    r"^\(?ΤΕΥΧΟΣ\s*ΠΡΩΤΟ\)?$",
    r"^\d{1,5}$",
    r"^Τεύχος\s*[ΑA]\s*[΄’'`´]?\s*\d+\s*/\s*\d{1,2}\.\d{1,2}\.\d{2,4}$",
    r"^Τ[Εε][ΥΎυ][ΧΧχ][ΟΌο][ΣΣς]\s*[ΑA]\s*[΄’'`´]?\s*\d+\s*/\s*\d{1,2}\.\d{1,2}\.\d{2,4}$",
    r"^ΑΡ(ΙΘΜΟΣ|\.)\s*ΦΥΛΛΟΥ\s*\d+$",
    r"^Αρ\.\s*Φύλλου\s*\d+$",
    r"^\*[0-9]{10,}\*$",
    r"^E$",
]]
END_RE = re.compile(r"^(Την ευθύνη για την εκτύπωση|ΥΠΗΡΕΣΙΕΣ ΠΟΥ ΠΑΡΕΧΕΙ ΤΟ ΕΘΝΙΚΟ ΤΥΠΟΓΡΑΦΕΙΟ|"
                    r"ΕΘΝΙΚΟ ΤΥΠΟΓΡΑΦΕΙΟ$|ΚΑΠΟΔΙΣΤΡΙΟΥ 34|Καποδιστρίου 34, Τ\.Κ\.|ΤΙΜΗ ΠΩΛΗΣΗΣ ΦΥΛΛΟΥ|"
                    r"ΔΙΕΥΘΥΝΤΗΣ ΤΟΥ ΕΘΝΙΚΟΥ ΤΥΠΟΓΡΑΦΕΙΟΥ|Ο ΔΙΕΥΘΥΝΤΗΣ ΤΟΥ ΕΘΝΙΚΟΥ ΤΥΠΟΓΡΑΦΕΙΟΥ|"
                    r"ΠΡΟΣΩΠΙΚΗ ΕΞΥΠΗΡΕΤΗΣΗ ΚΟΙΝΟΥ|ΕΞΥΠΗΡΕΤΗΣΗ ΚΟΙΝΟΥ|Ταχυδρομική Διεύθυνση: Καποδιστρίου)")

GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")
HIGH_RE = re.compile(r"[ -ÿ]")


def cp1253_fix(s):
    out = []
    for c in s:
        o = ord(c)
        if 0xA0 <= o <= 0xFF:
            try:
                out.append(bytes([o]).decode("cp1253"))
                continue
            except UnicodeDecodeError:
                pass
        out.append(c)
    return "".join(out)


TONOS_CAP = {"Α": "Ά", "Ε": "Έ", "Η": "Ή", "Ι": "Ί", "Ο": "Ό", "Υ": "Ύ", "Ω": "Ώ"}


C1_RE = re.compile(r"[\u0080-\u009f]")
LAT2GR_UP = str.maketrans("ABEHIKMNOPTXYZ", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖ")
LAT2GR_ANY = str.maketrans("ABEHIKMNOPTXYZoυv", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖουν")
LATIN_RE = re.compile(r"[A-Za-z]")


def latin_lookalikes(w):
    """Fix Latin look-alike glyphs inside Greek words (a font artefact of many ΦΕΚ PDFs,
    e.g. 'ΣYNΤAΓMA', 'Kοινοβουλευτική'). Only words that already contain Greek letters and
    whose Latin letters are all look-alikes are changed."""
    if not LATIN_RE.search(w) or not GREEK_RE.search(w):
        return w
    lat = set(re.findall(r"[A-Za-z]", w))
    if lat <= set("ABEHIKMNOPTXYZo"):
        return w.translate(LAT2GR_ANY)
    return w


def word_fix(w, legacy):
    if legacy and HIGH_RE.search(w) and not GREEK_RE.search(w):
        w = cp1253_fix(w)
    if C1_RE.search(w):
        w = C1_RE.sub(lambda m: bytes([ord(m.group(0))]).decode("cp1253", "replace"), w)
    w = w.translate(FIX)
    w = latin_lookalikes(w)
    # detached tonos before a capital vowel (old typesetting: "΄Αρθρο") -> accented capital
    w = re.sub(r"^([«(]?)[\u0384\u00b4\u1ffd]([ΑΕΗΙΟΥΩ])(?=[α-ωά-ώ])", lambda m: m.group(1) + TONOS_CAP[m.group(2)], w)
    return w


class Line:
    __slots__ = ("x0", "x1", "y0", "y1", "text", "page", "h")

    def __init__(self, x0, x1, y0, y1, text, page):
        self.x0, self.x1, self.y0, self.y1, self.text, self.page = x0, x1, y0, y1, text, page
        self.h = y1 - y0


def extract_lines(pdf):
    """Return list of pages, each a list of Line in reading order."""
    r = subprocess.run(["pdftotext", "-bbox-layout", pdf, "-"], capture_output=True, timeout=900)
    data = r.stdout
    if not data:
        return [], False
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(data, parser)
    ns = "{http://www.w3.org/1999/xhtml}"
    pages = []
    raw_words = []
    for pi, page in enumerate(root.iter(ns + "page")):
        pw = float(page.get("width"))
        lines = []
        for line in page.iter(ns + "line"):
            words = [w.text or "" for w in line.iter(ns + "word")]
            raw_words.extend(words)
            lines.append((float(line.get("xMin")), float(line.get("xMax")), float(line.get("yMin")),
                          float(line.get("yMax")), words))
        pages.append((pw, lines))
    alltext = " ".join(raw_words)
    legacy = len(HIGH_RE.findall(alltext)) > max(50, len(GREEK_RE.findall(alltext)))
    out = []
    for pi, (pw, lines) in enumerate(pages):
        pl = []
        for x0, x1, y0, y1, words in lines:
            ws = [word_fix(w, legacy) for w in words]
            for j, w in enumerate(ws):
                if re.fullmatch(r"[«(]?[HOTABEIKMNPXYZ][)»,.΄’']?", w):
                    nb = (ws[j + 1] if j + 1 < len(ws) else "") + (ws[j - 1] if j else "")
                    if GREEK_RE.search(nb) and not LATIN_RE.search(nb):
                        ws[j] = w.translate(LAT2GR_UP)
            t = " ".join(ws).strip()
            t = re.sub(r"\s+", " ", t)
            if t:
                pl.append(Line(x0, x1, y0, y1, t, pi))
        out.append((pw, pl))
    return out, legacy


def norm(s):
    return s.translate(LOOK).upper()


def is_drop(ln):
    if ln.h < 5.2 and ln.page == 0:   # digital-signature stamp
        return True
    t = ln.text
    n = norm(t)
    n2 = re.sub(r"\s+", " ", n)
    for r in DROP_RE:
        if r.match(t) or r.match(n2):
            return True
    if re.match(r"^(SIGNATURE NOT|VERIFIED$|DIGITALLY SIGNED|DATE: \d{4}\.|REASON:|LOCATION:|TYPOGRAFIO|\(EMBEDDED\)|EEST$|EET$)", t.upper()):
        return True
    return False


def column_geometry(pw, lines):
    """Per-page column margins: returns function line -> (left, right).

    The column split is the x position crossed by the fewest lines; margins are the most
    frequent left/right edges of the long (justified) lines of each column, so that indented
    first lines, headings and short last lines do not disturb them."""
    split = None
    if lines:
        best = None
        for sx in range(int(pw * 0.38), int(pw * 0.62), 3):
            cross = sum(1 for l in lines if l.x0 < sx - 2 and l.x1 > sx + 2)
            left = sum(1 for l in lines if l.x1 <= sx + 2)
            right = sum(1 for l in lines if l.x0 >= sx - 2)
            if left >= 0.2 * len(lines) and right >= 0.2 * len(lines):
                if best is None or cross < best[0]:
                    best = (cross, sx)
        if best and best[0] <= 0.2 * len(lines):
            split = best[1]

    def key(ln):
        if split is None:
            return "F"
        if ln.x0 < split - 2 and ln.x1 > split + 2:
            return "F"
        return "L" if ln.x1 <= split + 2 else "R"
    cols = collections.defaultdict(list)
    for ln in lines:
        cols[key(ln)].append(ln)
    geo = {}
    for k, ls in cols.items():
        span = max(l.x1 for l in ls) - min(l.x0 for l in ls)
        longs = [l for l in ls if l.x1 - l.x0 > span * 0.6] or ls
        lefts = collections.Counter(round(l.x0) for l in longs)
        rights = collections.Counter(round(l.x1) for l in longs)
        top_l = lefts.most_common(1)[0][1]
        top_r = rights.most_common(1)[0][1]
        geo[k] = (min(v for v, c in lefts.items() if c >= max(2, top_l * 0.25)) if top_l >= 2 else min(lefts),
                  max(v for v, c in rights.items() if c >= max(2, top_r * 0.25)) if top_r >= 2 else max(rights))
    if "L" in geo and "R" in geo:
        geo["F"] = (geo["L"][0], geo["R"][1])

    def f(ln):
        return geo.get(key(ln), (ln.x0, ln.x1))
    return f


def build_paragraphs(pages):
    """Re-flow lines into paragraphs. Returns list of (text, centered:bool)."""
    paras = []
    cur = []
    cur_centered = False
    prev = None

    def flush():
        nonlocal cur, cur_centered
        if cur:
            txt = join_lines(cur)
            paras.append((txt.strip(), cur_centered))
        cur = []
        cur_centered = False

    for pw, lines in pages:
        geo = column_geometry(pw, lines)
        for ln in lines:
            if is_drop(ln):
                continue
            if END_RE.match(ln.text):
                flush()
                paras.append(("\x00END", False))
                prev = None
                continue
            left, right = geo(ln)
            width = right - left
            indent = ln.x0 - left
            rgap = right - ln.x1
            centered = indent > 5 and rgap > 5 and abs(indent - rgap) < 4
            indented = 4 < indent and not centered
            new = False
            nt = norm(ln.text).translate(ACCENTS)
            enum = re.match(r"^(\d{1,3}[α-ω]?\.|[α-ωά-ώ]{1,3}[\.)΄]|\([α-ω0-9]{1,4}\)|[ivx]+\))\s", ln.text)
            if prev is None:
                new = True
            elif re.match(r"^(Ο ΠΡΟΕΔΡΟΣ|ΕΧΟΝΤΑΣ ΥΠΟΨΗ|ΑΠΟΦΑΣΙΖΟΥΜΕ|ΕΚΔΙΔΟΜΕ)", nt):
                new = True
            elif (ART_LOOSE.match(ln.text) and len(ln.text) < 40) or \
                    (STRUCT_RE.match(nt) and len(ln.text) < 60 and is_upper_text(ln.text)) or \
                    (ACT_HEAD.match(nt) and is_upper_text(ln.text[:12])):
                new = True
            elif (ART_LOOSE.match(prev[0]) and len(prev[0]) < 40) or \
                    (STRUCT_RE.match(norm(prev[0]).translate(ACCENTS)) and len(prev[0]) < 60) or prev[6]:
                new = True
            elif enum and (prev[3] or prev[2]):
                new = True
            elif indent > 5 and prev[8] > 5 and prev[9] > 5 and not prev[3] and \
                    (abs(indent - prev[8]) <= 2 or (centered and prev[1])):
                new = False   # continuation of a display block (centred or block-indented title)
            elif indented and prev[7] and abs(ln.x0 - prev[5]) > 2:
                new = True
            elif indented and prev[7] and abs(ln.x0 - prev[5]) <= 2 and not (prev[2] and prev[3]):
                new = False   # block-indented text
            elif indented and indent < width * 0.5 and (prev[3] or not prev[4]):
                new = True
            elif prev[2]:  # previous line ended short -> paragraph end
                new = True
            if TRACE:
                print(f"{'NEW' if new else '   '} c={int(centered)} i={int(indented)} ind={indent:.0f} rg={rgap:.0f} geo=({left},{right}) {ln.text[:60]}", file=sys.stderr)
            if new:
                flush()
                cur_centered = centered
            cur.append(ln.text)
            short = rgap > max(15, width * 0.08) and not centered
            ends_sentence = bool(re.search(r"[.:;·»]$", ln.text))
            full = rgap < max(6, width * 0.03)
            is_act = bool(ACT_HEAD.match(nt)) and is_upper_text(ln.text[:12])
            prev = (ln.text, centered, short, ends_sentence, full, ln.x0, is_act, indented, indent, rgap)
    flush()
    return paras


def find_acts(paras):
    """Return list of (index, kind_norm, number) for act headings in the issue."""
    res = []
    for i, (t, c) in enumerate(paras):
        n = norm(t)
        m = ACT_HEAD.match(n)
        if not m:
            continue
        rest = m.group(1)
        # table-of-contents lines are usually in sentence case and followed by page numbers;
        # real headings are upper case and short
        if len(t) > 90 and not NUM_RE.search(n[:60]):
            continue
        if t != t.upper() and not re.match(r"^(N|Ν)(O|Ο)(M|Μ)(O|Ο)(Σ|Σ)", t):
            # mixed case lines are not headings
            continue
        num = None
        mm = NUM_RE.search(rest)
        if mm:
            num = mm.group(1)
        res.append((i, n, num))
    return res


def cut_act(paras, tcfg, number):
    acts = find_acts(paras)
    head = re.compile("^" + tcfg["head"])
    cands = [a for a in acts if head.match(a[1])]
    sel = None
    if number:
        for a in cands:
            if a[2] == number:
                sel = a
                break
    if sel is None and len(cands) == 1 and (not number or cands[0][2] is None):
        sel = cands[0]
    if sel is None and not number and cands:
        sel = cands[0]
    if sel is None:
        return None
    start = sel[0]
    end = len(paras)
    for a in acts:
        if a[0] > start:
            end = a[0]
            break
    for j in range(start, end):
        if paras[j][0] == "\x00END":
            end = j
            break
    return paras[start:end]


def roman_or_word(s):
    return s


ORDINALS = {}
for _i, _w in enumerate(["ΠΡΩΤΟ", "ΔΕΥΤΕΡΟ", "ΤΡΙΤΟ", "ΤΕΤΑΡΤΟ", "ΠΕΜΠΤΟ", "ΕΚΤΟ", "ΕΒΔΟΜΟ", "ΟΓΔΟΟ",
                         "ΕΝΑΤΟ", "ΔΕΚΑΤΟ", "ΕΝΔΕΚΑΤΟ", "ΔΩΔΕΚΑΤΟ"], 1):
    _ORD = _w
    ORDINALS[_w] = _i
ACCENTS = str.maketrans("ΆΈΉΊΌΎΏΪΫ", "ΑΕΗΙΟΥΩΙΥ")


def art_number(label):
    """'Άρθρο 12' -> 12, 'Άρθρο Πρώτο' -> 1, else None."""
    m = re.search(r"(\d+)", label)
    if m:
        return int(m.group(1))
    w = label.split(None, 1)[1].upper().translate(ACCENTS).strip() if " " in label else ""
    return ORDINALS.get(w)


def join_lines(parts):
    txt = ""
    for t in parts:
        t = t.strip()
        if not txt:
            txt = t
        elif re.search(r"\w[-−‐]$", txt) and t[:1].islower():
            txt = txt[:-1] + t
        elif re.search(r"\w[-−‐]$", txt):
            txt = txt + t
        else:
            txt = txt + " " + t
    return txt


def quote_delta(t):
    """Net change of «» nesting depth caused by paragraph t. An opening « left unclosed only
    counts when it starts the paragraph or follows a colon (start of a quoted provision);
    otherwise it is most likely a typo in the source and is ignored."""
    stack = []
    closes = 0
    for i, ch in enumerate(t):
        if ch == "«":
            stack.append(i)
        elif ch == "»":
            if stack:
                stack.pop()
            else:
                closes += 1
    opens = 0
    for i in stack:
        before = t[:i].rstrip()
        if not before or before.endswith((":", "«", "\"", "“")):
            opens += 1
    return opens - closes


def is_upper_text(t):
    letters = [c for c in t if c.isalpha()]
    return len(letters) >= 3 and all(not c.islower() for c in letters)


def head_label(t):
    n = norm(t).translate(ACCENTS)
    m = STRUCT_RE.match(n)
    if m:
        return m.group(1) + " " + m.group(2).rstrip("΄'’`")
    m = ART_LOOSE.match(t)
    if m:
        return "ΑΡΘΡΟ " + m.group(2).upper().translate(ACCENTS)
    return None


def to_markdown(seg, title_line, quotes=True, any_case_titles=False):
    """seg: paragraphs starting with the act heading. Returns (act_title, markdown_body)."""
    i = 1
    title_parts = []
    while i < len(seg) and len(title_parts) < 6:
        t = seg[i][0]
        n = norm(t).translate(ACCENTS)
        if n.startswith("Ο ΠΡΟΕΔΡΟΣ") or n.startswith("ΕΧΟΝΤΑΣ ΥΠΟΨΗ") or n.startswith("ΕΧΟΝΤΕΣ") \
                or ART_LOOSE.match(t) or n.startswith("Η ΒΟΥΛΗ") or n.startswith("ΕΚΔΙΔΟΜΕ") \
                or n.startswith("ΑΠΟΦΑΣΙΖΟΥΜΕ") or n.startswith("ΚΗΡΥΤΤΟΜΕΝ") or STRUCT_RE.match(n):
            break
        title_parts.append(t)
        i += 1
    if len(title_parts) >= 6:
        title_parts = title_parts[:1]
    act_title = join_lines(title_parts)
    rest = [p for p in seg[1 + len(title_parts):] if p[0] != "\x00END"]

    # table of contents (ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ) of modern laws: keep as plain text
    toc_end = -1
    for j in range(min(len(rest), 12)):
        if re.match(r"^(ΠΙΝΑΚΑΣ ΠΕΡΙΕΧΟΜΕΝΩΝ|ΠΕΡΙΕΧΟΜΕΝΑ)$", norm(rest[j][0]).translate(ACCENTS).strip()):
            first = None
            for k2 in range(j + 1, len(rest)):
                lab = head_label(rest[k2][0])
                if lab:
                    if first is None:
                        first = (lab, k2)
                    elif lab == first[0] and k2 > first[1] + 1:
                        toc_end = k2
                        break
            if toc_end > 0:
                toc_start = j
            break

    present = set()
    for t, c in rest[toc_end if toc_end > 0 else 0:]:
        m = STRUCT_RE.match(norm(t))
        if m and len(t) < 160:
            present.add(dict(STRUCT)[m.group(1)])
    first_seen = {}
    for j, (t, c) in enumerate(rest[toc_end if toc_end > 0 else 0:]):
        m = STRUCT_RE.match(norm(t))
        if m and len(t) < 160:
            first_seen.setdefault(m.group(1), j)
    rank_of = dict(STRUCT)
    if "ΤΜΗΜΑ" in first_seen and "ΚΕΦΑΛΑΙΟ" in first_seen and first_seen["ΤΜΗΜΑ"] < first_seen["ΚΕΦΑΛΑΙΟ"]:
        rank_of["ΤΜΗΜΑ"], rank_of["ΚΕΦΑΛΑΙΟ"] = 4, 5
    present = {rank_of[k] for k in first_seen}
    ranks = sorted(present)
    level_of = {r: 2 + k for k, r in enumerate(ranks)}
    art_level = min(6, 2 + len(ranks))
    out = []
    k = 0
    if toc_end > 0:
        out.extend(md_escape(t) for t, c in rest[:toc_start])
        out.append("**" + md_escape(rest[toc_start][0]) + "**")
        out.extend(md_escape(t) for t, c in rest[toc_start + 1:toc_end])
        k = toc_end
    depth = 0
    quote_len = 0
    last_art = 0
    while k < len(rest):
        t, c = rest[k]
        k += 1
        n = norm(t)
        in_quote = quotes and (depth > 0 or t.lstrip().startswith(("«", '"', "“")))
        sm = STRUCT_RE.match(n) if len(t) < 160 and is_upper_text(t.split()[0]) else None
        am = ART_RE.match(t) if len(t) < 200 else None
        if am and in_quote and depth > 0 and not t.lstrip().startswith("«"):
            num = art_number(f"{am.group(1)} {am.group(2)}")
            if num is not None and num == last_art + 1 and quote_len > 300:
                in_quote = False   # resynchronise: next article of the act itself
                depth = 0
        if sm and not in_quote:
            lvl = level_of.get(rank_of[sm.group(1)], 2)
            heading = t
            titles = []
            while k < len(rest) and len(rest[k][0]) < 300 \
                    and (is_upper_text(rest[k][0]) or (any_case_titles and not titles
                                                       and not re.search(r"[.:;,·]$", rest[k][0]))) \
                    and not ART_LOOSE.match(rest[k][0]) and not STRUCT_RE.match(norm(rest[k][0])) \
                    and not ACT_HEAD.match(norm(rest[k][0])) and len(titles) < 4:
                titles.append(rest[k][0])
                k += 1
            if titles:
                heading = f"{t} — " + " ".join(titles)
            out.append("#" * lvl + " " + md_escape_heading(heading))
            continue
        if am and not in_quote:
            label = f"{am.group(1)} {am.group(2).strip()}"
            num = art_number(label)
            if num is not None:
                last_art = num
            extra = (am.group(3) or "").strip()
            out.append("#" * art_level + " " + md_escape_heading(label))
            if extra:
                out.append(f"**{md_escape(extra)}**")
            elif k < len(rest):
                nt = rest[k][0]
                if len(nt) < 300 and not ART_LOOSE.match(nt) and not STRUCT_RE.match(norm(nt)) \
                        and not re.search(r"[.:;,·]$", nt) and not re.match(r"^(\d|«|\()", nt):
                    k += 1
                    while nt.rstrip().endswith(("-", "–")) and k < len(rest) and len(rest[k][0]) < 200 \
                            and not re.search(r"[.:;,·]$", rest[k][0]) and not ART_LOOSE.match(rest[k][0]):
                        nt = nt + " " + rest[k][0]
                        k += 1
                    out.append(f"**{md_escape(nt)}**")
                    depth += quote_delta(nt)
            continue
        if in_quote and (am or (sm and len(t) < 160)):
            out.append(f"**{md_escape(t)}**" if not t.startswith("«") else md_escape(t))
        else:
            out.append(md_escape(t))
        depth += quote_delta(t)
        if depth < 0:
            depth = 0
        quote_len = quote_len + 1 if depth > 0 else 0
    return act_title, "\n\n".join(out).strip() + "\n"


def md_escape(t):
    t = t.replace("*", "\\*").replace("_", "\\_")
    t = re.sub(r"^(#+)", r"\\\1", t)
    t = re.sub(r"^([-+*])(\s)", r"\\\1\2", t)
    t = re.sub(r"^(\d+)\.(\s)", r"\1\\.\2", t)
    t = re.sub(r"^>", r"\\>", t)
    return t


def md_escape_heading(t):
    return t.replace("#", "\\#").replace("*", "\\*").replace("_", "\\_")


def yaml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sentence_case_desc(s):
    return s


def load_index(cat):
    with open(os.path.join(RAW, "index", f"cat{cat}.json"), encoding="utf-8") as f:
        return json.loads(json.load(f)["data"])


def mdy(s):
    m, d, y = s[:10].split("/")
    return f"{y}-{m}-{d}"


def target_path(cat, x, used):
    t = TYPES[cat]
    date = mdy(x["search_IssueDate"])
    year = date[:4]
    num = x["search_LawProtocolNumber"].strip()
    fek = int(x["search_DocumentNumber"])
    if num.isdigit():
        base = f"{t['prefix']}-{int(num)}-{year}"
    else:
        base = f"{t['prefix']}-{date}-fek-a-{fek}"
    path = os.path.join(t["dir"], year, base + ".md")
    if path in used:
        path = os.path.join(t["dir"], year, f"{base}-fek-a-{fek}.md")
    used.add(path)
    return path


def convert_issue(job):
    """job: (pdf_path, [(cat, entry, relpath), ...]) -> list of (relpath, status)"""
    pdf, entries = job
    res = []
    try:
        pages, legacy = extract_lines(pdf)
        paras = build_paragraphs(pages)
    except Exception as e:  # noqa
        return [(e2[2], f"error:{e}") for e2 in entries]
    for cat, x, rel in entries:
        t = TYPES[cat]
        num = x["search_LawProtocolNumber"].strip() or None
        seg = cut_act(paras, t, num)
        whole = False
        if seg is None:
            # fall back to the whole issue only when it holds a single act
            if len(entries) == 1 and len(find_acts(paras)) <= 1:
                seg = [(t["label"].upper(), True)] + [p for p in paras if p[0] != "\x00END"]
                whole = True
            else:
                res.append((rel, "notfound"))
                continue
        act_title, body = to_markdown(seg, None)
        if len(body) < 80:
            res.append((rel, "empty"))
            continue
        desc = x["search_Description"].strip()
        if not act_title or len(act_title) > 1500:
            act_title = desc
        date = mdy(x["search_IssueDate"])
        year = date[:4]
        fek = int(x["search_DocumentNumber"])
        fekname = f"{year}01{fek:05d}"
        ident = f"{t['short']} {num}/{year}" if num else f"{t['short']} ΦΕΚ Α' {fek}/{year}"
        heading = f"{t['label']} {num}/{year}" if num else f"{t['label']} (ΦΕΚ Α' {fek}/{year})"
        full_title = f"{heading} — {act_title}" if act_title else heading
        full_title = re.sub(r"\s+", " ", full_title)
        fm = [
            "---",
            f"title: {yaml_str(full_title)}",
            f"identifier: {yaml_str(ident)}",
            f"type: {t['kind']}",
            f"subtype: {yaml_str(t['label'])}",
            "jurisdiction: gr",
            "language: el",
            f"date: {date}",
            f"gazette: {yaml_str(f'ΦΕΚ Α {fek}/{date[8:10]}.{date[5:7]}.{year}')}",
            "status: unknown",
            "consolidated: false",
            f"source: \"{BLOB}/01/{year}/{fekname}.pdf\"",
            f"retrieved: {TODAY}",
        ]
        if whole:
            fm.append("note: \"Act heading not detected in the ΦΕΚ text layer; full issue text reproduced.\"")
        if legacy:
            fm.append("note_encoding: \"Text layer uses legacy Windows-1253 Greek fonts; transcoded.\"")
        fm.append("---")
        md = "\n".join(fm) + "\n\n# " + md_escape_heading(full_title) + "\n\n" + body
        path = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        res.append((rel, "whole" if whole else "ok"))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default="1,2,3")
    ap.add_argument("--from-year", type=int, default=1975)
    ap.add_argument("--to-year", type=int, default=2100)
    ap.add_argument("--only", default=None, help="ΦΕΚ file name e.g. 20190100141")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    used = set()
    issues = collections.defaultdict(list)
    for cat in args.types.split(","):
        entries = load_index(cat)
        entries.sort(key=lambda x: (x["search_IssueDate"][6:10], int(x["search_DocumentNumber"]),
                                    x["search_LawProtocolNumber"]))
        for x in entries:
            year = int(x["search_IssueDate"][6:10])
            if not (args.from_year <= year <= args.to_year):
                continue
            fekname = f"{year}{int(x['search_IssueGroupID']):02d}{int(x['search_DocumentNumber']):05d}"
            if args.only and fekname != args.only:
                continue
            pdf = os.path.join(RAW, "pdf", str(year), fekname + ".pdf")
            if not os.path.exists(pdf):
                continue
            # skip exact duplicate index rows
            key = (cat, x["search_LawProtocolNumber"], fekname)
            if any((c, e["search_LawProtocolNumber"]) == key[:2] for c, e, _ in issues[pdf]):
                continue
            rel = target_path(cat, x, used)
            issues[pdf].append((cat, x, rel))
    jobs = sorted(issues.items())
    print(f"{len(jobs)} issues, {sum(len(v) for _, v in jobs)} acts", flush=True)
    stats = collections.Counter()
    log = open(os.path.join(RAW, "convert.log"), "a", encoding="utf-8")
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for i, res in enumerate(ex.map(convert_issue, jobs, chunksize=4)):
            for rel, st in res:
                stats[st.split(":")[0]] += 1
                if st not in ("ok",):
                    log.write(f"{st}\t{rel}\t{jobs[i][0]}\n")
            if i % 500 == 0:
                print(i, dict(stats), flush=True)
    print("done", dict(stats), flush=True)


if __name__ == "__main__":
    main()
