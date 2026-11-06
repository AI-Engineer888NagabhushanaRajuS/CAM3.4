import time
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(r"C:\CAM[3.4]-RFQ_centum\acceptance_evidence\probe_qr"); OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True).new_page()
    pg.goto("http://localhost:5181/#/login", wait_until="networkidle")
    pg.click("text=Sign in as Tester"); pg.wait_for_url("**/#/", timeout=15000)
    pg.wait_for_selector("#rfq-search-textbox", timeout=10000)
    pg.fill("#rfq-search-textbox", "RFQ-CENTUM-PROOF-05"); pg.press("#rfq-search-textbox", "Enter")
    time.sleep(4)
    pg.mouse.click(24, 482); time.sleep(2)
    pg.click("text=Quote Readiness"); time.sleep(3)
    print("download_btn", pg.locator("button:has-text('Download Consolidated BOM')").count())
    print("download_any", [e.inner_text()[:50] for e in pg.query_selector_all("button") if e.is_visible() and "Download" in (e.inner_text() or "")])
    pg.screenshot(path=str(OUT / "quote_readiness.png"))
    b.close()
