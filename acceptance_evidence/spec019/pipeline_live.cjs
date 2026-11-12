// Live proof (SPEC-025): the manifests drive the left pane (order, buttons, locked/open) and the pipeline's routing table.
// Real Chrome against :5181 and the daemon on :9334. Evidence in acceptance_evidence/spec019/pipeline.
const { createRequire } = require('module');
const fs = require('fs');
const { execFileSync } = require('child_process');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/pipeline'; fs.mkdirSync(OUT, { recursive: true });
const S03 = 'skills/skill_03_feasibility_risk.json', S06 = 'skills/skill_06_sap_cost_extraction.json', S01 = 'skills/skill_01_input_standardization.json', AGENT = 'agent/agent_manifest.json';
const MAN = 'C:/CAM[3.4]-RFQ_centum/CAM-Source/manifests/';
const keep = {}; for (const f of [S03, S06, S01, AGENT]) keep[f] = fs.readFileSync(MAN + f); // restored byte for byte at the end
const routing = () => execFileSync('docker', ['exec', 'cam-e2e-postgres-1', 'psql', '-U', 'centum', '-d', 'logic_db_2', '-Atc', 'select routing_sequence from quote_routing_profiles'], { encoding: 'utf8' }).trim();
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  let auth = null; p.on('request', (r) => { if (r.url().includes(':9334/') && r.headers().authorization) auth = r.headers().authorization; });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(2500);
  const api = async (method, path, body) => { const r = await fetch(`http://localhost:9334${path}`, { method, headers: { 'Content-Type': 'application/json', Authorization: auth }, body: body ? JSON.stringify(body) : undefined }); return { status: r.status, json: await r.json() }; };
  const setFlag = async (rel, on) => { const f = await api('GET', `/api/manifests/file?path=${encodeURIComponent(rel)}`); const d = JSON.parse(f.json.text); if (on) delete d.skill_metadata.enabled; else d.skill_metadata.enabled = false; return api('PUT', '/api/manifests/file', { path: rel, text: JSON.stringify(d), baseHash: f.json.hash }); };
  const pane = async () => {
    await p.evaluate(() => window.dispatchEvent(new Event('focus'))); await p.waitForTimeout(2500);
    return p.evaluate(() => [...document.querySelectorAll('[role="tree"] > div')].map((d) => { const b = d.querySelector('button[aria-label]'); const s = d.querySelectorAll('button')[1]; return { stage: b?.getAttribute('aria-label'), locked: !!s?.disabled, status: s?.querySelector('span span:nth-child(2)')?.textContent }; }));
  };
  console.log('1 BEFORE (SKILL_03 off, all else on):', JSON.stringify(await pane()));
  console.log('  routing:', routing().slice(0, 90) + '...');
  await p.screenshot({ path: `${OUT}/01-before.png` });

  const r1 = await setFlag(S03, true);
  console.log('2 SKILL_03 enabled -> save', r1.status, JSON.stringify(r1.json.runtime));
  const after1 = await pane();
  console.log('  risk stage now:', JSON.stringify(after1.find((s) => /feasibility/i.test(s.stage))));
  await p.screenshot({ path: `${OUT}/02-risk-unlocked.png` });

  const r2 = await setFlag(S06, false);
  console.log('3 SKILL_06 disabled -> save', r2.status, JSON.stringify(r2.json.runtime));
  console.log('  routing now:', routing());
  const after2 = await pane();
  console.log('  ERP stage now:', JSON.stringify(after2.find((s) => /ERP/i.test(s.stage))));
  await p.screenshot({ path: `${OUT}/03-erp-off.png` });

  const r3 = await setFlag(S06, true);
  console.log('4 SKILL_06 enabled again -> save', r3.status, JSON.stringify(r3.json.runtime));
  console.log('  routing restored:', routing());
  console.log('5 order of the pane:', (await pane()).map((s) => s.stage).join(' > '));
  const subs = async () => p.evaluate(() => [...document.querySelectorAll('[data-testid^="sub-skills-"]')].map((e) => [e.getAttribute('data-testid'), [...e.querySelectorAll('button')].map((x) => x.textContent.trim()).filter(Boolean)]));
  console.log('  buttons shown (current stage):', JSON.stringify(await subs()));

  // 6: a check that can fail: swap the run order of two skills and rename one button, both only in the manifest files.
  const ag = await api('GET', `/api/manifests/file?path=${encodeURIComponent(AGENT)}`); const da = JSON.parse(ag.json.text);
  const e7 = da.skill_sequence.find((s) => s.skill_id === 'SKILL_07'), e8 = da.skill_sequence.find((s) => s.skill_id === 'SKILL_08');
  [e7.sequence, e8.sequence] = [e8.sequence, e7.sequence];
  const ra = await api('PUT', '/api/manifests/file', { path: AGENT, text: JSON.stringify(da), baseHash: ag.json.hash });
  const s1 = await api('GET', `/api/manifests/file?path=${encodeURIComponent(S01)}`); const d1 = JSON.parse(s1.json.text);
  d1.ui_actions[0].label = 'Start a new RFQ';
  const rs = await api('PUT', '/api/manifests/file', { path: S01, text: JSON.stringify(d1), baseHash: s1.json.hash });
  console.log('6 swapped SKILL_07/08 and renamed "Create RFQ" ->', ra.status, rs.status);
  console.log('  pane order now:', (await pane()).map((s) => s.stage).join(' > '));
  console.log('  buttons now:', JSON.stringify(await subs()));
  await p.screenshot({ path: `${OUT}/04-reordered-renamed.png` });
  await b.close();
  for (const f of [S03, S06, AGENT, S01]) fs.writeFileSync(MAN + f, keep[f]); // put the manifests back exactly as they were
  console.log('manifests restored; routing:', routing().slice(0, 90) + '...');
})().catch((e) => { for (const f of [S03, S06, S01, AGENT]) fs.writeFileSync(MAN + f, keep[f]); console.error('FAILED', e); process.exit(1); });
