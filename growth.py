#!/usr/bin/env python3
"""Watch your memory grow: one page that plays how your journals grew, day by day.

Every dated entry is one dot, every journal is one cluster, decisions kept are bright dots,
and a line joins two journals that name each other. The page is a single file with no network
calls, so it opens from disk and can be recorded for a demo.

    python growth.py --root <folder> [--root <folder2>] [--out page.html] [--hide-names] [--skip WORD] [--open]
    python growth.py --root <folder> --serve 4747 --open     (live: new entries arrive on the open page)

Default roots are the journal roots the server already uses; default output is
$HOME/.journal/growth/memory_growth.html. --hide-names writes "Project 1, Project 2 ..." instead of
the real journal names, for a page that will be shown to other people.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "growth_page.html"
DEFAULT_OUT = Path(os.environ.get("JOURNAL_HOME") or str(Path(os.path.expanduser("~")) / ".journal")) / "growth" / "memory_growth.html"

_HEAD = re.compile(r"^## (\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?([^\n]*)$", re.M)
_ANY_H2 = re.compile(r"^## ", re.M)
_TAG = re.compile(r"\[([A-Za-z][A-Za-z \-_]{1,22})\]")
_DECIDED = re.compile(r"^## Decided\b[^\n]*\n(.*?)(?=^## |\Z)", re.M | re.S)
_CARD_DATE = re.compile(r"date: (\d{4})-(\d{2})-(\d{2})")
_MONTH_FILE = re.compile(r"^(.*)_(\d{4}-\d{2})$")
_STEM_TOKEN = re.compile(r"\b([A-Z][A-Z0-9_]{2,60}_JOURNAL(?:_[A-Z]{2,12})?)\b")
_WORD = re.compile(r"\S+")

KIND_WORK, KIND_SHIP, KIND_FIX, KIND_CARD = 0, 1, 2, 3
_SHIP = {"ship", "shipped", "live", "deploy", "release", "launch", "published"}
_FIX = {"fix", "bug", "incident", "root-cause", "root cause", "correction", "hotfix"}


def _kind(head_rest: str) -> int:
    m = _TAG.search(head_rest)
    tag = m.group(1).strip().lower() if m else ""
    if tag in _SHIP:
        return KIND_SHIP
    if tag in _FIX:
        return KIND_FIX
    return KIND_WORK


def _day(y: str, m: str, d: str, lo: date, hi: date) -> date | None:
    try:
        v = date(int(y), int(m), int(d))
    except ValueError:
        return None
    return v if lo <= v <= hi else None


_ACRONYMS = {"AI", "AA", "MCP", "IG", "VST", "GPU", "PC", "API", "ASMR", "UI", "UX", "SEO", "DNA", "CRM", "QA", "FX", "3D", "KDP", "DM"}
_SMALL = {"and", "of", "the", "for", "to", "in"}


def pretty(stem: str) -> str:
    """OWNER_VOICE_JOURNAL_DIRECTION -> 'Owner Voice Direction'; mixed-case words stay as written."""
    s = re.sub(r"_JOURNAL(_USER)?$", "", stem, flags=re.I)
    s = re.sub(r"_JOURNAL_", "_", s, flags=re.I)
    out = []
    for w in s.replace("_", " ").replace("-", " ").split():
        if w.upper() in _ACRONYMS:
            out.append(w.upper())
        elif w.upper() == "SAAS":
            out.append("SaaS")
        elif out and w.lower() in _SMALL:
            out.append(w.lower())
        elif w.isupper() or w.islower():
            out.append(w.capitalize())
        else:
            out.append(w)
    return " ".join(out) or stem


def group_of(path: Path, root: Path) -> str:
    try:
        parts = path.resolve().relative_to(root.resolve()).parts[:-1]
    except ValueError:
        parts = ()
    if not parts:
        return "General"
    low = [p.lower() for p in parts]
    if "companies" in low and low.index("companies") + 1 < len(parts):
        return pretty(parts[low.index("companies") + 1])
    return pretty(parts[0])


def parse_journal(text: str, lo: date, hi: date) -> tuple[list[tuple], list[date]]:
    """([(day, minutes, kind, words, title)], [card day]) from one journal's text."""
    cuts = [m.start() for m in _ANY_H2.finditer(text)] + [len(text)]
    entries = []
    for m in _HEAD.finditer(text):
        day = _day(m.group(1), m.group(2), m.group(3), lo, hi)
        if day is None:
            continue
        minutes = (int(m.group(4)) * 60 + int(m.group(5))) if m.group(4) else 0
        end = next((c for c in cuts if c > m.start()), len(text))
        words = len(_WORD.findall(text[m.end():end]))
        entries.append((day, minutes, _kind(m.group(6)), words, m.group(6).strip()[:80]))
    cards = []
    sec = _DECIDED.search(text)
    if sec:
        for line in sec.group(1).splitlines():
            if not line.startswith("- **"):
                continue
            d = _CARD_DATE.search(line)
            day = _day(d.group(1), d.group(2), d.group(3), lo, hi) if d else None
            if day:
                cards.append(day)
    return entries, cards


