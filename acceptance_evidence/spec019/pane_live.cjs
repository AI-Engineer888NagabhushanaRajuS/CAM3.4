// Live proof (SPEC-023): the left pane follows the manifests. `enabled:false` saved through the manifest API greys the stage and the sub-skill.
const { createRequire } = require('module');
const fs = require('fs');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/pane'; fs.mkdirSync(OUT, { recursive: true });
const width = Number(process.argv[2] || 1440);
const S1 = 'skills/skill_01_input_standardization.json', S2 = 'skills/skill_02_feature_extraction.json';
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width, height: 900 } })).newPage();
  let auth = null; p.on('request', (r) => { if (r.url().includes(':9334/') && r.headers().authorization) auth = r.headers().authorization; });
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(2500);
  const api = (method, path, body) => fetch(`http://localhost:9334${path}`, { method, headers: { 'Content-Type': 'application/json', Authorization: auth }, body: body ? JSON.stringify(body) : undefined }).then(async (r) => ({ status: r.status, json: await r.json() }));
  const stageBtn = (name) => p.getByRole('button', { name, exact: true }).first();
  const state = async () => ({
    extract: (await p.getByRole('button', { name: 'Extract features' }).first().isDisabled()),
    extractLabel: ((await p.locator('[role="tree"]').innerText()).match(/Extract features\s*\n\s*([^\n]+)/) || [])[1],
    subs: await p.getByTestId('manifest-sub').evaluateAll((els) => els.map((e) => [e.textContent.trim().slice(0, 40), e.getAttribute('aria-disabled')])),
  });

  console.log('auth captured:', !!auth);
  console.log('stages in the tree:', JSON.stringify(await p.locator('[role="tree"] > div').count()), '| unwired note:', (await p.getByTestId('unwired-skills').innerText().catch(() => '(none)')));
  console.log('BEFORE:', JSON.stringify(await state()));
  await p.screenshot({ path: `${OUT}/01-before-${width}.png` });

  // switch SKILL_02 off and sub-skill 1.2 of SKILL_01 off, through the real save route (admin)
  const f2 = await api('GET', `/api/manifests/file?path=${encodeURIComponent(S2)}`); const d2 = JSON.parse(f2.json.text); d2.skill_metadata.enabled = false;
  const r2 = await api('PUT', '/api/manifests/file', { path: S2, text: JSON.stringify(d2), baseHash: f2.json.hash });
  const f1 = await api('GET', `/api/manifests/file?path=${encodeURIComponent(S1)}`); const d1 = JSON.parse(f1.json.text); d1.sub_skills[1].enabled = false;
  const r1 = await api('PUT', '/api/manifests/file', { path: S1, text: JSON.stringify(d1), baseHash: f1.json.hash });
  console.log('saved SKILL_02 enabled=false ->', r2.status, r2.json.version, '| SKILL_01 sub 1.2 enabled=false ->', r1.status, r1.json.version);
  await p.evaluate(() => window.dispatchEvent(new Event('focus'))); await p.waitForTimeout(2500);
  console.log('AFTER :', JSON.stringify(await state()));
  await p.screenshot({ path: `${OUT}/02-after-off-${width}.png` });

  // revert both (flags removed), so the live manifests are back to "no flag"
  const g2 = await api('GET', `/api/manifests/file?path=${encodeURIComponent(S2)}`); const e2 = JSON.parse(g2.json.text); delete e2.skill_metadata.enabled;
  const v2 = await api('PUT', '/api/manifests/file', { path: S2, text: JSON.stringify(e2), baseHash: g2.json.hash });
  const g1 = await api('GET', `/api/manifests/file?path=${encodeURIComponent(S1)}`); const e1 = JSON.parse(g1.json.text); delete e1.sub_skills[1].enabled;
  const v1 = await api('PUT', '/api/manifests/file', { path: S1, text: JSON.stringify(e1), baseHash: g1.json.hash });
  console.log('reverted ->', v2.status, v1.status);
  await p.evaluate(() => window.dispatchEvent(new Event('focus'))); await p.waitForTimeout(2500);
  console.log('REVERTED:', JSON.stringify(await state()));

  // "Scan for virus" is a control now: it opens Settings on the Security tab
  const stage = p.getByRole('button', { name: 'Upload file' }).first(); await stage.click(); await p.waitForTimeout(500);
  const scan = p.getByRole('button', { name: 'Scan for virus' }); console.log('Scan for virus is a button:', await scan.count(), '| disabled:', await scan.first().isDisabled().catch(() => null));
  await scan.first().click(); await p.waitForTimeout(1800);
  const dlg = p.getByRole('dialog'); console.log('settings opened:', await dlg.count(), '| security panel text:', (await dlg.innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 160));
  await p.screenshot({ path: `${OUT}/03-scan-opens-security-${width}.png` });
  console.log('page errors:', JSON.stringify(errs));
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
