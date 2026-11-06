import time
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
    pg = b.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True).new_page()
    seen = []
    pg.on("request", lambda r: seen.append(("REQ", r.method, r.url[:150])) if "13110" in r.url or "13100" in r.url or "export" in r.url else None)
    pg.on("response", lambda r: seen.append(("RES", r.status, r.url[:150])) if "export" in r.url or "13110" in r.url else None)
    pg.on("console", lambda m: seen.append(("CON", m.type, m.text[:160])) if m.type in ("error","warning") else None)
    pg.goto("http://localhost:5181/#/login", wait_until="networkidle")
    pg.click("text=Sign in as Tester"); pg.wait_for_url("**/#/", timeout=15000)
    pg.wait_for_selector("#rfq-search-textbox", timeout=10000)
    pg.fill("#rfq-search-textbox", "RFQ-CENTUM-PROOF-05"); pg.press("#rfq-search-textbox", "Enter")
    time.sleep(4)
    pg.mouse.click(24, 482); time.sleep(3)
    btn = pg.locator("button:has-text('Export Consolidated CBOM')").first
    print("count", pg.locator("button:has-text('Export Consolidated CBOM')").count(), "enabled", btn.is_enabled(), "visible", btn.is_visible())
    seen.clear()
    btn.click(); time.sleep(6)
    for s in seen: print(s)
    print("done")
    b.close()
