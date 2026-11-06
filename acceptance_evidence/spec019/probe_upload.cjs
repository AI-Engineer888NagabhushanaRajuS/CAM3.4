const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.fill('[data-testid="task-input-textarea"]', 'open RFQ-000017'); await p.click('[data-testid="task-input-submit"]'); await p.waitForTimeout(6000);
  await p.getByRole('button', { name: /Open RFQ-000017/ }).first().click(); await p.waitForTimeout(3500);
  for (const name of ['Upload file', 'Create RFQ', 'Ingest BOM and Volume file']) { const e = p.getByText(name, { exact: true }).first(); if (await e.count()) { await e.click().catch(()=>{}); await p.waitForTimeout(1200); console.log('clicked', name, '| file inputs:', await p.locator('input[type=file]').count(), '| testids:', JSON.stringify(await p.locator('input[type=file]').evaluateAll(els => els.map(e => [e.getAttribute('data-testid'), e.accept, e.multiple])))); } }
  console.log((await p.locator('body').innerText()).replace(/\s+/g,' ').slice(0,900));
  await p.screenshot({ path: 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/62-upload-probe.png' });
  await b.close();
})();
