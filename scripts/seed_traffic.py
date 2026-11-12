#!/usr/bin/env python3
"""Seed realistic demo traffic through the gateway so the admin UI has something to show.
Stdlib only. Usage: python3 scripts/seed_traffic.py [--fast] [topup|tail]
  (no mode) full seed run; "topup" = extra key B traffic only (raises B spend by ~$0.36);
  "tail" = ~20 interleaved calls so the newest rows on the logs page are a clean mix.

Sends about 80 chat calls over a few minutes: key A (gpt-4o-mini + claude-sonnet), key B
(gpt-4o-mini only, paced under its 10 requests/minute limit), a couple of master-key calls to the
fallback route, and a few deliberate refusals (key B -> claude-sonnet, HTTP 403).
Prompt sizes vary from a few hundred tokens up to tens of thousands so tokens and cost vary.
Mocked providers return a tiny canned reply, so cost is driven by prompt size: to reach a visible share
of the small demo budgets the larger prompts are big. Budgets are never exceeded (hard caps below).
"""
import json, os, random, sys, time, urllib.request, urllib.error

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
FAST = "--fast" in sys.argv
MODE = next((a for a in sys.argv[1:] if a in ("topup", "tail")), "full")
MAXTOK = 100000 if MODE == "topup" else 40000

# USD per token, same as config.yaml
PRICE = {"gpt-4o-mini": (0.00000015, 0.0000006), "claude-sonnet": (0.000003, 0.000015), "resilient-chat": (0.00000015, 0.0000006)}
TARGET = {"A": 0.50, "B": 0.045}      # aimed-for final spend (of $1 and $0.10 budgets)
HARD_CAP = {"A": 0.85, "B": 0.085}    # never plan to go above this
MIN_B_GAP = 7.0                       # seconds between key B requests (limit is 10/min)

rnd = random.Random(20261112)
WORDS = ("gateway budget virtual key model request token latency fallback routing policy team analytics support "
         "invoice customer ticket summary report quarter revenue forecast pipeline contract renewal churn onboarding "
         "dashboard audit compliance retention embedding classification extraction translation draft review escalation "
         "incident postmortem deployment rollback database migration index query cache queue worker schedule alert "
         "threshold dataset sample feature release roadmap priority stakeholder meeting agenda minutes action owner").split()

ratio = {"gpt-4o-mini": 1.3, "claude-sonnet": 1.3, "resilient-chat": 1.3}   # tokens per word, refined from usage

def filler(tokens, model):
    n = max(20, int(tokens / ratio[model]))
    words = [rnd.choice(WORDS) for _ in range(n)]
    for i in range(12, n, 14):
        words[i] += "."
    return "Please summarise the following notes in two sentences. " + " ".join(words)

def post(key, model, tokens):
    prompt = filler(tokens, model)
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode()
    headers = {"Content-Type": "application/json"}
    if key: headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read()), len(prompt.split())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw), len(prompt.split())
        except Exception: return e.code, raw.decode(errors="replace"), len(prompt.split())

# ---- plan -------------------------------------------------------------------------------------------
def item(kind, who, model, **kw):
    return {"kind": kind, "who": who, "model": model, **kw}
def a_mini():  return item("ok", "A", "gpt-4o-mini", tokens=rnd.randint(300, 3000))
def a_son():   return item("ok", "A", "claude-sonnet", weight=rnd.uniform(0.3, 1.7))
def b_mini():  return item("ok", "B", "gpt-4o-mini", weight=rnd.uniform(0.1, 1.9))
def ref():     return item("refused", "B", "claude-sonnet", tokens=rnd.randint(300, 1500))
def fb():      return item("fallback", "M", "resilient-chat", tokens=rnd.randint(300, 1500))

if MODE == "topup":
    TARGET.update({"A": 0.0, "B": 0.36}); HARD_CAP.update({"A": 0.0, "B": 0.40})
