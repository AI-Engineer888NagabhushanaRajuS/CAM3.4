// Live proof: the all-volumes edit card. Cancel changes nothing; Confirm regenerates; then revert both volumes.
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
const RFQ = 'RFQ-CENTUM-PROOF-24';
const PART = '2N7002BK,215';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const chat = []; const confirms = [];
  p.on('response', async (r) => {
    if (/\/api\/chat$/.test(r.url()) && r.request().method() === 'POST') { let body = null; try { body = await r.json(); } catch {} chat.push({ body }); }
    if (/\/api\/chat\/actions\/confirm/.test(r.url())) { let body = null; try { body = await r.json(); } catch {} confirms.push({ status: r.status(), body }); }
  });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  const body = async () => (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  const ask = async (text, ms = 90000) => { const n = chat.length; await p.fill('[data-testid="task-input-textarea"]', text); await p.click('[data-testid="task-input-submit"]'); const t0 = Date.now(); while (chat.length === n && Date.now() - t0 < ms) await p.waitForTimeout(400); await p.waitForTimeout(900); return chat[chat.length - 1]; };
  const cancelIfCard = async () => { const c = p.getByRole('button', { name: /^Cancel/ }); if (await c.count()) { await c.last().click(); await p.waitForTimeout(800); } };
  const versions = async () => { const v = p.getByText(/^Versions/).first(); if (await v.count()) { await v.click().catch(() => {}); await p.waitForTimeout(600); } return ((await body()).match(/\.xlsx/g) || []).length; };

  let r = await ask(`open ${RFQ}`);
  await p.getByRole('button', { name: new RegExp(`Open ${RFQ}`) }).first().click(); await p.waitForTimeout(3500);
  const v0 = await versions(); console.log('versions listed before:', v0);

  if (!process.env.REVERT_ONLY) {
  // 1. all volumes, then CANCEL
  r = await ask(`set the unit price of part ${PART} to 0.2 for ${RFQ}`);
  console.log('card:', r.body?.ui?.type, '|', (r.body?.message || '').replace(/\n/g, ' | ').slice(0, 330));
  await p.screenshot({ path: `${OUT}/52-all-volumes-card.png` });
  const c0 = confirms.length;
  await p.getByRole('button', { name: /^Cancel/ }).last().click(); await p.waitForTimeout(1500);
  console.log('after Cancel: confirm calls made:', confirms.length - c0, '| card still shows Confirm button:', await p.getByRole('button', { name: /^Confirm/ }).count(), '| versions:', await versions());
  await p.screenshot({ path: `${OUT}/53-all-volumes-cancelled.png` });

  // 2. all volumes, CONFIRM
  r = await ask(`set the unit price of part ${PART} to 0.2 for ${RFQ}`);
  const cp = p.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 240000 });
  await p.getByRole('button', { name: /^Confirm/ }).last().click();
  const rr = await (await cp).json();
  console.log('Confirm ->', rr.ok, '|', (rr.message || '').replace(/\n/g, ' | ').slice(0, 330));
  await p.waitForTimeout(2500);
  console.log('versions after confirm:', await versions());
  await p.screenshot({ path: `${OUT}/54-all-volumes-confirmed.png` });

  // 3. what the DB holds now: the next card quotes the current values of every volume
  r = await ask(`set the unit price of part ${PART} to 0.2 for ${RFQ}`);
  console.log('current values per the card:', (r.body?.message || '').replace(/\n/g, ' | ').slice(0, 330));
  await p.getByRole('button', { name: /^Cancel/ }).last().click(); await p.waitForTimeout(800);

  }
  // 4. revert volume by volume to the original values (0.102 and 0.017)
  for (const [vol, val] of [[1, '0.102'], [2, '0.017']]) {
    r = await ask(`set the unit price of part ${PART} volume ${vol} to ${val} for ${RFQ}`);
    const cp2 = p.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 240000 });
    await p.getByRole('button', { name: /^Confirm/ }).last().click();
    const r2 = await (await cp2).json();
    console.log(`revert volume ${vol} ->`, r2.ok, (r2.message || '').replace(/\n/g, ' | ').slice(0, 160));
    await p.waitForTimeout(1500);
  }
  r = await ask(`set the unit price of part ${PART} to 0.2 for ${RFQ}`);
  console.log('values after revert per the card:', (r.body?.message || '').replace(/\n/g, ' | ').slice(0, 330));
  await p.getByRole('button', { name: /^Cancel/ }).last().click(); await p.waitForTimeout(800);
  console.log('versions at end:', await versions());
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
