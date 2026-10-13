#!/usr/bin/env python3
"""Build kodikes/: the major Greek codes (κώδικες) in the text of the act that enacted or
ratified them, as published in ΦΕΚ Α'. The text is taken from the converted act in nomoi/ or
pd/ (gr_convert.py must have run first) and given code-level front matter.

The texts are NOT consolidated: later amendments are not incorporated (see README).
Codes whose enacting ΦΕΚ is an image-only scan (before 2000) are produced by gr_ocr.py.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gr_convert as g  # noqa: E402

# (catalogue, number, year, slug, title)
CODES = [
    ("1", 4619, 2019, "poinikos-kodikas", "Ποινικός Κώδικας"),
    ("1", 4620, 2019, "kodikas-poinikis-dikonomias", "Κώδικας Ποινικής Δικονομίας"),
    ("1", 4172, 2013, "kodikas-forologias-eisodimatos", "Κώδικας Φορολογίας Εισοδήματος"),
    ("1", 2859, 2000, "kodikas-fpa", "Κώδικας Φόρου Προστιθέμενης Αξίας"),
    ("1", 4987, 2022, "kodikas-forologikis-diadikasias", "Κώδικας Φορολογικής Διαδικασίας"),
    ("1", 4978, 2022, "kodikas-eispraxis-dimosion-esodon", "Κώδικας Είσπραξης Δημοσίων Εσόδων"),
    ("1", 2960, 2001, "ethnikos-teloneiakos-kodikas", "Εθνικός Τελωνειακός Κώδικας"),
    ("1", 2961, 2001, "kodikas-forologias-klironomion-dorean", "Κώδικας διατάξεων φορολογίας κληρονομιών, δωρεών, γονικών παροχών, προικών και κερδών από λαχεία"),
    ("1", 3463, 2006, "kodikas-dimon-kai-koinotiton", "Κώδικας Δήμων και Κοινοτήτων"),
    ("1", 3528, 2007, "ypallilikos-kodikas", "Κώδικας Κατάστασης Δημόσιων Πολιτικών Διοικητικών Υπαλλήλων και Υπαλλήλων Ν.Π.Δ.Δ. (Υπαλληλικός Κώδικας)"),
    ("1", 3584, 2007, "kodikas-dimotikon-ypallilon", "Κώδικας Κατάστασης Δημοτικών και Κοινοτικών Υπαλλήλων"),
    ("1", 3284, 2004, "kodikas-ellinikis-ithageneias", "Κώδικας Ελληνικής Ιθαγένειας"),
    ("1", 5038, 2023, "kodikas-metanasteusis", "Κώδικας Μετανάστευσης"),
    ("1", 4939, 2022, "kodikas-ypodochis-diethnous-prostasias", "Κώδικας νομοθεσίας για την υποδοχή, τη διεθνή προστασία πολιτών τρίτων χωρών και ανιθαγενών και την προσωρινή προστασία"),
    ("1", 4194, 2013, "kodikas-dikigoron", "Κώδικας Δικηγόρων"),
    ("1", 2830, 2000, "kodikas-symvolaiografon", "Κώδικας Συμβολαιογράφων"),
    ("1", 4938, 2022, "kodikas-organismou-dikastirion", "Κώδικας Οργανισμού Δικαστηρίων και Κατάστασης Δικαστικών Λειτουργών"),
    ("1", 4798, 2021, "kodikas-dikastikon-ypallilon", "Κώδικας Δικαστικών Υπαλλήλων"),
    ("1", 4129, 2013, "kodikas-elegktikou-synedriou", "Κώδικας Νόμων για το Ελεγκτικό Συνέδριο"),
    ("1", 2882, 2001, "kodikas-anagkastikon-apallotrioseon", "Κώδικας Αναγκαστικών Απαλλοτριώσεων Ακινήτων"),
    ("1", 3588, 2007, "ptocheutikos-kodikas-2007", "Πτωχευτικός Κώδικας (2007)"),
    ("1", 3459, 2006, "kodikas-nomon-gia-ta-narkotika", "Κώδικας Νόμων για τα Ναρκωτικά"),
    ("1", 3850, 2010, "kodikas-ygeias-asfaleias-ergazomenon", "Κώδικας νόμων για την υγεία και την ασφάλεια των εργαζομένων"),
    ("1", 3669, 2008, "kodikas-dimosion-ergon", "Κώδικας νομοθεσίας κατασκευής δημοσίων έργων"),
    ("1", 4858, 2021, "kodikas-archaiotiton", "Κώδικας νομοθεσίας για την προστασία των αρχαιοτήτων και εν γένει της πολιτιστικής κληρονομιάς"),
    ("1", 5020, 2023, "kodikas-idiotikou-naftikou-dikaiou", "Κώδικας Ιδιωτικού Ναυτικού Δικαίου"),
    ("1", 4948, 2022, "kodikas-thalassion-endometaforon", "Κώδικας νομοθεσίας θαλάσσιων ενδομεταφορών και δικαιωμάτων επιβατών"),
    ("1", 3418, 2005, "kodikas-iatrikis-deontologias", "Κώδικας Ιατρικής Δεοντολογίας"),
    ("1", 4548, 2018, "anonymes-etaireies", "Αναμόρφωση του δικαίου των ανωνύμων εταιρειών (ν. 4548/2018)"),
    ("2", 80, 2022, "kodikas-atomikou-ergatikou-dikaiou", "Κώδικας Ατομικού Εργατικού Δικαίου"),
    ("2", 63, 2005, "kodikas-nomothesias-gia-tin-kyvernisi", "Κώδικας νομοθεσίας για την Κυβέρνηση και τα κυβερνητικά όργανα"),
    ("2", 169, 2007, "kodikas-politikon-kai-stratiotikon-syntaxeon", "Κώδικας Πολιτικών και Στρατιωτικών Συντάξεων"),
    ("2", 26, 2012, "kodikas-eklogis-vouleuton", "Κωδικοποίηση της νομοθεσίας για την εκλογή βουλευτών"),
    ("2", 28, 2015, "kodikas-prosvasis-se-dimosia-eggrafa", "Κωδικοποίηση διατάξεων για την πρόσβαση σε δημόσια έγγραφα και στοιχεία"),
]


def main():
    out_dir = os.path.join(g.OUT, "kodikes")
    os.makedirs(out_dir, exist_ok=True)
    made = 0
    for cat, num, year, slug, title in CODES:
        t = g.TYPES[cat]
        src = os.path.join(g.OUT, t["dir"], str(year), f"{t['prefix']}-{num}-{year}.md")
        if not os.path.exists(src):
            print("missing", src)
            continue
        text = open(src, encoding="utf-8").read()
        m = re.match(r"^---\n(.*?)\n---\n\n# [^\n]*\n", text, re.S)
        fm, body = m.group(1), text[m.end():]
        fields = dict(re.findall(r"^(\w+): (.*)$", fm, re.M))
        act = f"{t['short']} {num}/{year}"
        new_fm = [
            "---",
            f"title: {g.yaml_str(title)}",
            f"identifier: {g.yaml_str(act)}",
            "type: code",
            "jurisdiction: gr",
            "language: el",
            f"date: {fields['date']}",
            f"gazette: {fields['gazette']}",
            "status: unknown",
            "consolidated: false",
            f"enacted_by: {g.yaml_str(act)}",
            f"enacting_act_file: \"{t['dir']}/{year}/{t['prefix']}-{num}-{year}.md\"",
            f"source: {fields['source']}",
            f"retrieved: {fields['retrieved']}",
            "note: \"Original text of the enacting act as published in ΦΕΚ Α'; later amendments are not incorporated.\"",
            "---",
        ]
        heading = f"# {g.md_escape_heading(title)}\n\n*{t['label']} {num}/{year} ({fields['gazette'].strip(chr(34))})*\n\n"
        with open(os.path.join(out_dir, slug + ".md"), "w", encoding="utf-8") as f:
            f.write("\n".join(new_fm) + "\n\n" + heading + body)
        made += 1
    print("codes written:", made)


if __name__ == "__main__":
    main()
