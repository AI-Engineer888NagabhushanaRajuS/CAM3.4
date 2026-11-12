// Live proof: after an upload, the LEFT pane follows the run by itself (no manual click). Real Chrome.
// Records which stage is open (aria-expanded) and each stage's status every 5 s while the BOM run goes on, plus the right pane's log length.
// usage: node follow_upload_live.cjs [bomPath] [volumePath]
const { createRequire } = require('module');
const fs = require('fs');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const DIR = 'C:/Users/ADMIN/Documents/CAM input files/UPLOAD THESE 3 (BOM, Volume, QuoteWin)';
const BOM = process.argv[2] || `${DIR}/Centum_Scrub_BOM.xlsx`, VOL = process.argv[3] || `${DIR}/Volume_File.xlsx`;
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/follow-upload'; fs.mkdirSync(OUT, { recursive: true });
const pane = (p) => p.evaluate(() => [...document.querySelectorAll('[role="tree"] > div')].map((d) => {
  const b = d.querySelector('button[aria-label]');
  return { stage: b?.getAttribute('aria-label'), open: d.querySelector('button[aria-expanded="true"]') !== null, status: b?.querySelector('span span:nth-child(2)')?.textContent };
}));
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })).newPage();
  const seen = new Set();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(2500);
  await p.getByRole('button', { name: 'Create RFQ', exact: true }).first().click(); await p.waitForTimeout(2500);
  for (const id of ['rfq-execution-customer', 'rfq-execution-project']) {
    await p.getByTestId(id).click(); await p.waitForTimeout(800);
    const opt = p.locator('[role="option"], [data-testid^="' + id + '-option"]').first();
    if (await opt.count()) await opt.click();
    await p.waitForTimeout(800);
  }
  const rfqId = await p.getByPlaceholder('e.g. RFQ-000001').inputValue();
  console.log('RFQ', rfqId);
  await p.locator('input[type="file"][multiple]').first().setInputFiles([BOM, VOL]);
  const scanDialog = p.locator('[role="dialog"]').filter({ hasText: 'Repel Shield' });
  await scanDialog.waitFor({ timeout: 15000 });
  await scanDialog.getByRole('button', { name: /^Scan/ }).click();
  await scanDialog.getByTestId('use-scanned-files').waitFor({ timeout: 120000 });
  await scanDialog.getByTestId('use-scanned-files').click();
  await p.waitForTimeout(800);
  await p.getByRole('button', { name: 'Create RFQ' }).last().click();
  const started = Date.now();
  let last = '';
  while (Date.now() - started < 240000) {
    await p.waitForTimeout(5000);
    const rows = await pane(p);
    const openNow = rows.find((r) => r.open)?.stage ?? '(none open)';
    const line = `${Math.round((Date.now() - started) / 1000)}s open=${openNow} | ` + rows.map((r) => `${r.stage}:${r.status}`).join(' ; ');
    if (line !== last) { console.log(line.slice(0, 600)); last = line; }
    if (rows.every((r) => !/Running/.test(r.status || '')) && Date.now() - started > 60000) break;
  }
  await p.screenshot({ path: `${OUT}/left-pane-paused.png` });
  // Phase 2 (--qw=<QuoteWin file>): the app's own "Upload QuoteWin" button, then the left pane must move on by itself.
  const qw = (process.argv.find((a) => a.startsWith('--qw=')) || '').slice(5);
  if (qw) {
    const upBtn = p.getByRole('button', { name: /Upload QuoteWin/i });
    await upBtn.waitFor({ timeout: 60000 });
    await upBtn.click(); await p.waitForTimeout(1500);
    const modal = p.locator('[role="dialog"]').filter({ hasText: 'Upload QuoteWin' });
    await modal.waitFor({ timeout: 15000 });
    await modal.locator('input[type="file"]').first().setInputFiles(qw);
    await p.getByRole('button', { name: /Upload & Proceed/i }).click();
    console.log('QuoteWin uploaded', new Date().toISOString());
    const phase2 = Date.now();
    let last2 = '';
    while (Date.now() - phase2 < 600000) {
      await p.waitForTimeout(5000);
      const rows = await pane(p);
      const openNow = rows.find((r) => r.open)?.stage ?? '(none open)';
      const line2 = `${Math.round((Date.now() - phase2) / 1000)}s open=${openNow} | ` + rows.map((r) => `${r.stage}:${r.status}`).join(' ; ');
      if (line2 !== last2) { console.log('P2 ' + line2.slice(0, 600)); last2 = line2; }
      if (rows.every((r) => !/Running|Needs your upload/.test(r.status || '')) && Date.now() - phase2 > 60000) break;
    }
    await p.screenshot({ path: `${OUT}/left-pane-after-quotewin.png` });
  }
  await p.screenshot({ path: `${OUT}/left-pane-follow.png` });
  await b.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
