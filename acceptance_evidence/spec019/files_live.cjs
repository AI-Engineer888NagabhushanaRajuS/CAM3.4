// Live proof (SPEC-023): files attached in the chat are routed by rules, roles on chips, customer/project buttons,
// the pre-flight fix dialog with automatic download.   usage: node files_live.cjs dump | scrub | bad [w]
const { createRequire } = require('module');
const fs = require('fs'); const path = require('path'); const os = require('os');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/files';
fs.mkdirSync(OUT, { recursive: true });
const IN = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/test_inputs';
const DL = 'C:/Users/ADMIN/Downloads';
const FIX = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/fixtures';
const mode = process.argv[2] || 'dump'; const width = Number(process.argv[3] || 1440);
const DUMP = ['QCAD - Download.pdf', 'SRIM_RFQ_Automation_Quote_Redesigned.xlsx', 'Triode_Master_PCBA_Pricing_Reference.pdf', 'Master Capture Checklists (2).pdf',
  'WORK_REPORT.md', 'ISATVON 1.4 for Skill Generation.docx', 'Gerber_Files_1_pcb_info.pdf', 'Master Capture Checklists - Capture Checklist.csv'].map((n) => `${DL}/${n}`);
const files = mode === 'dump' ? DUMP : mode === 'scrub' ? [...DUMP.slice(0, 5), `${IN}/Centum_Scrub_BOM.xlsx`] : [...DUMP.slice(0, 3), `${FIX}/Centum_Scrub_BOM_bad.xlsx`];

