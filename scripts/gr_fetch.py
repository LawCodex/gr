#!/usr/bin/env python3
"""Fetch the index of Greek primary legislation and the corresponding ΦΕΚ (Government Gazette)
PDFs from the National Printing Office (Εθνικό Τυπογραφείο, https://search.et.gr).

Steps
  index  : query the public search API used by https://search.et.gr/el/search-legislation/
           (POST https://searchetv99.azurewebsites.net/api/searchlegislation) once per
           legislation catalogue and store the JSON results in _raw/gr/index/.
  pdf    : download the ΦΕΚ issue PDFs (issue A) from the public Azure blob storage used by the
           same site (https://ia37rg02wpsa01.blob.core.windows.net/fek/...) into _raw/gr/pdf/.
           Each PDF is checked for a text layer immediately (pdftotext); image-only scans are
           recorded in _raw/gr/notext.txt and deleted unless --keep-scans is given.

Usage
  python gr_fetch.py index
  python gr_fetch.py pdf --types 1,2,3 --from-year 1990 --to-year 2026 [--workers 4]
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

RAW = os.environ.get("GR_RAW", "/Users/magicaltux/projects/lawcodex/_raw/gr")
API = "https://searchetv99.azurewebsites.net/api"
BLOB = "https://ia37rg02wpsa01.blob.core.windows.net/fek"
UA = {"User-Agent": "LawCodex/1.0 (+https://github.com/LawCodex)"}
# legislation catalogues exposed by search.et.gr (values of the "legislation_catalogues" select)
CATALOGUES = {
    "1": "Νόμος",
    "2": "Προεδρικό Διάταγμα",
    "3": "Πράξη Νομοθετικού Περιεχομένου",
    "101": "Αναγκαστικός Νόμος",
    "102": "Βασιλικό Διάταγμα",
    "301": "Νομοθετικό Διάταγμα",
    "501": "Νομοθετικό Προεδρικό Διάταγμα",
}

session = requests.Session()
session.headers.update(UA)
lock = threading.Lock()


def req(method, url, **kw):
    for attempt in range(6):
        try:
            r = session.request(method, url, timeout=kw.pop("timeout", 300), **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return r
            print(f"HTTP {r.status_code} {url}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"ERR {e} {url}", file=sys.stderr)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


def load_index(cat):
    with open(os.path.join(RAW, "index", f"cat{cat}.json"), encoding="utf-8") as f:
        return json.loads(json.load(f)["data"])


def cmd_index(args):
    os.makedirs(os.path.join(RAW, "index"), exist_ok=True)
    for cat in CATALOGUES:
        body = {"legislationCatalogues": cat, "legislationNumber": "", "selectYear": []}
        r = req("POST", f"{API}/searchlegislation", json=body)
        d = r.json()
        assert d.get("status") == "ok", d
        with open(os.path.join(RAW, "index", f"cat{cat}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        print(cat, CATALOGUES[cat], len(json.loads(d["data"])))
        time.sleep(2)


def fek_name(x):
    year = x["search_IssueDate"][6:10]
    grp = int(x["search_IssueGroupID"])
    num = int(x["search_DocumentNumber"])
    return year, f"{year}{grp:02d}{num:05d}", f"{BLOB}/{grp:02d}/{year}/{year}{grp:02d}{num:05d}.pdf"


def has_text(path):
    try:
        t = subprocess.run(["pdftotext", "-l", "3", path, "-"], capture_output=True,
                           timeout=120).stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return False
    return sum(1 for c in t if c.isalpha()) > 200


def fetch_one(year, name, url, keep_scans, notext):
    d = os.path.join(RAW, "pdf", year)
    path = os.path.join(d, name + ".pdf")
    if os.path.exists(path) or name in notext:
        return "cached"
    os.makedirs(d, exist_ok=True)
    r = req("GET", url)
    if r.status_code == 404:
        with lock:
            with open(os.path.join(RAW, "missing.txt"), "a") as f:
                f.write(name + "\n")
        return "missing"
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(r.content)
    if not has_text(tmp) and not keep_scans:
        os.remove(tmp)
        with lock:
            notext.add(name)
            with open(os.path.join(RAW, "notext.txt"), "a") as f:
                f.write(name + "\n")
        return "notext"
    os.replace(tmp, path)
    return "ok"


def cmd_pdf(args):
    notext = set()
    p = os.path.join(RAW, "notext.txt")
    if os.path.exists(p):
        notext = set(open(p).read().split())
    if os.path.exists(os.path.join(RAW, "missing.txt")):
        notext |= set(open(os.path.join(RAW, "missing.txt")).read().split())
    jobs = {}
    for cat in args.types.split(","):
        for x in load_index(cat):
            year, name, url = fek_name(x)
            if args.from_year <= int(year) <= args.to_year:
                jobs[name] = (year, name, url)
    jobs = sorted(jobs.values(), reverse=True)
    print(f"{len(jobs)} ΦΕΚ issues", flush=True)
    stats = {}
    with ThreadPoolExecutor(max_workers=min(args.workers, 4)) as ex:
        futs = [ex.submit(fetch_one, *j, args.keep_scans, notext) for j in jobs]
        for i, fu in enumerate(futs):
            try:
                s = fu.result()
            except Exception as e:  # noqa
                s = "error"
                print("error", e, file=sys.stderr)
            stats[s] = stats.get(s, 0) + 1
            if i % 200 == 0:
                print(i, jobs[i][1], stats, flush=True)
    print("done", stats, flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    p = sub.add_parser("pdf")
    p.add_argument("--types", default="1,2,3")
    p.add_argument("--from-year", type=int, default=1975)
    p.add_argument("--to-year", type=int, default=2100)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--keep-scans", action="store_true")
    args = ap.parse_args()
    {"index": cmd_index, "pdf": cmd_pdf}[args.cmd](args)


if __name__ == "__main__":
    main()
