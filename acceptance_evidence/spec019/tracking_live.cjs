// Live proof (SPEC-021 tracking): History toggle always visible, all-RFQ runs, who started a run, Users > Activity.
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/tracking';
require('fs').mkdirSync(OUT, { recursive: true });
const width = Number(process.argv[2] || 1440);
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width, height: width < 500 ? 844 : 900 } })).newPage();
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0, 100)));
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(1500);

  // 1. no RFQ open: the toggle is there, History lists every RFQ's runs
  console.log('1 toggle visible with no RFQ open:', await p.getByRole('button', { name: 'History', exact: true }).count());
  await p.screenshot({ path: `${OUT}/01-landing-toggle-${width}.png` });
  await p.getByRole('button', { name: 'History', exact: true }).click();
  await p.getByTestId('run-history').waitFor({ timeout: 20000 }); await p.waitForTimeout(2500);
  const rows = await p.getByTestId('run-row').allInnerTexts();
  console.log('1 all-RFQ runs:', rows.length); rows.slice(0, 5).forEach((r) => console.log('   ', r.replace(/\s+/g, ' ').slice(0, 170)));
  await p.screenshot({ path: `${OUT}/02-all-runs-${width}.png` });

  if (width >= 500) {
    // 2. open RFQ-000017 from the left list (the UI's own resume: a new run started by the signed-in user)
    const search = p.getByPlaceholder(/Search by RFQ ID/i); await search.fill('RFQ-000017'); await p.waitForTimeout(2500);
    const opt = p.getByText('RFQ-000017', { exact: true }).first(); if (await opt.count()) await opt.click();
    await p.waitForTimeout(6000);
    await p.getByRole('button', { name: 'History', exact: true }).click(); await p.getByTestId('run-history').waitFor({ timeout: 20000 }); await p.waitForTimeout(2500);
    const mine = await p.getByTestId('run-row').allInnerTexts();
    console.log('2 RFQ-000017 runs:', mine.length, '| newest:', (mine[0] || '').replace(/\s+/g, ' ').slice(0, 200));
    await p.screenshot({ path: `${OUT}/03-rfq-history-who-${width}.png` });
    await p.getByRole('button', { name: /^All RFQs$|^My runs$/ }).click(); await p.waitForTimeout(2500);
    console.log('2 switched to all RFQs:', (await p.getByTestId('run-row').count()), 'rows | first:', ((await p.getByTestId('run-row').first().innerText()) || '').replace(/\s+/g, ' ').slice(0, 150));
    await p.screenshot({ path: `${OUT}/04-switch-all-${width}.png` });

    // 3. Settings > Users > Activity
    await p.getByRole('button', { name: /settings/i }).first().click();
    const d = p.getByRole('dialog'); await d.waitFor({ timeout: 10000 });
    const usersTab = d.getByRole('button', { name: /^Users$/ });
    console.log('3 Users tab present:', await usersTab.count());
    if (await usersTab.count()) {
      await usersTab.click(); await p.waitForTimeout(2500);
      const names = await d.locator('p.truncate').allInnerTexts().catch(() => []);
      console.log('3 users listed:', JSON.stringify(names.slice(0, 6)));
      const acts = d.getByRole('button', { name: 'Activity' });
      console.log('3 Activity buttons:', await acts.count());
      for (let i = 0; i < Math.min(await acts.count(), 6); i++) {
        await acts.nth(i).click(); await p.waitForTimeout(1800);
        const txt = (await d.innerText()).replace(/\s+/g, ' ');
        const m = txt.match(/Recent runs[^]*?(?=Hide activity|$)/);
        const li = await d.getByTestId('user-activity').count();
        console.log(`   user ${i}: activity list shown: ${li} | text near:`, (txt.match(/(RFQ-\d+[^A-Z]{0,90})|No runs started by this user yet/) || [''])[0].slice(0, 120));
        await d.getByRole('button', { name: 'Hide activity' }).first().click().catch(() => {});
      }
      await p.screenshot({ path: `${OUT}/05-users-activity-${width}.png` });
    }
  }
  console.log('page errors:', JSON.stringify(errs));
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
