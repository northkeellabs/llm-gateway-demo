#!/usr/bin/env python3
"""Capture admin UI screenshots with Playwright (needs `pip install playwright` + a Chromium)."""
import os, sys
from playwright.sync_api import sync_playwright
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
env = {}
for l in open(os.path.join(ROOT, ".env")):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); env[k] = v
B = "http://localhost:4000"
out = os.path.join(ROOT, "screenshots"); os.makedirs(out, exist_ok=True)
with sync_playwright() as p:
    br = p.chromium.launch()
    pg = br.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2).new_page()
    pg.goto(B + "/ui/login"); pg.wait_for_timeout(2500)
    pg.screenshot(path=f"{out}/00-login.png")
    pg.fill('input[name="username"], input[type="text"]', env["UI_USERNAME"])
    pg.fill('input[type="password"]', env["UI_PASSWORD"])
    pg.keyboard.press("Enter"); pg.wait_for_timeout(5000)
    print("after login:", pg.url)
    for name, path in [("01-virtual-keys", "/ui/?page=api-keys"), ("02-usage", "/ui/?page=new_usage"), ("03-logs", "/ui/?page=logs")]:
        pg.goto(B + path); pg.wait_for_timeout(6000)
        print(name, pg.url)
        pg.screenshot(path=f"{out}/{name}.png")
    br.close()
