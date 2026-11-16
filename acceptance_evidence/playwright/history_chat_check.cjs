// Check: a conversation with an RFQ comes back after a new browser session (History / reopen). Real Chrome, real daemon.
const { createRequire } = require('module');
const path = require('path');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const RFQ = 'RFQ-000062';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 1000 } });
  const p = await ctx.newPage();
  const open = async () => {
    await p.waitForSelector('input[placeholder*="Search by RFQ"]', { state: 'visible', timeout: 60000 });
    const s = p.locator('input[placeholder*="Search by RFQ"]').first(); await s.fill(RFQ); await s.press('Enter'); await p.waitForTimeout(4000);
  };
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  await p.waitForTimeout(3000);
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForTimeout(6000); }
  await p.waitForSelector('textarea', { state: 'attached', timeout: 30000 });
  await open();
  const ask = p.getByPlaceholder(/Ask anything|Ask about this RFQ/i).first();
  const question = 'what is the status of this RFQ';
  await ask.fill(question); await ask.press('Enter');
  await p.waitForFunction((q) => document.body.innerText.includes(q), question, { timeout: 60000 });
  await p.waitForTimeout(25000);   // let the answer arrive and be saved (the save waits 0.8 s)
  const before = await p.evaluate(() => document.body.innerText.includes('status of this RFQ'));
  console.log('before new session: question visible =', before);
  // a new browser session: the page's session storage is empty; the daemon keeps the conversation
  await p.evaluate(() => sessionStorage.clear());
  await p.reload({ waitUntil: 'networkidle' });
  await p.waitForTimeout(4000);
  await p.getByRole('button', { name: /Sign in as Tester/i }).click();
  await p.waitForTimeout(8000);
  await p.waitForSelector('textarea', { state: 'attached', timeout: 30000 });
  await open();
  await p.waitForTimeout(8000);
  const after = await p.evaluate(() => document.body.innerText.includes('status of this RFQ'));
  console.log('after new session: question visible =', after);
  await p.screenshot({ path: path.join(__dirname, 'screenshots', 'history-chat-after-new-session.png') });
  await b.close();
  process.exitCode = before && after ? 0 : 1;
})().catch((e) => { console.log('ERROR', e.message.slice(0, 200)); process.exitCode = 1; });
