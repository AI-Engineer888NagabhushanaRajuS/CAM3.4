// Live proof (SPEC-022): Manifests > Changes tab (Monaco inline diff). usage: node changes_live.cjs [dark] [width]
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/changes';
require('fs').mkdirSync(OUT, { recursive: true });
const dark = process.argv[2] === 'dark'; const width = Number(process.argv[3] || 1440);
const tag = `${dark ? 'dark' : 'light'}-${width}`;
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const ctx = await b.newContext({ viewport: { width, height: width < 500 ? 844 : 900 } });
  if (dark) await ctx.addInitScript(() => { try { localStorage.setItem('theme', 'dark'); } catch {} });
  const p = await ctx.newPage();
  const puts = []; p.on('response', async (r) => { if (/\/api\/manifests\/file/.test(r.url()) && r.request().method() === 'PUT') { let j = null; try { j = await r.json(); } catch {} puts.push({ status: r.status(), v: j?.version }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.getByRole('radiogroup', { name: 'Model provider' }).waitFor({ timeout: 20000 });
  await p.getByRole('button', { name: /^Manifests$/ }).click();
  await p.getByText('Feature Extraction').first().waitFor({ timeout: 20000 });
  await p.getByText('Feature Extraction').first().click();
  await p.waitForSelector('.monaco-editor', { timeout: 30000 }); await p.waitForTimeout(1800);
  if (dark) await p.evaluate(() => document.documentElement.classList.add('dark'));
  const body = async () => (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  const replace = async (find, repl) => { await p.locator('.monaco-editor .view-lines').first().click(); await p.keyboard.press('Control+H'); await p.waitForTimeout(400); await p.keyboard.type(find); await p.keyboard.press('Tab'); await p.keyboard.type(repl); await p.keyboard.press('Control+Alt+Enter'); await p.waitForTimeout(500); await p.keyboard.press('Escape'); await p.waitForTimeout(500); };

  // 1. Changes tab with nothing edited
  await p.getByRole('tab', { name: /^Changes/ }).click(); await p.waitForTimeout(1500);
  console.log('1 clean editor:', (await body()).match(/No unsaved changes: the editor matches[^.]*\./)?.[0]);
  // 2. edit, then Changes (saved on disk baseline)
  await p.getByRole('tab', { name: /^JSON/ }).click(); await p.waitForTimeout(500);
  await replace('Nagabhushan / Harish', 'Nagabhushan / Harish (changes proof)');
  await p.getByRole('tab', { name: /^Changes/ }).click(); await p.waitForSelector('.monaco-diff-editor', { timeout: 20000 }); await p.waitForTimeout(2500);
  console.log('2 unsaved diff:', (await body()).match(/\d+ changed lines?: [^.]*?modified/)?.[0], '| diff editor present:', await p.locator('.monaco-diff-editor').count(), '| added/removed marks:', await p.locator('.line-insert, .char-insert').count(), await p.locator('.line-delete, .char-delete').count());
  await p.screenshot({ path: `${OUT}/01-unsaved-diff-${tag}.png` });
  // 3. save, then compare with the previous saved version
  await p.getByTitle('Save (Ctrl+S)').click(); await p.waitForTimeout(2500);
  console.log('3 save:', JSON.stringify(puts));
  await p.getByRole('button', { name: 'Previous saved version' }).click(); await p.waitForSelector('.monaco-diff-editor', { timeout: 20000 }).catch(() => {}); await p.waitForTimeout(2500);
  const t3 = await body();
  console.log('3 vs previous:', t3.match(/Baseline [^.]*\./)?.[0], '|', t3.match(/\d+ changed lines?: [^.]*?modified/)?.[0], '| layout note:', /spacing and line breaks are ignored/.test(t3));
  await p.screenshot({ path: `${OUT}/02-previous-version-${tag}.png` });
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
