// Live proof (SPEC-022): Uppy intake dashboard, animated scan, detected roles, Create RFQ through the assistant.
// usage: node intake_live.cjs scan4 [dark] [w]   |   node intake_live.cjs create1
const { createRequire } = require('module');
const fs = require('fs'); const path = require('path'); const os = require('os');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/intake';
fs.mkdirSync(OUT, { recursive: true });
const IN = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/test_inputs';
const mode = process.argv[2] || 'scan4'; const dark = process.argv[3] === 'dark'; const width = Number(process.argv[4] || 1440);
const tag = `${mode}-${dark ? 'dark' : 'light'}-${width}`;
(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cam-intake-'));
  fs.writeFileSync(path.join(tmp, 'setup.exe'), 'this is only text, named like a program, to show a rejection');
  const files = mode === 'scan4'
    ? [`${IN}/Centum_Scrub_BOM.xlsx`, `${IN}/Volume_File.xlsx`, `${IN}/QuoteWin_File.xlsx`, `${IN}/Centum_BOM.xlsx`, path.join(tmp, 'setup.exe')]
    : [`${IN}/Centum_Scrub_BOM.xlsx`];
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width, height: width < 500 ? 844 : 900 } })).newPage();
  const chat = []; p.on('response', async (r) => { if (/\/api\/chat$/.test(r.url()) && r.request().method() === 'POST') { let body = null; try { body = await r.json(); } catch {} chat.push({ body }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  if (dark) await p.evaluate(() => document.documentElement.classList.add('dark'));
  await p.setInputFiles('[data-testid="assistant-file-input"]', files);
  const dlg = p.getByRole('dialog'); await dlg.waitFor({ timeout: 20000 });
  await p.waitForSelector('.uppy-Dashboard', { timeout: 20000 }); await p.waitForTimeout(1500);
  if (dark) await p.evaluate(() => document.documentElement.classList.add('dark'));
  console.log('tiles:', await p.locator('.uppy-Dashboard-Item').count(), '| names:', JSON.stringify(await p.locator('.uppy-Dashboard-Item-name').allInnerTexts()));
  console.log('footer:', (await dlg.innerText()).replace(/\s+/g, ' ').match(/\d+ selected[^R]{0,60}(Rejected \(\d+\))?/)?.[0]);
  await p.screenshot({ path: `${OUT}/01-dashboard-${tag}.png` });

  const scan = dlg.getByRole('button', { name: /^Scan \d+ files?$/ });
  await scan.click();
  let shots = 0;
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) {
    if (await dlg.getByText('Scan complete').count()) break;
    if (shots < 3) { await p.screenshot({ path: `${OUT}/02-scanning-${shots}-${tag}.png` }); shots++; }
    await p.waitForTimeout(250);
  }
  await p.waitForTimeout(1500);
  console.log('scanning frames captured:', shots, '| scan took ms:', Date.now() - t0);
  const text = (await dlg.innerText()).replace(/\s+/g, ' ');
  console.log('detected:', JSON.stringify(text.match(/Detected: [^R]{0,45}?(?= BuLL|\s{2}|$)/g) || []));
  console.log('RESULT TEXT:', text.slice(text.indexOf('Scan complete'), text.indexOf('Scan complete') + 1700));
  await p.screenshot({ path: `${OUT}/03-results-${tag}.png` });
  console.log('create button:', await dlg.getByRole('button', { name: 'Create RFQ from these files' }).count());

  if (mode === 'create1') {
    await dlg.getByRole('button', { name: 'Create RFQ from these files' }).click();
    const wait = async (n) => { const t1 = Date.now(); while (chat.length === n && Date.now() - t1 < 90000) await p.waitForTimeout(400); await p.waitForTimeout(900); return chat[chat.length - 1]; };
    let r = await wait(0);
    console.log('assistant 1:', (r.body?.message || '').replace(/\n/g, ' | ').slice(0, 300));
    const n = chat.length; await p.fill('[data-testid="task-input-textarea"]', 'create an RFQ from these files for customer 000, project UBR-TEST-3.4'); await p.click('[data-testid="task-input-submit"]');
    r = await wait(n);
    console.log('assistant 2:', r.body?.ui?.type, '|', (r.body?.message || '').replace(/\n/g, ' | ').slice(0, 400));
    console.log('params:', JSON.stringify(r.body?.ui?.params || null).slice(0, 500));
    await p.screenshot({ path: `${OUT}/04-confirm-card-${tag}.png` });
    if (r.body?.ui?.type === 'confirm_action') {
      const cp = p.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 240000 });
      await p.getByRole('button', { name: /^Confirm/ }).last().click();
      const body = await (await cp).json();
      console.log('CONFIRM ->', body.ok, '| rfq:', body.rfqId, '|', (body.message || '').replace(/\n/g, ' | ').slice(0, 300));
      console.log('steps:', JSON.stringify(body.steps));
      fs.writeFileSync(`${OUT}/created-rfq.txt`, String(body.rfqId || ''));
    }
  }
  await b.close(); fs.rmSync(tmp, { recursive: true, force: true });
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
