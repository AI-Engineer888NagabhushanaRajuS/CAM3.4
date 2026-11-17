"""The one place the intake step asks the local model (qwen2.5-coder:7b through Ollama) to map a file's column headers.

Why it exists: every standardize tool (SCRUB BOM, QuoteWin, costing sheet, ERP) sends the file's headers and the target schema to the
model. On this machine's 8 GB GPU that call took 19 to 90 s per file; for the same headers the answer is the same every time, and the
model's own answers vary between runs (the callers force the critical fields because of it). Under a batch of RFQs the calls queued in
Ollama behind the callers' HTTP timeouts and piled up as orphaned work. So:
  1. the answer is cached on disk under a hash of the exact request (model + both prompts): the same headers against the same schema
     are asked once, and a changed prompt or schema is a new key;
  2. a miss runs one at a time, with a hard timeout, and the model stays loaded between calls;
  3. a mapping is cached only when it holds every field the caller needs, so a poor first answer is never made permanent.
`chat` takes and returns what `ollama.chat(model=..., messages=..., format=...)` does for these callers (`response["message"]["content"]`).
"""
import hashlib
import json
import os
import tempfile
import threading

import ollama

CACHE_DIR = os.environ.get("CAM_MAPPING_CACHE_DIR", "/app/database/mapping_cache")
TIMEOUT = float(os.environ.get("CAM_OLLAMA_TIMEOUT", "300"))
KEEP_ALIVE = os.environ.get("CAM_OLLAMA_KEEP_ALIVE", "30m")
# ponytail: one model call at a time (one GPU, one Ollama slot); raise to a Semaphore only if the GPU ever has headroom.
_slot = threading.Lock()
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = ollama.Client(timeout=TIMEOUT)  # the host comes from OLLAMA_HOST, as for ollama.chat
    return _client


def _key(model, messages):
    blob = json.dumps({"model": model, "messages": messages}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _path(key):
    return os.path.join(CACHE_DIR, key + ".json")


def _load(key):
    try:
        with open(_path(key), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _store(key, content):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, _path(key))  # atomic: a reader never sees half a file
    except OSError:
        pass  # a cache that cannot be written only makes the next run slower


def _complete(content, required):
    try:
        data = json.loads(content)
    except ValueError:
        return False
    return isinstance(data, dict) and any(v is not None for v in data.values()) and all(data.get(f) is not None for f in required)


def chat(model, messages, format=None, required=()):
    """ollama.chat for header mapping: cached by request, one miss at a time. `required` are the fields the caller cannot go on without."""
    key = _key(model, messages)
    cached = _load(key)
    if cached is not None:
        return {"message": {"content": cached}}
    with _slot:
        cached = _load(key)  # another request may have filled it while this one waited its turn
        if cached is not None:
            return {"message": {"content": cached}}
        response = _get_client().chat(model=model, messages=messages, format=format, keep_alive=KEEP_ALIVE)
        content = response["message"]["content"]
        if _complete(content, required):
            _store(key, content)  # inside the lock: the request queued behind this one must find it
    return response
