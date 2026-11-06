// Live proof (SPEC-023): bad BOM -> Fix button in the INTAKE dialog (not the chat) -> corrected file downloaded -> Create RFQ from these files
// -> customer / project buttons -> card -> Confirm: the corrected file passes the upload gate and the run starts.
const { createRequire } = require('module');
const fs = require('fs'); const path = require('path');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/files'; fs.mkdirSync(OUT, { recursive: true });
const FIX = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/fixtures';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })).newPage();
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  const chat = []; p.on('response', async (r) => { if (/\/api\/chat$/.test(r.url()) && r.request().method() === 'POST') { let body = null; try { body = await r.json(); } catch {} chat.push({ body }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  const waitChat = async (n) => { const t1 = Date.now(); while (chat.length === n && Date.now() - t1 < 90000) await p.waitForTimeout(300); await p.waitForTimeout(900); return chat[chat.length - 1]?.body; };
  const short = (s) => (s || '').replace(/\s+/g, ' ').slice(0, 300);

  await p.setInputFiles('[data-testid="assistant-file-input"]', [`${FIX}/Centum_Scrub_BOM_bad.xlsx`]);
  const dlg = p.getByRole('dialog'); await dlg.waitFor({ timeout: 20000 });
  await p.waitForSelector('.uppy-Dashboard', { timeout: 20000 }); await p.waitForTimeout(1000);
  await dlg.getByRole('button', { name: /^Scan \d+ files?$/ }).click();
  const t0 = Date.now(); while (Date.now() - t0 < 180000 && !(await dlg.getByText('Scan complete').count())) await p.waitForTimeout(300);
  await p.waitForTimeout(800);
  console.log('readiness before:', short(await dlg.getByTestId('intake-readiness').innerText()), '| Create button:', await dlg.getByRole('button', { name: 'Create RFQ from these files' }).count());

  // the Fix button of the intake dialog (the nested dialog is the last one)
  await dlg.getByRole('button', { name: /^Fix \d+ cells? in/ }).click();
  const fd = p.getByRole('dialog').last(); await fd.getByTestId('fix-row').first().waitFor({ timeout: 20000 });
  const boxes = fd.locator('[data-testid="fix-row"] input'); const labels = [];
  for (let i = 0; i < await boxes.count(); i++) labels.push(await boxes.nth(i).getAttribute('aria-label'));
  const give = { 'SCRUB BOM I5': '2', 'SCRUB BOM I6': '3', 'SCRUB BOM D7': 'MB_Cover_X', 'Settings B2': '1500' };
  for (let i = 0; i < labels.length; i++) { const k = Object.keys(give).find((x) => labels[i].endsWith(x)); if (k) await boxes.nth(i).fill(give[k]); }
  const dl = p.waitForEvent('download', { timeout: 60000 });
  await fd.getByRole('button', { name: /^Save \d+ corrections? and check again$/ }).click();
  const d = await dl; const saved = path.join(OUT, 'confirm-' + d.suggestedFilename()); await d.saveAs(saved);
  console.log('DOWNLOADED:', d.suggestedFilename(), fs.statSync(saved).size, 'bytes');
  await fd.getByTestId('fix-saved').waitFor({ timeout: 20000 });
  await fd.getByRole('button', { name: 'Close' }).first().click(); await p.waitForTimeout(800);
  console.log('readiness after:', short(await dlg.getByTestId('intake-readiness').innerText()), '| Create button:', await dlg.getByRole('button', { name: 'Create RFQ from these files' }).count());
  await p.screenshot({ path: `${OUT}/confirm-01-intake-after-fix.png` });

  let n = chat.length;
  await dlg.getByRole('button', { name: 'Create RFQ from these files' }).click();
  let r = await waitChat(n);
  console.log('R1:', short(r?.message), '|', r?.ui?.type, JSON.stringify((r?.ui?.options || []).map((o) => o.label)));
  for (let step = 0; step < 2 && r?.ui?.type === 'disambiguate'; step++) {
    n = chat.length; await p.getByRole('button', { name: r.ui.options[0].label, exact: true }).last().click(); r = await waitChat(n);
    console.log('R' + (step + 2) + ':', short(r?.message), '|', r?.ui?.type);
  }
  console.log('card files:', JSON.stringify((r?.ui?.params?.files || []).map((f) => [f.role, f.name])), '| rfq:', r?.ui?.params?.rfqId);
  await p.screenshot({ path: `${OUT}/confirm-02-card.png` });
  if (r?.ui?.type === 'confirm_action') {
    const cp = p.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 240000 });
    await p.getByRole('button', { name: /^Confirm/ }).last().click();
    const body = await (await cp).json();
    console.log('CONFIRM ->', body.ok, '| rfq:', body.rfqId, '|', short(body.message));
    console.log('steps:', JSON.stringify(body.steps));
    fs.writeFileSync(`${OUT}/confirm-created-rfq.txt`, String(body.rfqId || ''));
    await p.waitForTimeout(2500);
    await p.screenshot({ path: `${OUT}/confirm-03-after-confirm.png` });
  }
  console.log('page errors:', JSON.stringify(errs));
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
