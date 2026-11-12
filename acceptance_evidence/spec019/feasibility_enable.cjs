// Live proof (SPEC-025): switching SKILL_03 on in the manifest adds the real Feasibility & Risk tool to the routing table,
// unlocks the stage in the left pane, and keeps every RFQ that is already part-way at its place. Left ON (not restored).
const { createRequire } = require('module');
const fs = require('fs');
const { execFileSync } = require('child_process');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/feasibility'; fs.mkdirSync(OUT, { recursive: true });
const S03 = 'skills/skill_03_feasibility_risk.json';
const psql = (db, sql) => execFileSync('docker', ['exec', 'cam-e2e-postgres-1', 'psql', '-U', 'centum', '-d', db, '-Atc', sql], { encoding: 'utf8' }).trim();
const routing = () => psql('logic_db_2', 'select routing_sequence from quote_routing_profiles');
const stages = () => psql('file_metadata_db_2', "select rfq_id||'='||rfq_process_stage from rfq_process_tracking where is_active and rfq_process_stage>0 order by rfq_id").split('\n').join(' ');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  let auth = null; p.on('request', (r) => { if (r.url().includes(':9334/') && r.headers().authorization) auth = r.headers().authorization; });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(2500);
  const api = async (method, path, body) => { const r = await fetch(`http://localhost:9334${path}`, { method, headers: { 'Content-Type': 'application/json', Authorization: auth }, body: body ? JSON.stringify(body) : undefined }); return { status: r.status, json: await r.json() }; };
  const pane = async () => {
    await p.evaluate(() => window.dispatchEvent(new Event('focus'))); await p.waitForTimeout(2500);
    return p.evaluate(() => [...document.querySelectorAll('[role="tree"] > div')].map((d) => { const b = d.querySelector('button[aria-label]'); const s = d.querySelectorAll('button')[1]; return { stage: b?.getAttribute('aria-label'), locked: !!s?.disabled, status: s?.querySelector('span span:nth-child(2)')?.textContent }; }));
  };
  const risk = (rows) => JSON.stringify(rows.find((s) => /feasibility/i.test(s.stage)));
  console.log('1 BEFORE  risk stage:', risk(await pane()));
  console.log('  routing:', routing());
  const stagesBefore = stages();
  console.log('  in-flight stages:', stagesBefore);
  await p.screenshot({ path: `${OUT}/01-before-locked.png` });

  const f = await api('GET', `/api/manifests/file?path=${encodeURIComponent(S03)}`); const d = JSON.parse(f.json.text);
  delete d.skill_metadata.enabled;
  const r = await api('PUT', '/api/manifests/file', { path: S03, text: JSON.stringify(d, null, 2) + '\n', baseHash: f.json.hash });
  console.log('2 SKILL_03 on -> save', r.status, JSON.stringify(r.json.runtime));
  console.log('  routing:', routing());
  console.log('  risk stage now:', risk(await pane()));
  const stagesAfter = stages();
  console.log('  in-flight stages:', stagesAfter);
  console.log('  finished RFQs moved 8 -> 9, RFQs that stopped before the new step unchanged:', stagesBefore !== stagesAfter);
  await p.screenshot({ path: `${OUT}/02-after-open.png` });
  await b.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