def decided_cards(text: str) -> list[str]:
    """The card lines of a journal's Decided section."""
    sec = _DECIDED.search(text)
    return [ln for ln in sec.group(1).splitlines() if ln.startswith("- **")] if sec else []


def _card_sig(line: str) -> str:
    """What a card decides, folded, so the same decision kept in two journals is seen as one."""
    m = re.match(r"- \*\*(.+?)\*\*", line)
    sig = re.sub(r"\W+", " ", (m.group(1) if m else line)[:90]).strip().lower()
    return sig if len(sig) >= 25 else ""


def collect(pairs: list[tuple[Path, Path]], skip: list[str] | None = None) -> dict:
    """pairs: (root, journal path). Month files (STEM_YYYY-MM.md) fold into their journal.
    skip: journals whose file name holds one of these words are left out (a raw log, for example)."""
    skip = [w.upper() for w in (skip or []) if w.strip()]
    today = date.today()
    lo, hi = date(2015, 1, 1), today + timedelta(days=1)
    books: dict[str, dict] = {}
    for root, path in pairs:
        stem = path.stem
        mm = _MONTH_FILE.match(stem)
        is_month = bool(mm)
        if mm:
            stem = mm.group(1)
        key = stem.upper()
        if any(w in key for w in skip):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        b = books.setdefault(key, {"stem": stem, "group": None, "seen": set(), "entries": [], "cards": set(), "refs": {},
                                   "card_refs": {}, "card_sigs": set()})
        if b["group"] is None or not is_month:
            b["group"] = group_of(path, root)
        entries, cards = parse_journal(text, lo, hi)
        for e in entries:
            sig = (e[0], e[1], e[4])
            if sig in b["seen"]:
                continue
            b["seen"].add(sig)
            b["entries"].append(e)
        for i, c in enumerate(cards):
            b["cards"].add((c, i))
        for tok in _STEM_TOKEN.findall(text):
            t = tok.upper()
            if t != key:
                b["refs"][t] = b["refs"].get(t, 0) + 1
        for line in decided_cards(text):
            sig = _card_sig(line)
            if sig:
                b["card_sigs"].add(sig)
            for t in {tok.upper() for tok in _STEM_TOKEN.findall(line)}:
                if t != key:
                    b["card_refs"][t] = b["card_refs"].get(t, 0) + 1
    return {k: b for k, b in books.items() if b["entries"]}


DEMO_TOP = ["Online Store", "Paid Ads", "Welcome Emails", "Sales Page", "YouTube Channel", "Customer Support", "Checkout",
            "Newsletter", "Brand Guide", "Product Launch", "Instagram", "Blog", "Pricing", "Analytics", "Mobile App",
            "Affiliate Program", "Online Course", "Podcast", "Booking System", "Community", "Search", "Landing Pages",
            "Design System", "Automations", "Market Research", "Video Editing", "Invoices", "Onboarding", "Reviews", "Partnerships"]
DEMO_A = ["Shop", "Studio", "Agency", "App", "Course", "Channel", "Label", "Store", "Club", "Brand"]
DEMO_B = ["Website", "Ads", "Emails", "Content", "Support", "Launch", "Analytics", "Automation", "Social", "Videos",
          "Design", "Research", "Sales", "Members", "Catalog", "Partners", "Events", "Finance"]


def demo_names(sizes: list[int]) -> list[str]:
    """Invented, believable project names for a page that is shown to other people: the biggest journals get the
    plainest names. Same input, same names."""
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i])
    pool = DEMO_TOP + ["%s %s" % (a, b) for b in DEMO_B for a in DEMO_A]
    names = [""] * len(sizes)
    for rank, i in enumerate(order):
        names[i] = pool[rank] if rank < len(pool) else "Project %d" % (rank + 1)
    return names


