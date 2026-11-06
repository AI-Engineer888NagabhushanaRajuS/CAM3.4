const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
const RFQ = 'RFQ-CENTUM-PROOF-24';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })).newPage();
  const chat = []; const confirms = []; const sse = [];
  p.on('response', async (r) => {
    if (/\/api\/chat$/.test(r.url()) && r.request().method() === 'POST') { let body = null; try { body = await r.json(); } catch {} chat.push({ body }); }
    if (/\/api\/chat\/actions\/confirm/.test(r.url())) { let body = null; try { body = await r.json(); } catch {} confirms.push(body); }
  });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  const body = async () => (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  const ask = async (text, ms = 90000) => { const n = chat.length; await p.fill('[data-testid="task-input-textarea"]', text); await p.click('[data-testid="task-input-submit"]'); const t0 = Date.now(); while (chat.length === n && Date.now() - t0 < ms) await p.waitForTimeout(400); await p.waitForTimeout(900); return chat[chat.length - 1]; };

  let r = await ask(`open ${RFQ}`);
  await p.getByRole('button', { name: new RegExp(`Open ${RFQ}`) }).first().click(); await p.waitForTimeout(3500);

  // the exact case: volume 1 only
  r = await ask('set the unit price of part 2N7002BK,215 volume 1 to 0.102 for RFQ-CENTUM-PROOF-24');
  console.log('B volume-1 card:', r.body?.ui?.type, '|', (r.body?.message || '').slice(0, 300).replace(/\n/g, ' | '));
  console.log('B params:', JSON.stringify(r.body?.ui?.params || null).slice(0, 360));
  await p.screenshot({ path: `${OUT}/40-edit-card-volume1.png` });
  if (r.body?.ui?.type !== 'confirm_action') { await b.close(); return; }

  const cp = p.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 240000 });
  await p.getByRole('button', { name: /^Confirm/ }).last().click();
  // watch the right pane timeline while the regeneration runs
  const seen = new Set(); const t0 = Date.now(); let resp = null;
  cp.then((x) => { resp = x; });
  while (!resp && Date.now() - t0 < 240000) {
    const s = await body();
    for (const k of ['Value changed', 'value-changed', 'Regenerating', 'ready', 'changed cells', 'Versions']) if (new RegExp(k, 'i').test(s) && !seen.has(k)) { seen.add(k); console.log(`  [+${((Date.now() - t0) / 1000).toFixed(1)}s] pane shows: ${k}`); }
    await p.waitForTimeout(500);
  }
  const rr = await (await cp).json();
  console.log('C confirm ->', rr.ok, '|', (rr.message || '').slice(0, 300).replace(/\n/g, ' | '));
  console.log('C steps:', JSON.stringify(rr.steps || []).slice(0, 300));
  await p.waitForTimeout(2500);
  const s = await body();
  const pane = await p.evaluate(() => { const r = [...document.querySelectorAll('[aria-live=polite]')].map((e) => e.textContent.trim().replace(/\s+/g, ' ').slice(0, 400)); return r; });
  console.log('D aria-live regions (timeline):', JSON.stringify(pane));
  console.log('D right pane after:', (s.match(/Changes[^]{0,10}/) ? '' : ''), /changed cells/i.test(s) ? (s.match(/[^.]{0,60}changed cells[^.]{0,80}/i) || [])[0] : '(no "changed cells" text)');
  console.log('D Versions list present:', /Versions/i.test(s));
  await p.screenshot({ path: `${OUT}/42-panel-visible.png` });
  // the reply carries a download button for the new version
  const dl = p.getByRole('button', { name: /Download reports/i });
  if (await dl.count()) { const [d] = await Promise.all([p.waitForEvent('download', { timeout: 60000 }).catch(() => null), dl.last().click()]); console.log('E download:', d ? d.suggestedFilename() : 'none'); }
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
