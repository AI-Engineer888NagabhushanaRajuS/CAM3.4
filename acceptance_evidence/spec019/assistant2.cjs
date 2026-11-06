const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const fs = require('fs');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const chat = []; const confirms = []; const startReq = [];
  p.on('request', (r) => { if (/\/exports|edit-and-regenerate|dify\/start/.test(r.url()) && r.method() !== 'GET') startReq.push(r.url()); });
  p.on('response', async (r) => {
    if (/\/api\/chat$/.test(r.url()) && r.request().method() === 'POST') { let body = null; try { body = await r.json(); } catch {} chat.push({ req: JSON.parse(r.request().postData() || '{}'), body }); }
    if (/\/api\/chat\/actions\/confirm/.test(r.url())) { let body = null; try { body = await r.json(); } catch {} confirms.push(body); }
  });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  const ask = async (text, ms = 90000) => {
    const n = chat.length;
    await p.fill('[data-testid="task-input-textarea"]', text); await p.click('[data-testid="task-input-submit"]');
    const t0 = Date.now(); while (chat.length === n && Date.now() - t0 < ms) await p.waitForTimeout(400);
    await p.waitForTimeout(900); return { ms: Date.now() - t0, e: chat[chat.length - 1] };
  };
  const brief = (r) => `ms=${r.ms} model=${r.e?.body?.model} ui=${r.e?.body?.ui?.type}${r.e?.body?.ui?.action ? '/' + r.e.body.ui.action : ''}`;

  let r = await ask('open the input standardization manifest');
  console.log('1 manifest:', brief(r), '|', (r.e?.body?.message || '').slice(0, 140), '| path:', r.e?.body?.ui?.path);
  const link = p.getByRole('link', { name: /manifest/i });
  console.log('1 link in bubble:', await link.count(), (await link.first().getAttribute('href').catch(() => null)));
  await p.screenshot({ path: `${OUT}/31-open-manifest.png` });

  r = await ask('open the sales quote skill');
  console.log('2 manifest by name:', brief(r), '| path:', r.e?.body?.ui?.path);
  r = await ask('open the weather manifest');
  console.log('3 unknown name:', brief(r), '|', (r.e?.body?.message || '').slice(0, 200).replace(/\n/g, ' | '));

  r = await ask('set the unit price of part 2N7002BK,215 to 0.1222 for RFQ-CENTUM-PROOF-24');
  console.log('4 edit card:', brief(r), '|', (r.e?.body?.message || '').slice(0, 260).replace(/\n/g, ' | '));
  console.log('4 params:', JSON.stringify(r.e?.body?.ui?.params || null).slice(0, 400));
  await p.screenshot({ path: `${OUT}/32-edit-card.png` });
  if (r.e?.body?.ui?.type === 'confirm_action') {
    const cp = p.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 30000 });
    await p.getByRole('button', { name: /^Cancel$/ }).last().click(); const resp = await cp; const body = await resp.json();
    console.log('4 cancel ->', resp.status(), body.ok, body.message);
  }
  r = await ask('set the foo of part 2N7002BK,215 to 3 for RFQ-CENTUM-PROOF-24');
  console.log('5 unknown field:', brief(r), '|', (r.e?.body?.message || '').slice(0, 220).replace(/\n/g, ' | '));
  r = await ask('set the unit price of part 2N7002BK,215 to abc for RFQ-CENTUM-PROOF-24');
  console.log('6 bad value:', brief(r), '|', (r.e?.body?.message || '').slice(0, 160));
  console.log('write requests (edit/regenerate/start) during this run:', startReq.length, '(must be 0: only Cancel was pressed)');
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
