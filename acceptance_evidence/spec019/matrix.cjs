// Responsive + dark-mode matrix for the new round-3 pages (Manifests, Security tab, Live changes).
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/matrix';
require('fs').mkdirSync(OUT, { recursive: true });
const RFQ = 'RFQ-CENTUM-PROOF-24';
const SIZES = [[1440, 900], [1024, 768], [390, 844]];
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const rows = [];
  for (const dark of [false, true]) {
    for (const [w, h] of SIZES) {
      const ctx = await b.newContext({ viewport: { width: w, height: h }, colorScheme: dark ? 'dark' : 'light' });
      if (dark) await ctx.addInitScript(() => { try { localStorage.setItem('theme', 'dark'); } catch {} });
      const p = await ctx.newPage();
      const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0, 100)));
      const tag = `${dark ? 'dark' : 'light'}-${w}`;
      const overflow = () => p.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, isDark: document.documentElement.classList.contains('dark') }));
      const rec = async (page, note) => { if (dark) { await p.evaluate(() => document.documentElement.classList.add('dark')); await p.waitForTimeout(400); } const o = await overflow(); rows.push({ tag, page, ...o, overflowPx: o.sw - o.cw, note: note || '' }); await p.screenshot({ path: `${OUT}/${page}-${tag}.png` }); };
      await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
      const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
      await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
      if (dark) await p.evaluate(() => document.documentElement.classList.add('dark'));
      // Manifests
      await p.goto('http://localhost:5181/#/manifests'); await p.getByText('Input Standardization').first().waitFor({ timeout: 20000 }).catch(() => {});
      await p.waitForTimeout(800); await rec('manifests-tree');
      await p.getByText('Input Standardization').first().click().catch(() => {});
      await p.waitForSelector('.monaco-editor', { timeout: 30000 }).catch(() => {}); await p.waitForTimeout(1500); await rec('manifests-editor');
      // Security tab
      await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' }); await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
      if (dark) await p.evaluate(() => document.documentElement.classList.add('dark'));
      await p.getByRole('button', { name: /settings/i }).first().click().catch(() => {});
      const d = p.getByRole('dialog'); await d.waitFor({ timeout: 10000 }).catch(() => {});
      await d.getByRole('button', { name: /^Security$/ }).click().catch(() => {}); await p.waitForTimeout(3000); await rec('security-tab');
      await p.keyboard.press('Escape');
      // Live changes: open the RFQ through the assistant, as a user would
      await p.fill('[data-testid="task-input-textarea"]', `open ${RFQ}`); await p.click('[data-testid="task-input-submit"]'); await p.waitForTimeout(6000);
      const ob = p.getByRole('button', { name: new RegExp(`Open ${RFQ}`) }).first(); if (await ob.count()) { await ob.click(); await p.waitForTimeout(4000); }
      await rec('live-changes');
      if (errs.length) rows.push({ tag, page: 'ERRORS', note: errs.join(' | ') });
      await ctx.close();
    }
  }
  await b.close();
  for (const r of rows) console.log(JSON.stringify(r));
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
