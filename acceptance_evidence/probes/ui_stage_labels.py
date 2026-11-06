"""UI check: open a completed RFQ on a fresh page and read the left-pane stage labels and header pill."""
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright
RFQ = sys.argv[1]
OUT = Path(r"C:\CAM[3.4]-RFQ_centum\acceptance_evidence\probes\out"); OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    pg.goto("http://localhost:5181/#/login", wait_until="networkidle")
    pg.click("text=Sign in as Tester"); pg.wait_for_url("**/#/", timeout=15000)
    pg.wait_for_selector("#rfq-search-textbox", timeout=10000)
    pg.fill("#rfq-search-textbox", RFQ); pg.press("#rfq-search-textbox", "Enter")
    time.sleep(5)
    pg.mouse.click(24, 482); time.sleep(2)
    labels = pg.locator("text=/^(Completed|Waiting|Not in this profile|Running|Failed)/").all_inner_texts()
    header = pg.locator("text=/^(Completed|Running|Failed)$/").all_inner_texts()
    print("STAGE_LABELS", labels)
    print("HEADER", header)
    pg.screenshot(path=str(OUT / f"{RFQ}_stages.png"))
    b.close()
