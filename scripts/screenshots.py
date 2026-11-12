#!/usr/bin/env python3
"""Capture admin UI screenshots with Playwright (needs `pip install playwright` + a Chromium).
Writes 01-virtual-keys, 02-usage, 03-logs, 04-key-detail PNGs (1440x900 viewport, 2x) and boxes.json
(bounding boxes of interesting elements, in screenshot pixel coordinates) to ./screenshots, or to $OUT_DIR.
Run it after scripts/seed_traffic.py so the pages have data."""
import json, os
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
env = {}
for l in open(os.path.join(ROOT, ".env")):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); env[k] = v
B = "http://localhost:4000"
out = os.environ.get("OUT_DIR") or os.path.join(ROOT, "screenshots"); os.makedirs(out, exist_ok=True)
S = 2  # device scale factor
boxes = {}

def bb(el):
    b = el.bounding_box()
    return [round(b["x"] * S), round(b["y"] * S), round((b["x"] + b["width"]) * S), round((b["y"] + b["height"]) * S)]

def rec(page, name, el):
    try:
        boxes.setdefault(page, {})[name] = bb(el)
    except Exception as e:
        print("  box failed:", page, name, e)

def climb(pg, text, min_w, max_w, min_h, nth=0):
    """Smallest ancestor of the element with this exact text that is at least min_w x min_h (and not wider than max_w)."""
    h = pg.get_by_text(text, exact=True).nth(nth).evaluate_handle(
        """(e, a) => { let n = e; while (n.parentElement) { const r = n.getBoundingClientRect();
             if (r.width >= a[0] && r.height >= a[2]) return r.width <= a[1] ? n : e; n = n.parentElement; } return e; }""",
        [min_w, max_w, min_h])
    return h.as_element()

def close_toast(pg):
    try:
        btn = pg.locator('button:has(span:text("Press"))').first
        if btn.count():
            pg.locator('div:has(> button:has(span:text("Press"))) > button').last.click(timeout=2000)
            pg.wait_for_timeout(400)
    except Exception as e:
        print("  toast not closed:", e)

with sync_playwright() as p:
    br = p.chromium.launch()
    pg = br.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=S).new_page()
    pg.goto(B + "/ui/login"); pg.wait_for_timeout(2500)
    pg.fill('input[name="username"], input[type="text"]', env["UI_USERNAME"])
    pg.fill('input[type="password"]', env["UI_PASSWORD"])
    pg.keyboard.press("Enter"); pg.wait_for_timeout(5000)
    print("after login:", pg.url)

    # 01 virtual keys
    pg.goto(B + "/ui/?page=api-keys"); pg.wait_for_timeout(6000); close_toast(pg)
    heads = [t.strip() for t in pg.locator("thead th").all_inner_texts()]
    sc = next(i for i, t in enumerate(heads) if t.startswith("Spend / Budget"))
    for row in pg.locator("tbody tr").all():
        txt = row.inner_text()
        alias = "key-a-analytics" if "key-a-analytics" in txt else "key-b-support" if "key-b-support" in txt else None
        if alias:
            rec("keys", f"row {alias}", row)
            rec("keys", f"spend-budget {alias}", row.locator("td").nth(sc))
    pg.screenshot(path=f"{out}/01-virtual-keys.png"); print("01", pg.url)

    # 02 usage (scroll so the tiles and the daily chart are both in view)
    pg.goto(B + "/ui/?page=new_usage"); pg.wait_for_timeout(8000); close_toast(pg)
    chart = climb(pg, "Daily usage", 900, 1700, 300)
    chart.evaluate("e => e.scrollIntoView({block: 'end'})"); pg.wait_for_timeout(1500)
    for nm, t in [("spend tile", "Spend"), ("total requests tile", "Total Requests"), ("total tokens tile", "Total Tokens")]:
        rec("usage", nm, climb(pg, t, 250, 600, 120))
    rec("usage", "daily usage chart", chart)
    pg.screenshot(path=f"{out}/02-usage.png"); print("02", pg.url)

    # 03 logs
    pg.goto(B + "/ui/?page=logs"); pg.wait_for_timeout(8000); close_toast(pg)
    for nm, t in [("cost column header", "Cost"), ("key alias column header", "Key Alias"), ("model column header", "Model")]:
        rec("logs", nm, pg.locator("thead th", has_text=t).first)
    n = 0
    for badge in pg.get_by_text("Failure", exact=True).all():
        b = badge.bounding_box()
        if not b or b["y"] + b["height"] > 895: continue
        n += 1
        if n > 3: break
        rec("logs", f"failure badge {n}", badge)
        rec("logs", f"failure row {n}", badge.locator("xpath=ancestor::tr[1]"))
    for who in ("key-a-analytics", "key-b-support"):
        for row in pg.locator("tbody tr").all():
            t = row.inner_text()
            if "Success" in t and who in t and row.bounding_box()["y"] + row.bounding_box()["height"] < 895:
                rec("logs", f"success row {who}", row); break
    pg.screenshot(path=f"{out}/03-logs.png"); print("03", pg.url)

    # 04 key detail
    pg.goto(B + "/ui/?page=api-keys"); pg.wait_for_timeout(6000)
    pg.get_by_text("key-a-analytics").first.click(); pg.wait_for_timeout(3500); close_toast(pg)
    rec("key-detail", "allowed models", climb(pg, "Models", 300, 700, 120))
    rec("key-detail", "budget (spend card)", climb(pg, "Spend", 300, 700, 120))
    pg.screenshot(path=f"{out}/04-key-detail.png"); print("04", pg.url)
    br.close()

json.dump(boxes, open(f"{out}/boxes.json", "w"), indent=1)
print(json.dumps(boxes, indent=1))