(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const ctx = await b.newContext({ viewport: { width, height: width < 500 ? 844 : 900 }, acceptDownloads: true });
  const p = await ctx.newPage();
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  const chat = []; p.on('response', async (r) => { if (/\/api\/chat$/.test(r.url()) && r.request().method() === 'POST') { let body = null; try { body = await r.json(); } catch {} chat.push({ body }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  const send = async (text) => {
    const n = chat.length; await p.fill('[data-testid="task-input-textarea"]', text); await p.click('[data-testid="task-input-submit"]');
    const t1 = Date.now(); while (chat.length === n && Date.now() - t1 < 90000) await p.waitForTimeout(300); await p.waitForTimeout(900); return chat[chat.length - 1]?.body;
  };
  const short = (s) => (s || '').replace(/\s+/g, ' ').slice(0, 520);

  // attach through the assistant: both engines, then the files become chips
  await p.setInputFiles('[data-testid="assistant-file-input"]', files);
  const dlg = p.getByRole('dialog'); await dlg.waitFor({ timeout: 20000 });
  await p.waitForSelector('.uppy-Dashboard', { timeout: 20000 }); await p.waitForTimeout(1200);
  await dlg.getByRole('button', { name: /^Scan \d+ files?$/ }).click();
  const t0 = Date.now(); while (Date.now() - t0 < 180000 && !(await dlg.getByText('Scan complete').count())) await p.waitForTimeout(300);
  await p.waitForTimeout(800);
  console.log('readiness:', short(await dlg.getByTestId('intake-readiness').innerText().catch(() => '(none)')));
  console.log('fix button in dialog:', await dlg.getByRole('button', { name: /^Fix \d+ cells? in/ }).count());
  await p.screenshot({ path: `${OUT}/${mode}-01-scan-result-${width}.png` });
  await dlg.getByRole('button', { name: 'Done' }).click(); await p.waitForTimeout(1200);
  const chips = await p.getByTestId('file-role').allInnerTexts();
  console.log('chips with role:', JSON.stringify(chips), '| more button:', await p.getByRole('button', { name: /^\+\d+ more$/ }).count());
  await p.screenshot({ path: `${OUT}/${mode}-02-chips-${width}.png` });

  // "can u process this files": the model must not be asked
  let r = await send('can u process this files');
  console.log('REPLY 1:', short(r?.message), '| model:', r?.model, '| ui:', r?.ui?.type);
  const lastMsg = p.getByTestId('assistant-messages');
  console.log('newest reply fully inside the message area:', await p.evaluate(() => { const box = document.querySelector('[data-testid="assistant-messages"]'); const m = box?.querySelectorAll('[role="log"] > *'); const last = m && m[m.length - 1]; if (!box || !last) return null; const a = box.getBoundingClientRect(), c = last.getBoundingClientRect(); return c.bottom <= a.bottom + 2 && c.top >= a.top - 2; }));
  await p.screenshot({ path: `${OUT}/${mode}-03-reply-${width}.png` });

  if (mode === 'scrub' && r?.ui?.type === 'disambiguate') {
    console.log('buttons:', JSON.stringify(r.ui.options.map((o) => [o.label, o.send])));
    await p.getByRole('button', { name: r.ui.options[0].label, exact: true }).last().click();
    const n = chat.length; const t1 = Date.now(); while (chat.length === n && Date.now() - t1 < 60000) await p.waitForTimeout(300); await p.waitForTimeout(900);
    r = chat[chat.length - 1].body;
    console.log('REPLY 2:', short(r?.message), '| ui:', r?.ui?.type, JSON.stringify((r?.ui?.options || []).map((o) => o.label)));
    if (r?.ui?.type === 'disambiguate') {
      await p.getByRole('button', { name: r.ui.options[0].label, exact: true }).last().click();
      const n2 = chat.length; const t2 = Date.now(); while (chat.length === n2 && Date.now() - t2 < 60000) await p.waitForTimeout(300); await p.waitForTimeout(900);
      r = chat[chat.length - 1].body;
      console.log('REPLY 3:', short(r?.message), '| ui:', r?.ui?.type);
      console.log('card params files:', JSON.stringify((r?.ui?.params?.files || []).map((f) => [f.role, f.name])), '| customer/project:', JSON.stringify([r?.ui?.params?.customer?.name, r?.ui?.params?.project?.name]));
    }
    await p.screenshot({ path: `${OUT}/${mode}-04-card-${width}.png` });
  }

  if (mode === 'bad' && r?.ui?.type === 'fix_input') {
    console.log('fix_input directive:', JSON.stringify(r.ui));
    await p.getByRole('button', { name: /^Fix \d+ cells? in/ }).last().click();
    const fd = p.getByRole('dialog'); await fd.getByTestId('fix-row').first().waitFor({ timeout: 20000 });
    console.log('flagged rows shown:', await fd.getByTestId('fix-row').count(), '|', JSON.stringify((await fd.getByTestId('fix-row').allInnerTexts()).map((x) => x.replace(/\s+/g, ' ').slice(0, 110))));
    console.log('summary:', await fd.getByTestId('fix-summary').innerText());
    await p.screenshot({ path: `${OUT}/${mode}-05-fix-dialog-${width}.png` });
    // type the corrections: quantity text -> 2, #REF! -> 3, CPN -> MB_Cover_X, Settings B2 -> 1500
    const boxes = fd.locator('[data-testid="fix-row"] input');
    const labels = []; for (let i = 0; i < await boxes.count(); i++) labels.push(await boxes.nth(i).getAttribute('aria-label'));
    console.log('boxes:', JSON.stringify(labels));
    const give = { 'SCRUB BOM I5': '2', 'SCRUB BOM I6': '3', 'SCRUB BOM D7': 'MB_Cover_X', 'Settings B2': '1500' };
    for (let i = 0; i < labels.length; i++) { const key = Object.keys(give).find((k) => labels[i].endsWith(k)); if (key) await boxes.nth(i).fill(give[key]); }
    const dl = p.waitForEvent('download', { timeout: 60000 });
    await fd.getByRole('button', { name: /^Save \d+ corrections? and check again$/ }).click();
    const d = await dl; const saved = path.join(OUT, d.suggestedFilename()); await d.saveAs(saved);
    console.log('DOWNLOADED:', d.suggestedFilename(), '| bytes:', fs.statSync(saved).size);
    await fd.getByTestId('fix-saved').waitFor({ timeout: 20000 });
    console.log('saved panel:', short(await fd.getByTestId('fix-saved').innerText()));
    await p.screenshot({ path: `${OUT}/${mode}-06-fixed-${width}.png` });
    const n = chat.length; await fd.getByRole('button', { name: 'Continue with this file' }).click();
    const t1 = Date.now(); while (chat.length === n && Date.now() - t1 < 60000) await p.waitForTimeout(300); await p.waitForTimeout(900);
    r = chat[chat.length - 1].body;
    console.log('AFTER FIX:', short(r?.message), '| ui:', r?.ui?.type, JSON.stringify(r?.ui?.options?.map((o) => o.label) || null));
    await p.screenshot({ path: `${OUT}/${mode}-07-after-fix-${width}.png` });
  }
  console.log('page errors:', JSON.stringify(errs));
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
