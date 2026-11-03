"""Meaning search for journals (2026-10-30).

Every lexical layer (FTS words, aliases, change words, verdict words) misses a question asked with other words or in
the other language: "el embudo de Ambient Foundations" never matched the entry "SELECTOR DE COMPRA EN LAS 9 FICHAS"
(an upsell modal). Here every journal entry gets one vector from a small multilingual model, so a question finds the
entry that SAYS THE SAME THING, in Spanish or English, in any journal including month archives.

Pieces:
  - entries_vec table in the same index.sqlite: (path, line) -> heading, text hash, float16 vector
  - sync(): embeds new or changed entries of entries_fts (the entry index the server already keeps)
  - a resident service (127.0.0.1:JOURNAL_MEANING_PORT) holds the model and the matrix: a query costs ~0.1 s
  - query(): asks the service; if it is not running it starts it in the background and returns [] this time,
    so a caller never waits and lexical search keeps working without it

Optional: needs `fastembed` + `numpy`. Without them every function returns [] and nothing else changes.
Env: JOURNAL_HOME (index), JOURNAL_MEANING_MODEL, JOURNAL_MEANING_CACHE (model files), JOURNAL_MEANING_PORT,
JOURNAL_MEANING_THREADS, JOURNAL_MEANING_URL (team embedding service, see embed_server.py),
JOURNAL_MEANING_MIN, JOURNAL_MEANING_PYTHON (interpreter for the service; callers only need the standard library),
JOURNAL_MEANING_OFF=1.
CLI: python meaning.py build | serve | query "<text>" | status
"""
from __future__ import annotations

import hashlib
import json
import re
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("JOURNAL_HOME") or str(Path.home() / ".journal"))
DB = HOME / "index.sqlite"
# Where vectors come from: a team embedding service (embed_server.py on a GPU machine, private address only) when
# JOURNAL_MEANING_URL is set, else a small local CPU model that runs on any computer (the buyer default).
# The choice is saved next to the index (meaning.json, written by `build`) so every process (hook, service, server)
# uses the model that made the vectors, whatever environment it started from; env vars override it.
CONF = HOME / "meaning.json"
try:
    _conf = json.loads(CONF.read_text(encoding="utf-8"))
except Exception:
    _conf = {}
URL = (os.environ.get("JOURNAL_MEANING_URL") or _conf.get("url") or "").rstrip("/")
MODEL = os.environ.get("JOURNAL_MEANING_MODEL") or _conf.get("model") or (
    "BAAI/bge-m3" if URL else "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
CACHE = os.environ.get("JOURNAL_MEANING_CACHE") or str(HOME / "meaning-model")
PORT = int(os.environ.get("JOURNAL_MEANING_PORT", "47311"))
THREADS = int(os.environ.get("JOURNAL_MEANING_THREADS", "2"))
TEXT_CHARS = 700          # heading + the start of the body: where an entry says what it is about
MIN_SCORE = float(os.environ.get("JOURNAL_MEANING_MIN") or (0.45 if URL else 0.38))   # below it a hit is noise for that model
OFF = os.environ.get("JOURNAL_MEANING_OFF") == "1"
# Words that carry no topic in the owner's Spanish or English questions (only for the word half of the fusion)
_STOP = set("que qué por para con los las del una uno como esto eso esta este pero porque cuando donde sobre todo "
            "the and for with this that what why how was were are from into about have has had not you your".split())


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("CREATE TABLE IF NOT EXISTS entries_vec (path TEXT, line INTEGER, heading TEXT, h TEXT, vec BLOB, "
              "PRIMARY KEY(path, line))")
    return c


def _text(heading: str, body: str) -> str:
    return ((heading or "") + "\n" + (body or "")).strip()[:TEXT_CHARS]


def _hash(t: str) -> str:
    return hashlib.sha1((MODEL + "|" + t).encode("utf-8")).hexdigest()[:16]


_model = None


def _load_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL, cache_dir=CACHE, threads=THREADS)
    return _model


