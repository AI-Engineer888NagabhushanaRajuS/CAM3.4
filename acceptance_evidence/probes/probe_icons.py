import json, re, time
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(r"C:\CAM[3.4]-RFQ_centum\acceptance_evidence\probe_icons"); OUT.mkdir(parents=True, exist_ok=True)
WORD = re.compile(r"download|export|excel|xlsx", re.I)
ICONS = [("finalize_price", 482), ("quote_readiness", 546), ("reports", 610)]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True).new_page()
    pg.goto("http://localhost:5181/#/login", wait_until="networkidle")
    pg.click("text=Sign in as Tester"); pg.wait_for_url("**/#/", timeout=15000)
    pg.wait_for_selector("#rfq-search-textbox", timeout=10000)
    pg.fill("#rfq-search-textbox", "RFQ-CENTUM-PROOF-05"); pg.press("#rfq-search-textbox", "Enter")
    time.sleep(4)
    report = []
    for name, y in ICONS:
        pg.mouse.click(24, y); time.sleep(3)
        shot = OUT / f"{name}.png"; pg.screenshot(path=str(shot))
        labels = [e.inner_text().strip()[:60] for e in pg.query_selector_all("button, a") if e.is_visible() and WORD.search(e.inner_text() or "")]
        report.append({"icon": name, "download_like": labels, "screenshot": str(shot)})
        print(json.dumps(report[-1]))
    b.close()
