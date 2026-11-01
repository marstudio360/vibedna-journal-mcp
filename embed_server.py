"""Embedding service for meaning.py on a machine with a GPU (2026-10-30).

meaning.py can embed locally with a small CPU model (the default, works on any computer) or send texts here when
JOURNAL_MEANING_URL points at this service: a stronger retrieval model (default BAAI/bge-m3, multilingual) on the
GPU, shared by every machine of the same team. Texts are journal entries, so bind it to a PRIVATE address only
(a Tailscale or LAN IP, or 127.0.0.1), never a public one.

  python embed_server.py --host 100.x.y.z --port 47312
  GET  /health            -> {"ok": true, "model": ..., "dim": ..., "device": ...}
  POST /embed {"texts": [...]}  -> {"model": ..., "vectors": [[...], ...]}  (unit length, float)

Needs: torch + sentence-transformers. Env: EMBED_MODEL, EMBED_BATCH (64), HF_HOME (model files).
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
BATCH = int(os.environ.get("EMBED_BATCH", "64"))
MAX_TEXTS = 512


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=47312)
    a = ap.parse_args()
    # Take the address first: a second copy exits before loading the model.
    srv = ThreadingHTTPServer((a.host, a.port), None)

    import torch
    from sentence_transformers import SentenceTransformer
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL, device=dev)
    if dev == "cuda":
        model.half()
    model.max_seq_length = 512
    dim = model.get_sentence_embedding_dimension()
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/health"):
                self._send(200, {"ok": True, "model": MODEL, "dim": dim, "device": dev})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self.path.startswith("/embed"):
                return self._send(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                texts = json.loads(self.rfile.read(n) or b"{}").get("texts") or []
                if not isinstance(texts, list) or len(texts) > MAX_TEXTS:
                    return self._send(400, {"error": f"texts must be a list of at most {MAX_TEXTS}"})
                texts = [str(t)[:4000] for t in texts]
                with lock:
                    v = model.encode(texts, batch_size=BATCH, normalize_embeddings=True, convert_to_numpy=True)
                self._send(200, {"model": MODEL, "vectors": v.astype("float32").round(5).tolist()})
            except Exception as e:
                self._send(500, {"error": str(e)[:300]})

    srv.RequestHandlerClass = H
    srv.serve_forever()


if __name__ == "__main__":
    main()
