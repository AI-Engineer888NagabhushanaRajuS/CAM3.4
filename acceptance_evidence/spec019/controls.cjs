// Real-browser proof of the assistant's app controls (SPEC-019 phase E). Evidence: acceptance_evidence/spec019/20-*.png + controls-net.json
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const fs = require('fs');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
const RFQ = 'RFQ-CENTUM-PROOF-24';

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const chat = []; const difyStart = []; const confirms = [];
  page.on('request', (r) => { if (/\/api\/dify\/start/.test(r.url())) difyStart.push(r.url()); });
  page.on('response', async (r) => {
    if (/\/api\/chat$/.test(r.url()) && r.request().method() === 'POST') { let body = null; try { body = await r.json(); } catch {} chat.push({ req: JSON.parse(r.request().postData() || '{}'), body }); }
    if (/\/api\/chat\/actions\/confirm/.test(r.url())) { let body = null; try { body = await r.json(); } catch {} confirms.push(body); }
  });
  const log = (...a) => console.log(...a);
  await page.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const tester = page.getByRole('button', { name: /Sign in as Tester/i });
  if (await tester.count()) { await tester.click(); await page.waitForLoadState('networkidle'); }
  await page.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  const ask = async (text, ms = 120000) => {
    const before = chat.length;
    await page.fill('[data-testid="task-input-textarea"]', text);
    await page.click('[data-testid="task-input-submit"]');
    const t0 = Date.now();
    while (chat.length === before && Date.now() - t0 < ms) await page.waitForTimeout(400);
    await page.waitForTimeout(900);
    return { ms: Date.now() - t0, e: chat[chat.length - 1] };
  };
  const brief = (r) => `ms=${r.ms} model=${r.e?.body?.model} ui=${r.e?.body?.ui?.type}${r.e?.body?.ui?.action ? '/' + r.e.body.ui.action : ''}`;
  const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });

  // 1 open RFQ: button appears, pressing it selects the RFQ and starts NOTHING
  let r = await ask(`open ${RFQ}`);
  log('1 open:', brief(r), '|', (r.e?.body?.message || '').slice(0, 120));
  const openBtn = page.getByRole('button', { name: new RegExp(`Open ${RFQ}`) });
  log('1 open button visible:', await openBtn.count() > 0);
  const startsBefore = difyStart.length;
  await shot('20-open-button');
  if (await openBtn.count()) { await openBtn.first().click(); await page.waitForTimeout(3500); }
  log('1 after press: scope chip shows RFQ:', (await page.locator('ul[aria-label="Conversation scope"]').innerText().catch(() => '')).includes(RFQ), '| left pane search box value:', await page.getByPlaceholder(/Search by RFQ ID/i).inputValue().catch(() => '?'));
  log('1 /api/dify/start requests caused by Open:', difyStart.length - startsBefore, '(must be 0)');
  await shot('21-after-open');

  // 2 pipeline status (database, no model)
  r = await ask('what stage is it at and what has run so far?');
  log('2 status:', brief(r)); log('2 answer:', (r.e?.body?.message || '').replace(/\n/g, ' | ').slice(0, 420));
  await shot('22-status');

  // 3 a workbook-data question with "status" in it must still be a DATA answer, not the pipeline status
  r = await ask('what is the go / no-go status?');
  log('3 data:', brief(r), '|', (r.e?.body?.message || '').slice(0, 100), '| cites', (r.e?.body?.citations || []).length);

  // 4 download reports: button -> real file
  r = await ask(`download the reports for ${RFQ}`);
  log('4 export:', brief(r), '|', (r.e?.body?.message || '').slice(0, 100));
  const dl = page.getByRole('button', { name: /Download reports/i });
  if (await dl.count()) {
    const [download] = await Promise.all([page.waitForEvent('download', { timeout: 60000 }).catch(() => null), dl.first().click()]);
    if (download) { const p = await download.path(); log('4 downloaded:', download.suggestedFilename(), fs.statSync(p).size, 'bytes'); } else { log('4 no download event; alert:', (await page.getByRole('alert').allInnerTexts()).join(' | ').slice(0, 200)); }
  } else log('4 no download button');
  await shot('23-export');

  // 5 upload
  r = await ask('i want to upload a file');
  log('5 upload:', brief(r), '|', (r.e?.body?.message || '').slice(0, 140));
  const up = page.getByRole('button', { name: /Choose files/i });
  if (await up.count()) { const [fc] = await Promise.all([page.waitForEvent('filechooser', { timeout: 8000 }).catch(() => null), up.first().click()]); log('5 file chooser opened:', !!fc); }

  // 6 settings
  r = await ask('how do i add my openrouter key?');
  log('6 settings:', brief(r), '|', (r.e?.body?.message || '').slice(0, 160));
  const st = page.getByRole('button', { name: /Open Settings/i });
  if (st.count) { if (await st.count()) { await st.first().click(); await page.waitForTimeout(1500); log('6 settings dialog open:', (await page.getByRole('dialog').count()) > 0, '| shows OpenRouter:', (await page.getByRole('dialog').innerText().catch(() => '')).includes('OpenRouter')); await shot('24-settings'); await page.keyboard.press('Escape'); } }

  // 7 resume: refused for an RFQ waiting for review (no write)
  r = await ask('resume the pipeline for RFQ-000017');
  log('7 resume (review pending):', brief(r), '|', (r.e?.body?.message || '').slice(0, 220));

  // 8 resume: a card for an RFQ that is mid-run; press CANCEL only (no run is started)
  r = await ask('resume the pipeline for RFQ-E2E-4');
  log('8 resume card:', brief(r), '|', (r.e?.body?.message || '').slice(0, 200));
  const cancel = page.getByRole('button', { name: /^Cancel$/ }).last();
  await shot('25-resume-card');
  if (r.e?.body?.ui?.type === 'confirm_action' && await cancel.count()) {
    const cp = page.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 30000 });
    await cancel.click(); const resp = await cp; const body = await resp.json();
    log('8 cancel ->', resp.status(), body.ok, body.message);
  }
  log('TOTAL /api/dify/start requests in this whole run:', difyStart.length, '(must be 0: nothing was confirmed)');
  fs.writeFileSync(`${OUT}/controls-net.json`, JSON.stringify({ chat, confirms, difyStart }, null, 2));
  await browser.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
