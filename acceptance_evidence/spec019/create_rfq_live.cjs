// Live proof: the real "Create RFQ & Upload BOM" card with the two files handed to the user (Scrub BOM + Volume).
// usage: node create_rfq_live.cjs [bomPath] [volumePath]
const { createRequire } = require('module');
const fs = require('fs');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const DIR = 'C:/Users/ADMIN/Documents/CAM input files/UPLOAD THESE 3 (BOM, Volume, QuoteWin)';
const BOM = process.argv[2] || `${DIR}/Centum_Scrub_BOM.xlsx`, VOL = process.argv[3] || `${DIR}/Volume_File.xlsx`;
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/create-rfq'; fs.mkdirSync(OUT, { recursive: true });
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })).newPage();
  const net = []; p.on('response', (r) => { const u = r.url(); if (/\/api\/rfq\/upload|\/api\/dify\/start|create-rfq|createRfq/i.test(u)) net.push(`${r.status()} ${r.request().method()} ${u.replace(/^https?:\/\/[^/]+/, '')}`); });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(2500);
  await p.getByRole('button', { name: 'Create RFQ', exact: true }).first().click(); await p.waitForTimeout(2500);
  for (const id of ['rfq-execution-customer', 'rfq-execution-project']) {
    await p.getByTestId(id).click(); await p.waitForTimeout(800);
    const opt = p.locator('[role="option"], [data-testid^="' + id + '-option"]').first();
    if (await opt.count()) await opt.click(); else console.log('no option for', id);
    await p.waitForTimeout(800);
  }
  const rfqId = await p.getByPlaceholder('e.g. RFQ-000001').inputValue();
  console.log('RFQ id suggested:', rfqId);
  // One drop area for all files: the Uppy dashboard shows the tiles, both engines scan them (animation), the files are sorted by role.
  const bomFiles = VOL === 'none' ? [BOM] : [BOM, VOL];
  await p.locator('input[type="file"][multiple]').first().setInputFiles(bomFiles);
  const scanDialog = p.locator('[role="dialog"]').filter({ hasText: 'Repel Shield' });   // its description stays through every phase (the title changes)
  await scanDialog.waitFor({ timeout: 15000 });
  await p.screenshot({ path: `${OUT}/01a-uppy-tiles.png` });
  await scanDialog.getByRole('button', { name: /^Scan/ }).click();
  await p.waitForTimeout(700);
  await p.screenshot({ path: `${OUT}/01b-scanning.png` });
  console.log('scanning text:', (await scanDialog.innerText()).replace(/\s+/g, ' ').match(/(Quarantining|Scanning)[^.]*/)?.[0]);
  await scanDialog.getByTestId('use-scanned-files').waitFor({ timeout: 120000 });
  console.log('scan result:', (await scanDialog.getByTestId('intake-readiness').innerText()).replace(/\s+/g, ' '));
  await p.screenshot({ path: `${OUT}/01c-scan-result.png` });
  await scanDialog.getByTestId('use-scanned-files').click();
  await p.waitForTimeout(800);
  await p.screenshot({ path: `${OUT}/01-filled.png` });
  const go = p.getByRole('button', { name: 'Create RFQ' }).last();
  console.log('Create RFQ enabled:', !(await go.isDisabled()));
  await go.click(); await p.waitForTimeout(9000);
  console.log('network:', JSON.stringify(net));
  const txt = (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  const i = txt.indexOf('Intake Progress');
  console.log('progress panel:', i >= 0 ? txt.slice(i, i + 400) : txt.slice(0, 300));
  await p.screenshot({ path: `${OUT}/02-after-create.png` });

  // Golden path (--qw=<QuoteWin file>): wait for the BOM step, upload the QuoteWin file when the panel offers it, wait for the export.
  const qw = (process.argv.find((a) => a.startsWith('--qw=')) || '').slice(5);
  if (qw) {
    const upBtn = p.getByRole('button', { name: /Upload QuoteWin/i });
    await upBtn.waitFor({ timeout: 600000 });
    console.log('BOM step done, QuoteWin upload offered');
    await upBtn.click(); await p.waitForTimeout(1500);
    const modal = p.locator('[role="dialog"]').filter({ hasText: 'Upload QuoteWin' });
    await modal.waitFor({ timeout: 15000 });
    // --wrongqw=<file of another BOM>: the app must refuse it with the numbers, before it can zero the whole report (RFQ-000024)
    const wrong = (process.argv.find((a) => a.startsWith('--wrongqw=')) || '').slice(10);
    if (wrong) {
      await modal.locator('input[type="file"]').first().setInputFiles(wrong);
      await p.getByRole('button', { name: /Upload & Proceed/i }).click(); await p.waitForTimeout(5000);
      console.log('WRONG QuoteWin ->', (await modal.innerText()).replace(/\s+/g, ' ').match(/This QuoteWin file[^.]*\.[^.]*\./)?.[0] || '(no refusal text: ' + (await modal.innerText()).replace(/\s+/g, ' ').slice(0, 200) + ')');
      await p.screenshot({ path: `${OUT}/03a-quotewin-refused.png` });
      await modal.getByRole('button', { name: /Cancel/i }).click(); await p.waitForTimeout(800);
      await upBtn.click(); await p.waitForTimeout(1500);
    }
    await modal.locator('input[type="file"]').first().setInputFiles(qw);   // the first zone is "QuoteWin File (required)"
    await p.screenshot({ path: `${OUT}/03-quotewin-modal.png` });
    const downloading = p.waitForEvent('download', { timeout: 900000 }).catch(() => null);   // the app's own auto-download when the run finishes
    await p.getByRole('button', { name: /Upload & Proceed/i }).click(); await p.waitForTimeout(4000);
    console.log('modal text after upload:', (await p.locator('[role="dialog"]').allInnerTexts()).join(' ').replace(/\s+/g, ' ').slice(0, 300) || '(closed)');
    const dl = await downloading;
    if (dl) { await dl.saveAs(`${OUT}/${rfqId}-report.xlsx`); console.log('report saved by the app:', dl.suggestedFilename(), fs.statSync(`${OUT}/${rfqId}-report.xlsx`).size, 'bytes'); } else console.log('NO DOWNLOAD within 15 min');
    await p.waitForTimeout(6000);
    const pane = await p.evaluate(() => [...document.querySelectorAll('[role="tree"] > div')].map((d) => { const s = d.querySelectorAll('button')[1]; return [s?.querySelector('span span:nth-child(1)')?.textContent, s?.querySelector('span span:nth-child(2)')?.textContent]; }));
    console.log('LEFT PANE:', JSON.stringify(pane));
    const text = (await p.locator('body').innerText()).replace(/\s+/g, ' ');
    console.log('DASHBOARD:', /Reports & Analytics/.test(text) ? text.slice(text.indexOf('Reports & Analytics'), text.indexOf('Reports & Analytics') + 700) : '(not on screen)');
    await p.screenshot({ path: `${OUT}/04-after-export.png`, fullPage: false });
  }
  await b.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
