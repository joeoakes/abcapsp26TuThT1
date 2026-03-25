# rag_memory.py
import os
import json
import time
import math
import hashlib
from typing import List, Dict, Any, Tuple, Optional
import requests
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Base URL ONLY (no /api/... suffix)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Keep embedding calls fast; if it fails we fallback to deterministic hash embeddings.
EMBED_TIMEOUT_SEC = float(os.getenv("EMBED_TIMEOUT_SEC", "2.5"))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def maze_signature(width: int, height: int, cells: List[Dict[str,int]]) -> str:
    raw = f"{width}x{height}|" + ",".join(str(c["walls"]) for c in cells)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

def _embed_ollama(text: str) -> Optional[List[float]]:
    # Ollama embeddings endpoints vary by version:
    # - /api/embeddings  (older)
    # - /api/embed       (newer)
    payload = {"model": OLLAMA_EMBED_MODEL, "prompt": text}

    for path in ("/api/embeddings", "/api/embed"):
        try:
            resp = requests.post(f"{OLLAMA_URL}{path}", json=payload, timeout=20)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()

            # Some versions: {"embedding":[...]}
            vec = data.get("embedding")
            if isinstance(vec, list) and vec and isinstance(vec[0], (int, float)):
                return [float(x) for x in vec]

            # Some versions: {"embeddings":[[...]]}
            vecs = data.get("embeddings")
            if isinstance(vecs, list) and vecs and isinstance(vecs[0], list):
                v0 = vecs[0]
                if v0 and isinstance(v0[0], (int, float)):
                    return [float(x) for x in v0]

        except Exception:
            continue

    return None

def _hash_embed(text: str, dim: int = 384) -> List[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(h[:8], "big")
    vec = [0.0] * dim
    x = seed
    for i in range(dim):
        x = (1103515245 * x + 12345) & 0x7fffffff
        vec[i] = (x / 0x7fffffff) * 2 - 1
    return vec

def embed(text: str) -> List[float]:
    v = _embed_ollama(text)
    if v is not None:
        return v
    return _hash_embed(text)

def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    if na == 0 or nb == 0:
        return -1.0
    return dot / (na * nb)

def store_experience(doc: Dict[str,Any]) -> None:
    text = doc.get("text","")
    vec = embed(text)
    doc["embedding"] = vec
    doc["ts"] = int(time.time())

    key = f"maze:rag:doc:{doc['maze_sig']}:{doc['ts']}"
    r.set(key, json.dumps(doc))
    r.sadd(f"maze:rag:index:{doc['maze_sig']}", key)

def retrieve_experience(maze_sig: str, query_text: str, k: int = 4) -> List[Dict[str,Any]]:
    qv = embed(query_text)
    keys = list(r.smembers(f"maze:rag:index:{maze_sig}"))
    if not keys:
        return []

    scored: List[Tuple[float, Dict[str,Any]]] = []
    # cap scan so it stays fast
    for key in keys[-200:]:
        try:
            raw = r.get(key)
            if not raw:
                continue
            doc = json.loads(raw)
            dv = doc.get("embedding")
            if isinstance(dv, list) and dv:
                s = cosine(qv, dv)
                scored.append((s, doc))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:k]]
