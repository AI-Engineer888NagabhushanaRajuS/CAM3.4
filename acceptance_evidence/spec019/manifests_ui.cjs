const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errs = []; const puts = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 160)));
  p.on('response', async (r) => { if (/\/api\/manifests\/file/.test(r.url()) && r.request().method() === 'PUT') { let j = null; try { j = await r.json(); } catch {} const raw = j ? JSON.stringify(j).slice(0, 700) : ''; puts.push({ status: r.status(), j, raw }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.getByRole('radiogroup', { name: 'Model provider' }).waitFor({ timeout: 20000 });
  await p.getByRole('button', { name: /^Manifests$/ }).click();
  await p.waitForURL(/#\/manifests/, { timeout: 15000 });
  await p.getByText('Input Standardization').first().waitFor({ timeout: 20000 });
  const body = async () => (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  let txt = await body();
  console.log('page loaded; tree mentions: agent', /CAM 4\.0 RFQ Automation Agent|RFQ Automation Agent/.test(txt), '| skills', ['Input Standardization', 'Feature Extraction', 'Sales Quote'].every((s) => txt.includes(s)), '| read-only live manifests', /Live routing/i.test(txt), '| banner', /Design input/i.test(txt));
  await p.screenshot({ path: `${OUT}/33-manifests-tree.png` });

  await p.getByText('Input Standardization').first().click();
  await p.waitForSelector('.monaco-editor', { timeout: 30000 });
  await p.waitForTimeout(2000);
  const editorText = async () => (await p.locator('.monaco-editor .view-lines').first().innerText()).replace(/\s+/g, ' ');
  console.log('editor shows JSON:', (await editorText()).slice(0, 110));
  await p.screenshot({ path: `${OUT}/34-manifest-editor.png` });

  // Generated tool tab: baseline
  await p.getByRole('tab', { name: /Generated tool/i }).click().catch(async () => p.getByRole('button', { name: /Generated tool/i }).click());
  await p.waitForTimeout(2500);
  const gen = async () => { const s = await body(); const m = s.match(/Bundle\s+([a-f0-9]{6,64})/i); return { hash: m ? m[1] : null, ast: /AST gate: passed/i.test(s), py: /FastMCP|MAX_ITERATIONS/.test(s) }; };
  const g1 = await gen();
  console.log('generated tab before edit:', JSON.stringify(g1));
  await p.screenshot({ path: `${OUT}/35-generated-tool.png` });

  // Lint tab
  await p.getByRole('tab', { name: /Lint/i }).click().catch(async () => p.getByRole('button', { name: /Lint/i }).click());
  await p.waitForTimeout(1500);
  const lintTxt = await body();
  console.log('lint tab:', (lintTxt.match(/(\d+) (errors?|warnings?)[^.]{0,60}/i) || ['(no counts text)'])[0], '| mentions warning', /warning/i.test(lintTxt));
  await p.screenshot({ path: `${OUT}/36-lint.png` });

  // EDIT: insert text inside i_instructions (line 15) with real keystrokes
  await p.locator('.monaco-editor .view-lines').first().click();
  await p.keyboard.press('Control+G'); await p.keyboard.type('15'); await p.keyboard.press('Enter');
  await p.keyboard.press('Home');
  for (let i = 0; i < 19; i++) await p.keyboard.press('ArrowRight'); // past '"i_instructions": "'
  await p.keyboard.type('SPEC020 LIVE EDIT. ');
  await p.waitForTimeout(1200);
  console.log('dirty indicator after edit:', /unsaved|modified|dirty|\u2022/i.test(await body()));
  await p.getByRole('tab', { name: /Generated tool/i }).click().catch(async () => p.getByRole('button', { name: /Generated tool/i }).click());
  await p.waitForTimeout(2500);
  const g2 = await gen();
  const genText = await body();
  console.log('generated after edit:', JSON.stringify(g2), '| hash changed:', g1.hash !== g2.hash, '| output contains my edit:', /SPEC020 LIVE EDIT/.test(genText));
  await p.screenshot({ path: `${OUT}/37-generated-follows-edit.png` });

  // SAVE
  await p.getByRole('button', { name: /^Save/ }).click();
  await p.waitForTimeout(2500);
  console.log('PUT result:', JSON.stringify(puts.map((x) => [x.status, x.raw])));
  const after = await body();
  console.log('status line:', (after.match(/Saved[^.]{0,120}/) || ['(no "Saved" text)'])[0]);
  await p.screenshot({ path: `${OUT}/38-saved.png` });

  // INVALID EDIT: stray brace at line 15 start -> refused, nothing written
  await p.locator('.monaco-editor .view-lines').first().click();
  await p.keyboard.press('Control+G'); await p.keyboard.type('15'); await p.keyboard.press('Enter');
  await p.keyboard.press('Home'); await p.keyboard.type('}}}');
  await p.waitForTimeout(1500);
  const n = puts.length;
  const saveBtn = p.getByRole('button', { name: /^Save/ });
  const disabled = await saveBtn.isDisabled();
  if (!disabled) { await saveBtn.click(); await p.waitForTimeout(2000); }
  console.log('invalid JSON: Save disabled:', disabled, '| extra PUTs:', puts.length - n, puts.slice(n).map((x) => x.status), '| error text shown:', /invalid|error|expected|valid JSON/i.test(await body()));
  await p.screenshot({ path: `${OUT}/39-invalid.png` });
  console.log('page errors:', JSON.stringify(errs));
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