def _embed_remote(texts: list[str]):
    out = []
    for i in range(0, len(texts), 256):
        req = urllib.request.Request(URL + "/embed", data=json.dumps({"texts": texts[i:i + 256]}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read())
        if body.get("model") != MODEL:
            raise RuntimeError(f"embedding service runs {body.get('model')}, expected {MODEL}")
        out += body["vectors"]
    return out


def embed(texts: list[str]):
    import numpy as np
    if URL:
        v = np.array(_embed_remote(texts), dtype=np.float32)
    else:
        v = np.array(list(_load_model().embed(texts, batch_size=32)), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
    return v


_SYNC_LOCK = HOME / "meaning-sync.lock"


def _take_sync_lock() -> bool:
    """One embedder at a time (2026-10-30: a build plus 10 services embedding the same entries froze the owner's PC).
    The lock is touched every batch; a lock untouched for 5 minutes belongs to a dead process and is taken over."""
    try:
        fd = os.open(str(_SYNC_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - _SYNC_LOCK.stat().st_mtime > 300:
                _SYNC_LOCK.unlink()
                return _take_sync_lock()
        except Exception:
            pass
        return False
    except Exception:
        return False


def _index_model(c) -> str:
    c.execute("CREATE TABLE IF NOT EXISTS meaning_meta (k TEXT PRIMARY KEY, v TEXT)")
    r = c.execute("SELECT v FROM meaning_meta WHERE k='model'").fetchone()
    return r[0] if r else ""


def sync(progress=None, budget_s: float | None = None, force: bool = False) -> dict:
    """Embed every entry of entries_fts that has no vector or whose text changed; drop vectors of gone entries.
    Returns {"busy": True} without doing anything when another process is embedding."""
    # A process configured with another model never touches vectors made by a different one (it would re-embed
    # everything on the wrong machine): only `build` (force) switches an index to a new model.
    c = _conn()
    try:
        have = _index_model(c)
        if have and have != MODEL and not force:
            return {"model_mismatch": {"index": have, "this_process": MODEL}}
        c.execute("INSERT OR REPLACE INTO meaning_meta(k, v) VALUES('model', ?)", (MODEL,))
        c.commit()
    finally:
        c.close()
    if not _take_sync_lock():
        return {"busy": True}
    try:
        return _sync(progress, budget_s)
    finally:
        try:
            _SYNC_LOCK.unlink()
        except Exception:
            pass


def _sync(progress=None, budget_s: float | None = None) -> dict:
    import numpy as np
    c = _conn()
    try:
        have = {(p, int(l)): h for p, l, h in c.execute("SELECT path, line, h FROM entries_vec")}
        todo, live = [], set()
        for p, l, head, body in c.execute("SELECT path, line, heading, body FROM entries_fts"):
            k = (p, int(l))
            live.add(k)
            t = _text(head, body)
            h = _hash(t)
            if have.get(k) != h:
                todo.append((p, int(l), head or "", h, t))
        gone = [k for k in have if k not in live]
        if gone:
            c.executemany("DELETE FROM entries_vec WHERE path=? AND line=?", gone)
            c.commit()
        t0, done = time.time(), 0
        for i in range(0, len(todo), 64):
            part = todo[i:i + 64]
            vecs = embed([x[4] for x in part]).astype(np.float16)
            c.executemany("INSERT OR REPLACE INTO entries_vec(path, line, heading, h, vec) VALUES(?,?,?,?,?)",
                          [(p, l, hd, h, v.tobytes()) for (p, l, hd, h, _), v in zip(part, vecs)])
            c.commit()
            done += len(part)
            try:
                os.utime(_SYNC_LOCK)
            except Exception:
                pass
            if progress:
                progress(done, len(todo), time.time() - t0)
            if budget_s and time.time() - t0 > budget_s:
                break
        return {"embedded": done, "pending": len(todo) - done, "removed": len(gone), "total": len(live)}
    finally:
        c.close()


class _Index:
    """The vectors in memory; reloaded when entries_vec changes."""

    def __init__(self):
        self.sig, self.keys, self.mat = None, [], None

    def ensure(self):
        import numpy as np
        c = _conn()
        try:
            self.model = _index_model(c)
            sig = c.execute("SELECT COUNT(*), TOTAL(rowid) FROM entries_vec").fetchone()
            if sig == self.sig:
                return
            rows = c.execute("SELECT path, line, heading, vec FROM entries_vec").fetchall()
        finally:
            c.close()
        self.keys = [(p, l, h) for p, l, h, _ in rows]
        self.mat = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float16).reshape(len(rows), -1).astype(np.float32) \
            if rows else None
        self.sig = sig

    def search(self, q: str, k: int = 8, min_score: float = MIN_SCORE, path_like: str = "") -> list[dict]:
        """Meaning AND words, fused by rank (reciprocal rank fusion). Measured on the full index (18,429 entries,
        2026-10-30): meaning alone let generic sections ("Architecture", "EL HUECO") outrank the answer and missed
        exact names; words alone miss other phrasings and Spanish. Fused, the real cases land in the top 5."""
        import numpy as np
        self.ensure()
        if self.mat is None or not q.strip() or (getattr(self, "model", "") and self.model != MODEL):
            return []
        s = self.mat @ embed([q[:1000]])[0]
        order = np.argsort(-s)[:400]
        vec_rank = {i: r for r, i in enumerate(order) if s[i] >= min_score}
        pos = {(p, int(l)): i for i, (p, l, _) in enumerate(self.keys)}
        word_rank = {}
        words = [w for w in re.findall(r"[^\W_]{3,}", q.lower()) if w not in _STOP][:12]
        if words:
            try:
                c = _conn()
                try:
                    rows = c.execute("SELECT path, line FROM entries_fts WHERE entries_fts MATCH ? "
                                     "ORDER BY bm25(entries_fts) LIMIT 400",
                                     (" OR ".join('"%s"' % w.replace('"', "") for w in words),)).fetchall()
                finally:
                    c.close()
                for r, (p, l) in enumerate(rows):
                    i = pos.get((p, int(l)))
                    if i is not None:
                        word_rank.setdefault(i, r)
            except Exception:
                pass
        fused = {}
        for ranks in (vec_rank, word_rank):
            for i, r in ranks.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + r)
        out = []
        for i in sorted(fused, key=lambda x: -fused[x]):
            p, l, h = self.keys[i]
            if path_like and path_like.lower() not in p.lower():
                continue
            out.append({"path": p, "journal": Path(p).name, "line": int(l), "heading": (h or "")[:160],
                        "score": round(float(s[i]), 3), "by": "+".join(n for n, d in (("meaning", vec_rank), ("words", word_rank)) if i in d)})
            if len(out) >= k:
                break
        return out


def serve():
    """Resident service: model + vectors in memory; re-syncs new entries every 60 s."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    idx, lock = _Index(), threading.Lock()

    def keep_synced():
        while True:
            try:
                with lock:
                    sync(budget_s=120)
            except Exception:
                pass
            time.sleep(60)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            try:
                if u.path == "/health":
                    body = {"ok": True, "model": MODEL, "vectors": len(idx.keys)}
                elif u.path == "/search":
                    with lock:
                        body = idx.search(qs.get("q", [""])[0], int(qs.get("k", ["8"])[0]),
                                          float(qs.get("min", [MIN_SCORE])[0]), qs.get("path", [""])[0])
                else:
                    self.send_response(404); self.end_headers(); return
                self._send(body)
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode()[:300])

        def do_POST(self):
            # /score {"q": text, "texts": [...]}: how close each text is to q (the "already built" check compares
            # what a new script says it does with the journal lines that name an existing script).
            try:
                if urllib.parse.urlparse(self.path).path != "/score":
                    self.send_response(404); self.end_headers(); return
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                texts = [str(t)[:1000] for t in (req.get("texts") or [])][:64]
                q = str(req.get("q") or "")[:1000]
                body = [round(float(x), 3) for x in embed(texts) @ embed([q])[0]] if texts and q.strip() else []
                self._send(body)
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode()[:300])

        def _send(self, body):
            try:
                data = json.dumps(body).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode()[:300])

    # Take the port FIRST: a second copy fails here and exits before loading anything (2026-10-30: the port was
    # bound only after the ~2 min model load, so every owner message in between started one more copy).
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:
        return
    idx.ensure()
    if getattr(idx, "model", "") and idx.model != MODEL:
        return   # vectors from another model: this copy has nothing to serve
    if not URL:
        _load_model()
    threading.Thread(target=keep_synced, daemon=True).start()
    srv.serve_forever()


def _start_service():
    """Start the resident service in the background (once; a lock file avoids a start storm)."""
    flag = HOME / "meaning-start.lock"
    try:
        if flag.exists() and time.time() - flag.stat().st_mtime < 120:
            return
        flag.write_text(str(time.time()))
        kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # detached, new group, no window
        else:
            kw["start_new_session"] = True
        # The service may run on another interpreter than the hook (the hook only needs urllib): JOURNAL_MEANING_PYTHON
        py = os.environ.get("JOURNAL_MEANING_PYTHON") or sys.executable
        subprocess.Popen([py, str(Path(__file__).resolve()), "serve"], **kw)
    except Exception:
        pass


def query(q: str, k: int = 8, min_score: float = MIN_SCORE, path_like: str = "", timeout: float = 1.5) -> list[dict]:
    """Entries that mean the same as q. Never blocks long and never raises: [] when the service is down."""
    if OFF or not q or not q.strip():
        return []
    url = f"http://127.0.0.1:{PORT}/search?" + urllib.parse.urlencode(
        {"q": q[:1000], "k": k, "min": min_score, "path": path_like})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        # Start a service ONLY when nobody holds the port (connection refused). A slow answer means one is
        # loading: starting another copy is what froze the PC on 2026-10-30.
        reason = getattr(e, "reason", e)
        if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower() or "10061" in str(reason):
            _start_service()
        return []


def score(q: str, texts: list[str], timeout: float = 3.0) -> list[float]:
    """How close each text is to q, by meaning (cosine); [] when the service is down. Never raises."""
    if OFF or not q or not texts:
        return []
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/score", data=json.dumps({"q": q, "texts": texts}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        # Same start rule as query(): score() alone never started a dead service, so on 2026-11-01 the PC service
        # was down and every score-only check (already built, newer value) stayed silent.
        reason = getattr(e, "reason", e)
        if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower() or "10061" in str(reason):
            _start_service()
        return []


def text_lines(hits: list[dict], n: int = 4) -> list[str]:
    """Lines for the quick map: the entries that mean the same as the question, best first."""
    return [f"- SAME MEANING ({h['score']:.2f}, {h['journal']}:{h['line']}): {h['heading']}" for h in hits[:n]]


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # a Windows console died on an emoji heading
    except Exception:
        pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "build":
        def pr(d, t, s):
            if d % 640 == 0 or d == t:
                left = (t - d) * s / max(d, 1)
                print(f"  {d}/{t} entries, about {left / 60:.1f} min left", flush=True)
        CONF.write_text(json.dumps({"url": URL, "model": MODEL}), encoding="utf-8")
        print(json.dumps(sync(progress=pr, force=True)))
    elif cmd == "serve":
        serve()
    elif cmd == "query":
        hits = query(" ".join(sys.argv[2:]), timeout=60)
        if not hits:
            hits = _Index().search(" ".join(sys.argv[2:]))
        print("\n".join(text_lines(hits, 8)) or "no meaning match")
    else:
        c = _conn()
        n = c.execute("SELECT COUNT(*) FROM entries_vec").fetchone()[0]
        m = c.execute("SELECT COUNT(*) FROM entries_fts").fetchone()[0]
        c.close()
        print(json.dumps({"model": MODEL, "vectors": n, "entries": m}))
