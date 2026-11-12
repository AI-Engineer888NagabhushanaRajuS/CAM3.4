// Live proof (SPEC-023 item 4, closed here): a run the user is watching finishes -> the report workbook is saved by itself, once.
// Real Chrome on :5181. The finishing event is posted to the daemon's own internal route, the same call the pipeline router makes
// (fastapi_router.notify_skill_progress); RFQ-000015 already has a real exported workbook (716 KB) from an earlier run.
const { createRequire } = require('module');
const fs = require('fs');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/autodownload'; fs.mkdirSync(OUT, { recursive: true });
const RFQ = process.argv[2] || 'RFQ-000015';
const emit = (macro, status) => fetch('http://localhost:9334/api/internal/emit-skill-progress', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ rfqId: RFQ, skillCode: 'centum_reporting__export_reports', skillName: 'Export reports', macroCategory: macro, macroCategoryName: 'REPORTING', stepStatus: status, updatedAt: new Date().toISOString() }) }).then((r) => r.status);
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const p = await ctx.newPage();
  const downloads = []; p.on('download', (d) => downloads.push(d));
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(2000);
  console.log('switch value:', await p.evaluate(() => localStorage.getItem('cam-auto-download')), '(null = default on)');
  const search = p.getByPlaceholder(/Search by RFQ ID/i); await search.fill(RFQ); await p.waitForTimeout(2500);
  const opt = p.getByText(RFQ, { exact: true }).first(); if (await opt.count()) await opt.click();
  await p.waitForTimeout(4000); // the page now watches this RFQ (its progress stream is open)
  console.log('1 before the finishing event, downloads:', downloads.length);
  console.log('2 event "running" posted ->', await emit(9, 'running')); await p.waitForTimeout(3000);
  console.log('  downloads after "running":', downloads.length, '(none expected)');
  console.log('3 event "completed" posted ->', await emit(9, 'completed'));
  const d = await Promise.race([p.waitForEvent('download', { timeout: 20000 }).catch(() => null), p.waitForTimeout(20000).then(() => null)]);
  if (d) { const to = `${OUT}/${d.suggestedFilename()}`; await d.saveAs(to); console.log('  saved by the page:', d.suggestedFilename(), fs.statSync(to).size, 'bytes'); }
  else console.log('  NO DOWNLOAD (not proven)');
  await p.screenshot({ path: `${OUT}/01-after-completed.png` });
  console.log('4 second "completed" event ->', await emit(9, 'completed')); await p.waitForTimeout(5000);
  console.log('  total downloads:', downloads.length, '(1 expected: once per RFQ)');
  await b.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