elif MODE == "tail":
    TARGET.update({"A": 0.05, "B": 0.06}); HARD_CAP.update({"A": 0.1, "B": 0.09})
head = [a_mini() for _ in range(27)] + [a_son() for _ in range(8)] + [b_mini() for _ in range(24)] + [ref(), fb()]
rnd.shuffle(head)
# keep the first call a cheap one so the early part of the run is quiet
# Last 20 calls: interleaved successes from both keys and both models, 3 refusals, 1 fallback.
TAIL = "A-mini B-mini A-son REF A-mini B-mini A-son A-mini B-mini REF A-son B-mini A-mini FB A-son B-mini REF A-mini B-mini A-son".split()
mk = {"A-mini": a_mini, "A-son": a_son, "B-mini": b_mini, "REF": ref, "FB": fb}
tail = [mk[t]() for t in TAIL]
plan = {"full": head + tail, "topup": [b_mini() for _ in range(26)], "tail": tail}[MODE]

# ---- run --------------------------------------------------------------------------------------------
spent = {"A": 0.0, "B": 0.0}
last_b = 0.0
counts = {}
def cost(model, usage):
    pi, po = PRICE[model]
    return usage.get("prompt_tokens", 0) * pi + usage.get("completion_tokens", 0) * po

def tokens_for(it, idx):
    if "tokens" in it: return it["tokens"]
    rest = plan[idx:]
    who = it["who"]
    # remaining spend to reach target, minus the fixed-size calls still to come for that key
    fixed = sum(x["tokens"] * PRICE[x["model"]][0] for x in rest if x["who"] == who and "tokens" in x)
    wsum = sum(x["weight"] for x in rest if x["who"] == who and "weight" in x)
    price = PRICE[it["model"]][0]
    budget_left = max(0.0, TARGET[who] - spent[who] - fixed)
    t = it["weight"] * budget_left / (wsum * price) if wsum else 1000
    return int(min(max(t, 300), MAXTOK))

t0 = time.time()
total = len(plan)
# spread the run over roughly 5 minutes
gap = 0.4 if FAST else 3.4
for idx, it in enumerate(plan):
    who, model = it["who"], it["model"]
    tok = tokens_for(it, idx)
    if who in spent and it["kind"] == "ok":
        est = tok * PRICE[model][0]
        if spent[who] + est > HARD_CAP[who]:
            print(f"[{idx+1}/{total}] skip {who} {model}: would pass the cap"); continue
    if who == "B" and not FAST:
        wait = MIN_B_GAP - (time.time() - last_b)
        if wait > 0: time.sleep(wait)
        last_b = time.time()
    key = {"A": KEY_A, "B": KEY_B, "M": MASTER}[who]
    status, body, words = post(key, model, tok)
    if status == 200 and isinstance(body, dict):
        u = body.get("usage", {})
        if words and u.get("prompt_tokens"):
            ratio[model] = max(0.5, min(3.0, u["prompt_tokens"] / (words + 10)))
        c = cost(model if model != "resilient-chat" else "gpt-4o-mini", u)
        if who in spent: spent[who] += c
        tag = f"ok  prompt={u.get('prompt_tokens')} cost=${c:.6f}"
    else:
        tag = f"HTTP {status}"
    exp = {"ok": 200, "fallback": 200, "refused": 403}[it["kind"]]
    flag = "" if status == exp else "   <-- UNEXPECTED"
    counts[(who, model, status)] = counts.get((who, model, status), 0) + 1
    print(f"[{idx+1}/{total}] key {who} {model:15s} {tag}{flag}", flush=True)
    time.sleep(gap * rnd.uniform(0.6, 1.4))

print(f"\nDone in {time.time()-t0:.0f}s, {total} calls. Client-side spend estimate: A=${spent['A']:.4f} B=${spent['B']:.4f}")
for k, v in sorted(counts.items()): print(" ", k, v)
