const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const puts = [];
  p.on('response', async (r) => { if (/\/api\/manifests\/file/.test(r.url()) && r.request().method() === 'PUT') { let j = null; try { j = await r.json(); } catch {} puts.push({ status: r.status(), j }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.getByRole('radiogroup', { name: 'Model provider' }).waitFor({ timeout: 20000 });
  await p.getByRole('button', { name: /^Manifests$/ }).click();
  await p.getByText('Input Standardization').first().waitFor({ timeout: 20000 });
  await p.getByText('Input Standardization').first().click();
  await p.waitForSelector('.monaco-editor', { timeout: 30000 });
  await p.waitForTimeout(2000);
  const body = async () => (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  const line15 = async () => (await p.locator('.monaco-editor .view-lines').first().innerText()).split('\n').find((l) => l.includes('i_instructions')) || '';
  const bundle = async () => ((await body()).match(/Bundle\s+([a-f0-9]{6,64})/i) || [])[1] || null;
  const replace = async (find, repl) => { await p.locator('.monaco-editor .view-lines').first().click(); await p.keyboard.press('Control+H'); await p.waitForTimeout(400); await p.keyboard.type(find); await p.keyboard.press('Tab'); await p.keyboard.type(repl); await p.keyboard.press('Control+Alt+Enter'); await p.waitForTimeout(300); await p.keyboard.press('Escape'); await p.waitForTimeout(1800); };
  console.log('version/hash before:', (await body()).match(/Version\s+\S+/)?.[0], (await body()).match(/Hash\s+\S+/)?.[0]);
  await p.getByRole('tab', { name: /Generated tool/i }).click(); await p.waitForTimeout(2500);
  const b1 = await bundle(); console.log('generated bundle before:', b1);

  await replace('Triggered by manual UI upload', 'SPEC020 LIVE EDIT. Triggered by manual UI upload');
  console.log('editor line:', (await line15()).trim().slice(0, 60));
  const b2 = await bundle(); console.log('generated bundle after edit (live, unsaved):', b2, '| followed the edit:', b1 !== b2);
  console.log('server validation:', /Server validation: no problems/.test(await body()) ? 'no problems' : 'see page');
  await p.getByRole('button', { name: /^Save/ }).click();
  await p.waitForTimeout(2500);
  console.log('PUT:', puts.map((x) => [x.status, x.j?.version, (x.j?.hash || '').slice(0, 10), (x.j?.deterministicHash || '').slice(0, 17), x.j?.validation?.ok]));
  const after = await body();
  console.log('status line:', (after.match(/Saved[^.]{0,100}/) || [])[0] || '(no Saved text)', '| version/hash after:', after.match(/Version\s+\S+/)?.[0], after.match(/Hash\s+\S+/)?.[0]);
  await p.screenshot({ path: `${OUT}/38-saved.png` });

  // second save from a STALE view: reload the page state is not needed; the API-level 409 is checked separately.
  // INVALID EDIT through the UI: a stray character makes the JSON invalid -> refused, nothing written
  const n = puts.length;
  await replace('"isatvon_definition": {', '"isatvon_definition": {{');
  const dis = await p.getByRole('button', { name: /^Save/ }).isDisabled();
  if (!dis) { await p.getByRole('button', { name: /^Save/ }).click(); await p.waitForTimeout(2000); }
  console.log('invalid edit: Save disabled:', dis, '| PUTs sent:', puts.length - n, puts.slice(n).map((x) => [x.status, x.j?.validation?.errors?.[0]?.message?.slice(0, 80)]));
  console.log('error text visible:', /Invalid JSON|invalid/i.test(await body()));
  await p.screenshot({ path: `${OUT}/39-invalid.png` });
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
