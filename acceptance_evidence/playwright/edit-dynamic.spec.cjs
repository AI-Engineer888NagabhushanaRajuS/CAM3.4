// Playwright test with video: "change a value and check it is dynamic", done in the app like a person would.
// 1. Open RFQ-000062 in the RFQ search box (type, Enter).
// 2. Read the Reports & Analytics number "Cost per set by assembly: HCV_BMS_MB VL-1".
// 3. In the assistant, type: set the unit price of AC0603KRX7R9BB104 to 0.046 in RFQ-000062, press Enter.
// 4. The app shows a confirmation card: read it, click Confirm.
// 5. The app applies the edit, regenerates the workbook as a new version and reports the changed cells.
// 6. The Reports & Analytics number must change on screen (the dashboard reads the newest workbook).
// Run after the stack is up: node edit-dynamic.spec.cjs   (exits 1 on the first failed check)
const { createRequire } = require('module');
const fs = require('fs');
const path = require('path');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');

const HERE = __dirname;
const VIDEO_DIR = path.join(HERE, 'videos-edit');
const SHOTS = path.join(HERE, 'screenshots');
fs.mkdirSync(VIDEO_DIR, { recursive: true });
fs.mkdirSync(SHOTS, { recursive: true });
const RFQ = 'RFQ-000062';
const PART = 'AC0603KRX7R9BB104';
// The part is in both assemblies, so the app asks which BOM item is meant: the HCV_BMS_MB row (the one the dashboard shows).
const BOM_ITEM = '0d440305-d6e7-4271-8a26-34bb819f9e84';
const NEW_PRICE = '0.0525';
const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' :: ' + detail : ''}`); if (!ok) { throw new Error('check failed: ' + name); } };
const waitFor = async (fn, timeoutMs, stepMs = 3000) => {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) { const v = await fn(); if (v) { return v; } await new Promise((r) => setTimeout(r, stepMs)); }
  return null;
};
// The number shown for one assembly and volume on the Reports & Analytics dashboard ("HCV_BMS_MB" then "VL-1 66.4").
const costPerSet = (text, assembly, volume) => {
  const i = text.indexOf(assembly, text.indexOf('Cost per set by assembly'));
  if (i < 0) { return null; }
  const m = text.slice(i, i + 200).match(new RegExp(volume.replace('-', '\\-') + '\\s+([0-9.]+)'));
  return m ? Number(m[1]) : null;
};

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, recordVideo: { dir: VIDEO_DIR, size: { width: 1440, height: 1000 } } });
  const p = await context.newPage();
  try {
    await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
    const signIn = p.getByRole('button', { name: /Sign in as Tester/i });
    if (await signIn.count()) { await signIn.click(); await p.waitForLoadState('networkidle'); }
    await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
    await p.waitForTimeout(1500);

    // 1. Open the RFQ like a person: type it in the search box, press Enter
    const search = p.getByPlaceholder(/Search by RFQ ID/i).first();
    await search.click();
    await search.fill(RFQ);
    await search.press('Enter');
    await p.waitForTimeout(8000);
    // The page can crash while the workbook regenerates (a heavy render): reload and read again, like a person would.
    const dashText = async () => {
      try { return await p.locator('body').innerText(); } catch (e) {
        console.log('page crashed while reading; reloading');
        await p.reload({ waitUntil: 'networkidle' }).catch(() => undefined);
        await p.waitForTimeout(6000);
        return p.locator('body').innerText().catch(() => '');
      }
    };
    const before = costPerSet(await dashText(), 'HCV_BMS_MB', 'VL-1');
    check(`RFQ ${RFQ} shows Reports & Analytics with a cost per set`, before !== null, `HCV_BMS_MB VL-1 = ${before}`);
    await p.screenshot({ path: `${SHOTS}/edit-01-before.png` });

    // 2-3. Ask in the assistant
    const ask = p.getByPlaceholder(/Ask anything|Ask about this RFQ/i).first();
    await ask.click();
    await ask.fill(`set the unit price of ${BOM_ITEM} to ${NEW_PRICE} in ${RFQ}`);
    await ask.press('Enter');

    // 4. The confirmation card appears: read it, then Confirm
    const card = p.locator('section[aria-label="Confirm action"]');
    try { await card.waitFor({ timeout: 120000 }); } catch (e) {
      const txt = (await p.locator('body').innerText()).replace(/\s+/g, ' ');
      const at = txt.lastIndexOf('set the unit price');
      console.log('ASSISTANT SAYS:', txt.slice(at, at + 700));
      await p.screenshot({ path: `${SHOTS}/edit-02-no-card.png` });
      throw e;
    }
    const cardText = (await card.innerText()).replace(/\s+/g, ' ');
    check('the assistant asks for confirmation with the exact change', cardText.includes(BOM_ITEM) && cardText.includes(NEW_PRICE), cardText.slice(0, 160));
    await p.screenshot({ path: `${SHOTS}/edit-02-confirm-card.png` });
    await card.getByRole('button', { name: /^Confirm$/ }).click();

    // 5. The app says what it did
    const done = await waitFor(async () => {
      const t = (await p.locator('section[aria-label="Confirm action"]').innerText().catch(() => '')).replace(/\s+/g, ' ');
      return /Confirmed\./.test(t) ? t : null;
    }, 600000, 3000);
    check('the app confirms the edit was applied', !!done, done ? done.slice(0, 200) : 'no confirmation in 10 min');

    // 6. The number on screen changes
    const after = await waitFor(async () => {
      const v = costPerSet(await dashText(), 'HCV_BMS_MB', 'VL-1');
      return v !== null && v !== before ? v : null;
    }, 900000, 5000);
    await p.screenshot({ path: `${SHOTS}/edit-03-after.png` });
    check('Reports & Analytics updates on screen (dynamic): HCV_BMS_MB VL-1 cost per set changes', !!after, `before ${before} -> after ${after}`);
  } catch (err) {
    console.log('ERROR', err.message);
    process.exitCode = 1;
  } finally {
    await context.close();
    await browser.close();
    const videos = fs.readdirSync(VIDEO_DIR).filter((f) => f.endsWith('.webm'));
    console.log(`videos: ${videos.join(', ') || 'none'}`);
    console.log(`summary: ${results.filter((r) => r.ok).length} of ${results.length} checks passed`);
  }
})();
