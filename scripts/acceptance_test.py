#!/usr/bin/env python3
"""Acceptance test for the gateway. Stdlib only. Usage: python3 scripts/acceptance_test.py"""
import json, os, sys, time, urllib.request, urllib.error

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
def load(path):
    env = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); env[k] = v
    return env
env = {**load(os.path.join(ROOT, ".env")), **load(os.path.join(ROOT, ".keys.env")), **os.environ}
BASE = env.get("LITELLM_URL", "http://localhost:4000")
MASTER, KEY_A, KEY_B = env["LITELLM_MASTER_KEY"], env["KEY_A"], env["KEY_B"]

def call(method, path, key=None, body=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw.decode(errors="replace")

def chat(key, model):
    return call("POST", "/v1/chat/completions", key,
                {"model": model, "messages": [{"role": "user", "content": "Say hello in five words."}]})

results = []
def check(name, ok, detail):
    results.append((name, "PASS" if ok else "FAIL", detail))

s, b = chat(KEY_A, "gpt-4o-mini")
check("a) key A -> gpt-4o-mini allowed", s == 200, f"HTTP {s}: {b['choices'][0]['message']['content']!r}" if s == 200 else f"HTTP {s}")
s, b = chat(KEY_A, "claude-sonnet")
check("b) key A -> claude-sonnet allowed", s == 200, f"HTTP {s}: {b['choices'][0]['message']['content']!r}" if s == 200 else f"HTTP {s}")
s, b = chat(KEY_B, "claude-sonnet")
check("c) key B -> claude-sonnet refused", s in (401, 403), f"HTTP {s}")
s, b = chat(KEY_B, "gpt-4o")
check("d) key B -> gpt-4o refused", s in (401, 403), f"HTTP {s}")
s1, _ = chat(None, "gpt-4o-mini")
s2, _ = chat("sk-not-a-real-key", "gpt-4o-mini")
check("e) no key / bad key refused", s1 in (401, 403) and s2 in (401, 403), f"no key HTTP {s1}, bad key HTTP {s2}")
s, b = chat(KEY_B, "gpt-4o-mini")
check("   key B -> gpt-4o-mini allowed (sanity)", s == 200, f"HTTP {s}")

# (f) spend + logs. Spend is flushed to the DB by a background task, so poll.
spend, tokens, logs = 0, 0, []
for _ in range(24):
    s, info = call("GET", "/key/info?key=" + KEY_A, MASTER)
    spend = (info or {}).get("info", {}).get("spend", 0) if s == 200 else 0
    s2, logs = call("GET", "/spend/logs?api_key=" + KEY_A, MASTER)
    logs = logs if s2 == 200 and isinstance(logs, list) else []
    tokens = sum(l.get("total_tokens", 0) for l in logs)
    if spend > 0 and len(logs) >= 2: break
    time.sleep(5)
check("f) key A spend > 0, logs + tokens visible", spend > 0 and len(logs) >= 2 and tokens > 0,
      f"spend=${spend:.8f}, log rows={len(logs)}, total tokens={tokens}, models={sorted({l.get('model') for l in logs})}")

# (g) fallback: resilient-chat primary is a mocked 500, falls back to gpt-4o-mini
s, b = chat(MASTER, "resilient-chat")
txt = b["choices"][0]["message"]["content"] if s == 200 else ""
check("g) fallback resilient-chat -> gpt-4o-mini", s == 200 and "gpt-4o-mini" in txt, f"HTTP {s}: {txt!r}")

w = max(len(r[0]) for r in results)
out = ["", f"{'TEST'.ljust(w)}  RESULT  DETAIL", "-" * (w + 40)]
out += [f"{n.ljust(w)}  {r}    {d}" for n, r, d in results]
out.append("")
out.append("OVERALL: " + ("PASS" if all(r[1] == "PASS" for r in results) else "FAIL"))
print("\n".join(out))
sys.exit(0 if all(r[1] == "PASS" for r in results) else 1)
