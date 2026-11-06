"""Probe a COMPLETED RFQ in the real UI: open each left-rail stage and record what it offers.

Read-only: it clicks stage icons and screenshots, nothing else.
"""
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

RFQ_ID = sys.argv[1]
OUT = Path(r"C:\CAM[3.4]-RFQ_centum\acceptance_evidence") / "probe_stages" / RFQ_ID
OUT.mkdir(parents=True, exist_ok=True)

# Left-rail icon centres (x=24) in the 1400x900 viewport, top to bottom, as seen in the take screenshots
STAGE_LABELS = ["Finalize price", "Quote Readiness", "Reports & Analytics", "Consolidate Pricing Sources"]

DOWNLOAD_SELECTOR = "button, a"
DOWNLOAD_WORD = re.compile(r"download|export|excel|xlsx", re.I)


def visible_download_labels(page):
    labels = []
    for el in page.query_selector_all(DOWNLOAD_SELECTOR):
        if el.is_visible():
            text = el.inner_text().strip()
            if DOWNLOAD_WORD.search(text):
                labels.append(text[:60])
    return labels


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    context = browser.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True)
    page = context.new_page()
    page.goto("http://localhost:5181/#/login", wait_until="networkidle")
    page.click("text=Sign in as Tester")
    page.wait_for_url("**/#/", timeout=15000)
    page.wait_for_selector("#rfq-search-textbox", timeout=10000)
    page.fill("#rfq-search-textbox", RFQ_ID)
    page.press("#rfq-search-textbox", "Enter")
    time.sleep(3)

    report = []
    for i, label in enumerate(STAGE_LABELS):
        page.click(f"text={label}")
        time.sleep(2)
        shot = OUT / f"stage_{i}_{label.replace(' ', '_').replace('&', 'and')}.png"
        page.screenshot(path=str(shot))
        report.append({"stage": label, "download_controls": visible_download_labels(page), "screenshot": str(shot)})
        print(json.dumps(report[-1]))

    (OUT / "probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    browser.close()