def build_data(books: dict, hide_names: bool = False, demo: bool = False) -> dict:
    keys = sorted(books, key=lambda k: min(e[0] for e in books[k]["entries"]))
    idx = {k: i for i, k in enumerate(keys)}
    groups: list[str] = []
    journals = []
    for k in keys:
        g = books[k]["group"] or "General"
        if g not in groups:
            groups.append(g)
        journals.append({"n": pretty(books[k]["stem"]), "g": groups.index(g), "k": hashlib.sha1(k.encode()).hexdigest()[:8]})
    if demo:
        made_up = demo_names([len(books[k]["entries"]) for k in keys])
        for i, j in enumerate(journals):
            j["n"] = made_up[i]
        groups = ["Area %d" % (i + 1) for i in range(len(groups))]
    elif hide_names:
        for i, j in enumerate(journals):
            j["n"] = "Project %d" % (i + 1)
        groups = ["Area %d" % (i + 1) for i in range(len(groups))]
    rows = []
    for k in keys:
        b = books[k]
        for day, minutes, kind, words, title in b["entries"]:
            rows.append((day, minutes, idx[k], kind, words, title))
        for day, _ in b["cards"]:
            rows.append((day, 24 * 60, idx[k], KIND_CARD, 0, ""))
    rows.sort(key=lambda r: (r[0], r[1]))
    day0 = rows[0][0]
    ndays = (rows[-1][0] - day0).days + 1
    flat: list[int] = []
    words_by_day = [0] * ndays
    for day, _, j, kind, words, _title in rows:
        d = (day - day0).days
        flat += [d, j, kind]
        words_by_day[d] += words
    pair: dict[tuple[int, int], int] = {}
    for k in keys:
        for t, n in books[k]["refs"].items():
            if t in idx:
                a, b_ = sorted((idx[k], idx[t]))
                pair[(a, b_)] = pair.get((a, b_), 0) + n
    links = sorted(([a, b_, n] for (a, b_), n in pair.items() if n >= 2), key=lambda x: -x[2])[:320]
    written = [r for r in rows if r[3] != KIND_CARD][-14:]
    recent = [[r[2], "%s %02d:%02d" % (r[0].strftime("%d %b"), r[1] // 60, r[1] % 60), "" if (hide_names or demo) else r[5]] for r in written]
    return {
        "day0": day0.isoformat(), "days": ndays, "groups": groups, "journals": journals,
        "e": flat, "w": words_by_day, "links": links, "hidden": bool(hide_names) and not demo, "demo": bool(demo), "recent": recent,
        "sig": "%d-%d-%d" % (len(rows), sum(words_by_day), len(journals)),
        "made": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "totals": {
            "journals": len(journals),
            "entries": sum(1 for r in rows if r[3] != KIND_CARD),
            "decisions": sum(1 for r in rows if r[3] == KIND_CARD),
            "words": sum(words_by_day),
        },
    }


def meaning_pairs(keys, home: Path | None = None, top: int = 4, floor: float = 0.40) -> dict:
    """{(A, B): 0..100}: journals whose entries talk about the same things, from the vectors the meaning search
    already keeps (index.sqlite, entries_vec). Each journal is the average of its entries, with what all journals
    share taken out. Needs numpy and a built meaning index; without them it is simply empty. The result is kept
    next to the map and computed again only when the vectors changed (0.6 s for 33,000 entries)."""
    home = Path(home or os.environ.get("JOURNAL_HOME") or str(Path(os.path.expanduser("~")) / ".journal"))
    db, cache = home / "index.sqlite", home / "growth" / "neighbours_meaning.json"
    keys = set(keys)
    try:
        import sqlite3
        import numpy as np
        if not db.is_file():
            return {}
        con = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True, timeout=2)
        try:
            sig = "%s|%s|%s" % (con.execute("SELECT COUNT(*), TOTAL(rowid) FROM entries_vec").fetchone(),
                                hashlib.sha1("|".join(sorted(keys)).encode()).hexdigest()[:12], floor)
            try:
                kept = json.loads(cache.read_text(encoding="utf-8"))
                if kept.get("sig") == sig:
                    return {(a, b): n for a, b, n in kept["pairs"]}
            except (OSError, ValueError, KeyError, TypeError):
                pass
            sums, counts, dim = {}, {}, None
            for path, vec in con.execute("SELECT path, vec FROM entries_vec"):
                stem = Path(str(path).replace("\\", "/")).stem
                mm = _MONTH_FILE.match(stem)
                k = (mm.group(1) if mm else stem).upper()
                if k not in keys or not vec:
                    continue
                v = np.frombuffer(vec, dtype=np.float16).astype(np.float32)
                dim = dim or v.size
                if v.size != dim:
                    continue
                if k in sums:
                    sums[k] += v
                    counts[k] += 1
                else:
                    sums[k], counts[k] = v.copy(), 1
        finally:
            con.close()
        names = sorted(k for k in sums if counts[k] >= 5)
        pairs: dict = {}
        if len(names) >= 3:
            c = np.stack([sums[k] / counts[k] for k in names])
            c -= c.mean(axis=0)
            c /= np.linalg.norm(c, axis=1, keepdims=True) + 1e-9
            sim = c @ c.T
            for i, a in enumerate(names):
                for j in np.argsort(-sim[i])[: top + 1]:
                    if j != i and sim[i][j] >= floor:
                        pairs[tuple(sorted((a, names[int(j)])))] = int(round(float(sim[i][j]) * 100))
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"sig": sig, "pairs": [[a, b, n] for (a, b), n in pairs.items()]}), encoding="utf-8")
            os.replace(tmp, cache)
        except OSError:
            pass
        return pairs
    except Exception:
        return {}


