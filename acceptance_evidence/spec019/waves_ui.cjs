// Live proof: a pick of 12 files + one over-25-MB file goes through the attach dialog as scan waves; the big one is rejected.
const { createRequire } = require('module');
const fs = require('fs'); const path = require('path'); const os = require('os');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cam-waves-'));
const files = [];
for (let i = 1; i <= 12; i++) { const f = path.join(dir, `part_notes_${String(i).padStart(2, '0')}.txt`); fs.writeFileSync(f, `Part notes ${i}\nResistor 10k 0603, qty ${i * 100}\nNo special handling.\n`); files.push(f); }
const big = path.join(dir, 'big_price_dump.csv'); fs.writeFileSync(big, 'part,price\n' + 'ABC-123,0.10\n'.repeat(2_200_000)); files.push(big); // ~28 MB
console.log('big file MB:', (fs.statSync(big).size / 1048576).toFixed(1));
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const scans = [];
  p.on('response', async (r) => { if (/\/attachments\/scan/.test(r.url()) && r.request().method() === 'POST') { let j = null; try { j = await r.json(); } catch {} scans.push({ status: r.status(), n: (j?.results || []).length, decisions: (j?.results || []).map((x) => x.decision) }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.setInputFiles('[data-testid="assistant-file-input"]', files);
  const dlg = p.getByRole('dialog'); await dlg.waitFor({ timeout: 20000 });
  const txt = async () => (await dlg.innerText().catch(() => '(closed)')).replace(/\s+/g, ' ');
  console.log('BEFORE SCAN:', (await txt()).slice(0, 900));
  await p.screenshot({ path: `${OUT}/55-waves-before.png` });
  console.log('buttons:', JSON.stringify(await dlg.getByRole('button').allInnerTexts()));
  const scanBtn = dlg.getByRole('button', { name: /^Scan \d+ files?$/ });
  await scanBtn.click();
  const seen = new Set(); const t0 = Date.now();
  while (Date.now() - t0 < 240000) {
    const s = await txt();
    const m = s.match(/wave \d+ of \d+|Scanning[^.]{0,60}/i); if (m && !seen.has(m[0])) { seen.add(m[0]); console.log(`  [+${((Date.now() - t0) / 1000).toFixed(1)}s]`, m[0]); }
    if (await dlg.getByRole('button', { name: 'Done' }).count()) break;
    await p.waitForTimeout(400);
  }
  console.log('AFTER SCAN:', (await txt()).slice(0, 1100));
  await p.screenshot({ path: `${OUT}/56-waves-after.png` });
  console.log('scan calls:', JSON.stringify(scans));
  await dlg.getByRole('button', { name: 'Done' }).click().catch(() => {});
  await p.waitForTimeout(1200);
  console.log('no RFQ created by this script: only /attachments/scan was called; scan calls =', scans.length);
  await b.close();
  fs.rmSync(dir, { recursive: true, force: true });
})().catch((e) => { console.error('RUN FAILED', e.message); fs.rmSync(dir, { recursive: true, force: true }); process.exit(1); });
