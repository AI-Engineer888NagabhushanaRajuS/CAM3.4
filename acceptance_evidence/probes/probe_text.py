import time
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}).new_page()
    pg.goto("http://localhost:5181/#/login", wait_until="networkidle")
    pg.click("text=Sign in as Tester"); pg.wait_for_url("**/#/", timeout=15000)
    pg.wait_for_selector("#rfq-search-textbox", timeout=10000)
    pg.fill("#rfq-search-textbox", "RFQ-CENTUM-PROOF-05"); pg.press("#rfq-search-textbox", "Enter")
    time.sleep(6)
    for t in ["Finalize", "Quote Readiness", "Reports & Analytics", "Download", "Excel", "Running", "Completed"]:
        print(t, pg.locator(f"text={t}").count())
    pg.screenshot(path=r"C:\CAM[3.4]-RFQ_centum\acceptance_evidence\probe_text_now.png")
    b.close()