def neighbours(books: dict, top: int = 6, meaning: dict | None = None) -> dict:
    """{JOURNAL STEM: [[other journal stem, mentions both ways, day of its last entry, decisions they share,
    meaning 0..100, title of its last entry], ...]}, strongest first. Three reasons tie two journals: they name each
    other, their Decided cards name the other one or say the same thing, and their entries talk about the same
    things (meaning: {(A, B): 0..100} from meaning_pairs, optional)."""
    def pair_key(a, b_):
        return tuple(sorted((a, b_)))

    names: dict[tuple[str, str], int] = {}
    shared: dict[tuple[str, str], int] = {}
    for k, b in books.items():
        for t, n in b["refs"].items():
            if t in books:
                names[pair_key(k, t)] = names.get(pair_key(k, t), 0) + n
        for t, n in (b.get("card_refs") or {}).items():
            if t in books:
                shared[pair_key(k, t)] = shared.get(pair_key(k, t), 0) + n
    by_sig: dict[str, list] = {}
    for k, b in books.items():
        for sig in b.get("card_sigs") or ():
            by_sig.setdefault(sig, []).append(k)
    for ks in by_sig.values():
        for i, a in enumerate(ks):
            for b_ in ks[i + 1:]:
                shared[pair_key(a, b_)] = shared.get(pair_key(a, b_), 0) + 1
    meaning = {pair_key(a, b_): n for (a, b_), n in (meaning or {}).items() if a in books and b_ in books}
    last = {}
    for k, b in books.items():
        e = max(b["entries"], key=lambda x: (x[0], x[1]))
        last[k] = (e[0].isoformat(), re.sub(r"^\s*\[[^\]]*\]\s*", "", e[4])[:60])
    out: dict[str, list] = {}
    for key in set(names) | set(shared) | set(meaning):
        n, s, m = names.get(key, 0), shared.get(key, 0), meaning.get(key, 0)
        if n < 2 and not s and not m:
            continue
        # one strength for the order: naming each other counts by its size, a shared decision as much as ten
        # mentions, the same topics as much as a quarter of their score
        strength = n + 10 * s + m / 4.0
        a, b_ = key
        out.setdefault(a, []).append([books[b_]["stem"], n, last[b_][0], s, m, last[b_][1], strength])
        out.setdefault(b_, []).append([books[a]["stem"], n, last[a][0], s, m, last[a][1], strength])
    return {k: [x[:6] for x in sorted(v, key=lambda x: -x[6])[:top]] for k, v in out.items()}


def write_neighbours(books: dict, folder: Path, meaning: dict | None = None) -> Path:
    """neighbours.json in the folder of the page: the quick map (neighbours.py) reads it."""
    out = Path(folder) / "neighbours.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if meaning is None:
        meaning = meaning_pairs(books.keys())
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"made": datetime.now().strftime("%Y-%m-%d %H:%M"), "made_ts": int(time.time()),
                               "journals": neighbours(books, meaning=meaning)}, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, out)
    return out


