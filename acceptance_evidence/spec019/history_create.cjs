// Live proof (SPEC-021): create an RFQ from the CORRECT files through the assistant, then watch its run in History.
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
const dir = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/test_inputs';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const chat = [];
  p.on('response', async (r) => { if (/\/api\/chat$/.test(r.url()) && r.request().method() === 'POST') { let body = null; try { body = await r.json(); } catch {} chat.push({ body }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  const ask = async (text, ms = 90000) => { const n = chat.length; await p.fill('[data-testid="task-input-textarea"]', text); await p.click('[data-testid="task-input-submit"]'); const t0 = Date.now(); while (chat.length === n && Date.now() - t0 < ms) await p.waitForTimeout(400); await p.waitForTimeout(900); return chat[chat.length - 1]; };

  await p.setInputFiles('[data-testid="assistant-file-input"]', [`${dir}/Centum_Scrub_BOM.xlsx`, `${dir}/Volume_File.xlsx`]);
  const dlg = p.getByRole('dialog'); await dlg.waitFor({ timeout: 20000 });
  await dlg.getByRole('button', { name: /^Scan \d+ files?$/ }).click();
  await dlg.getByRole('button', { name: 'Done' }).waitFor({ timeout: 120000 }); await dlg.getByRole('button', { name: 'Done' }).click();
  const r = await ask('create an RFQ from these files for customer 000, project UBR-TEST-3.4');
  console.log('card:', r.body?.ui?.type, '|', (r.body?.message || '').replace(/\n/g, ' | ').slice(0, 260));
  const cp = p.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 240000 });
  await p.getByRole('button', { name: /^Confirm/ }).last().click();
  const body = await (await cp).json();
  console.log('Confirm ->', body.ok, '| rfq:', body.rfqId, '|', (body.message || '').replace(/\n/g, ' | ').slice(0, 260));
  require('fs').writeFileSync(`${OUT}/63-created-rfq.txt`, String(body.rfqId || ''));
  await p.waitForTimeout(2500);

  // open it and watch History
  const rfq = body.rfqId;
  await p.fill('[data-testid="task-input-textarea"]', `open ${rfq}`); await p.click('[data-testid="task-input-submit"]'); await p.waitForTimeout(6000);
  await p.getByRole('button', { name: new RegExp(`Open ${rfq}`) }).first().click(); await p.waitForTimeout(3500);
  await p.getByRole('button', { name: 'History', exact: true }).click(); await p.getByTestId('run-history').waitFor({ timeout: 20000 });
  for (let i = 0; i < 8; i++) {
    await p.waitForTimeout(5500);
    const rows = await p.getByTestId('run-row').allInnerTexts();
    console.log(`[+${(i + 1) * 5.5}s]`, rows.length, 'runs |', (rows[0] || '').replace(/\s+/g, ' ').slice(0, 230));
    if (rows[0] && !/Running/.test(rows[0])) break;
  }
  await p.screenshot({ path: `${OUT}/64-new-rfq-history.png` });
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
