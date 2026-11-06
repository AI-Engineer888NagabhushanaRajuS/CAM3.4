// Live proof (SPEC-021): the History tab of an RFQ whose runs failed on wrong input.
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
const RFQ = process.argv[2] || 'RFQ-000017';
const TAG = process.argv[3] || 'a';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const runs = [];
  p.on('response', async (r) => { if (/\/api\/rfq\/[^/]+\/runs$/.test(r.url())) { let j = null; try { j = await r.json(); } catch {} runs.push({ status: r.status(), j }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.fill('[data-testid="task-input-textarea"]', `open ${RFQ}`); await p.click('[data-testid="task-input-submit"]'); await p.waitForTimeout(6000);
  await p.getByRole('button', { name: new RegExp(`Open ${RFQ}`) }).first().click(); await p.waitForTimeout(3500);
  await p.screenshot({ path: `${OUT}/60-${TAG}-workflow-view.png` });
  await p.getByRole('button', { name: 'History', exact: true }).click();
  await p.getByTestId('run-history').waitFor({ timeout: 20000 }); await p.waitForTimeout(2500);
  const rows = await p.getByTestId('run-row').allInnerTexts();
  console.log(`${RFQ}: ${rows.length} runs`);
  rows.slice(0, 4).forEach((r, i) => console.log(`  [${i}]`, r.replace(/\s+/g, ' ').slice(0, 420)));
  console.log('run buttons:', await p.getByRole('button', { name: /Run again/ }).count());
  console.log('API status:', runs.map((r) => r.status), '| by:', JSON.stringify((runs.at(-1)?.j?.runs || []).map((x) => [x.status, x.started_by, x.duration_ms])).slice(0, 300));
  await p.screenshot({ path: `${OUT}/61-${TAG}-history.png` });
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