def default_roots() -> list[Path]:
    try:
        import obsidian
        return [Path(r) for r in obsidian.rules()[4]()]
    except Exception:
        return []


def find(roots: list[Path]) -> list[tuple[Path, Path]]:
    import obsidian
    return obsidian.find_journals(roots)


def render(data: dict, out: Path) -> Path:
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", blob)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, out)
    return out


def signature(pairs: list[tuple[Path, Path]]) -> tuple:
    """Cheap fingerprint of the journal files: it changes when any of them is written."""
    n = size = newest = 0
    for _, p in pairs:
        try:
            st = p.stat()
        except OSError:
            continue
        n, size, newest = n + 1, size + st.st_size, max(newest, st.st_mtime_ns)
    return n, size, newest


class Live:
    """Keeps one page fresh: rebuilds it when a journal changed. The file list is walked again every
    list_every seconds; between walks only the known files are checked, which costs nothing."""

    def __init__(self, roots, out, skip=None, hide_names=False, list_every=600, demo=False):
        self.roots, self.out, self.skip, self.hide, self.demo = roots, Path(out), skip, hide_names, demo
        self.list_every, self.pairs, self.listed_at, self.sig, self.data_sig = list_every, [], 0.0, None, None

    def tick(self) -> bool:
        """True when the page was written again with different content."""
        now = time.time()
        if not self.pairs or now - self.listed_at > self.list_every:
            words = [w.upper() for w in (self.skip or []) if w.strip()]
            self.pairs = [(r, p) for r, p in find(self.roots) if not any(w in p.stem.upper() for w in words)]
            self.listed_at = now
        sig = signature(self.pairs)
        if sig == self.sig and self.out.exists():
            return False
        self.sig = sig
        books = collect(self.pairs, self.skip)
        if not books:
            return False
        data = build_data(books, self.hide, self.demo)
        write_neighbours(books, self.out.parent)
        if data["sig"] == self.data_sig and self.out.exists():
            return False
        self.data_sig = data["sig"]
        render(data, self.out)
        return True


def serve(live: Live, port: int, every: int = 10) -> None:
    """The page on http://127.0.0.1:<port>, rebuilt while it is open; the page picks up new entries by itself."""
    import http.server
    live.tick()

    def loop():
        while True:
            time.sleep(every)
            try:
                live.tick()
            except Exception as e:  # keep serving the last good page
                print("rebuild failed: %s" % e)

    threading.Thread(target=loop, daemon=True).start()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                body = live.out.read_bytes()
            except OSError:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("memory map live at http://127.0.0.1:%d (Ctrl+C to stop)" % port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Watch your memory grow: one page from your journals.")
    ap.add_argument("--root", action="append", help="folder to scan (repeatable); default: the journal roots")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="where to write the page")
    ap.add_argument("--hide-names", action="store_true", help="write Project 1, Project 2 ... instead of journal names")
    ap.add_argument("--demo-names", action="store_true", help="write invented project names (Online Store, Paid Ads ...) for a page shown to other people")
    ap.add_argument("--skip", action="append", help="leave out journals whose file name holds this word (repeatable)")
    ap.add_argument("--serve", type=int, metavar="PORT", help="keep the page live on http://127.0.0.1:PORT, rebuilt when a journal changes")
    ap.add_argument("--open", action="store_true", help="open the page in the browser when done")
    args = ap.parse_args(argv)
    roots = [Path(r) for r in args.root] if args.root else default_roots()
    if not roots:
        print("no roots: pass --root <folder with your journals>")
        return 2
    if args.serve:
        if args.open:
            threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:%d" % args.serve)).start()
        serve(Live(roots, args.out, args.skip, args.hide_names, demo=args.demo_names), args.serve)
        return 0
    books = collect(find(roots), args.skip)
    if not books:
        print("no dated entries found under: " + ", ".join(str(r) for r in roots))
        return 1
    data = build_data(books, args.hide_names, args.demo_names)
    out = render(data, Path(args.out))
    write_neighbours(books, out.parent)
    t = data["totals"]
    print(json.dumps({"page": str(out), "bytes": out.stat().st_size, "first_day": data["day0"], "days": data["days"],
                      "groups": len(data["groups"]), "links": len(data["links"]), **t}, indent=1))
    if args.open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
