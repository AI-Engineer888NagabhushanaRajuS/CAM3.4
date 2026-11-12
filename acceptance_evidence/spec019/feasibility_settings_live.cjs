// Live proof: Settings > Feasibility. Opens the admin tab in real Chrome, sets a lead-time limit and a machine rule, saves,
// checks the stored row in logic_db, then puts the defaults back. Screenshots in feasibility-settings/.
const { createRequire } = require('module');
const fs = require('fs');
const { execFileSync } = require('child_process');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/feasibility-settings'; fs.mkdirSync(OUT, { recursive: true });
const stored = () => execFileSync('docker', ['exec', 'cam-e2e-postgres-1', 'psql', '-U', 'centum', '-d', 'logic_db_2', '-Atc', 'select settings::text from feasibility_settings where id=1'], { encoding: 'utf8' }).trim();
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(2000);
  await p.getByRole('button', { name: /settings/i }).first().click().catch(async () => { await p.locator('header button').nth(1).click(); });
  const dlg = p.getByRole('dialog');
  await dlg.waitFor({ timeout: 10000 });
  await dlg.getByRole('button', { name: /Feasibility/i }).first().click();
  await p.waitForTimeout(800);
  console.log('panel shows:', (await dlg.innerText()).replace(/\s+/g, ' ').slice(0, 160));
  await p.screenshot({ path: `${OUT}/01-defaults.png` });

  const limit = dlg.getByRole('spinbutton').first();
  await limit.fill('15');
  await dlg.getByRole('button', { name: /Add machine rule/i }).click();
  const row = dlg.locator('div.grid').last();
  await row.getByLabel('Rule name').fill('No 0201 placement');
  await row.getByLabel('Value').fill('0201');
  await dlg.getByRole('button', { name: /^Save$/ }).click();
  await p.waitForTimeout(1500);
  console.log('after save:', (await dlg.innerText()).replace(/\s+/g, ' ').match(/Saved\.[^.]*\./)?.[0] || '(no saved message)');
  await p.screenshot({ path: `${OUT}/02-saved.png` });
  console.log('stored row:', stored());

  await dlg.getByRole('button', { name: /Reset to defaults/i }).click();
  await dlg.getByRole('button', { name: /^Save$/ }).click();
  await p.waitForTimeout(1500);
  console.log('restored row:', stored());
  await b.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
