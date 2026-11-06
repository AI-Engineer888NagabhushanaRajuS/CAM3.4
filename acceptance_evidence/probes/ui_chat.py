"""UI check: ask the RFQ Assistant a question and read what the pane shows back."""
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
    box = pg.locator("input[placeholder^='Ask about this RFQ'], textarea[placeholder^='Ask about this RFQ']").first
    box.fill("What is the A-class spend for this RFQ?")
    pg.click("button:has-text('Send')")
    time.sleep(25)
    texts = pg.locator("[class*='prose'], [class*='message']").all_inner_texts()
    print("CHAT_TEXTS", [t[:200] for t in texts[-4:]])
    pg.screenshot(path=str(OUT / f"{RFQ}_chat.png"))
    b.close()
