// Live proof of the stale-save (409) path: two browser sessions edit the same manifest.
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
const NAME = 'Feature Extraction';
async function session(b, label) {
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage(); const puts = [];
  p.on('response', async (r) => { if (/\/api\/manifests\/file/.test(r.url()) && r.request().method() === 'PUT') { let j = null; try { j = await r.json(); } catch {} puts.push({ status: r.status(), j }); } });
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.getByRole('radiogroup', { name: 'Model provider' }).waitFor({ timeout: 20000 });
  await p.getByRole('button', { name: /^Manifests$/ }).click();
  await p.getByText(NAME).first().waitFor({ timeout: 20000 });
  await p.getByText(NAME).first().click();
  await p.waitForSelector('.monaco-editor', { timeout: 30000 }); await p.waitForTimeout(1800);
  const body = async () => (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  const replace = async (find, repl) => { await p.locator('.monaco-editor .view-lines').first().click(); await p.keyboard.press('Control+H'); await p.waitForTimeout(400); await p.keyboard.type(find); await p.keyboard.press('Tab'); await p.keyboard.type(repl); await p.keyboard.press('Control+Alt+Enter'); await p.waitForTimeout(500); await p.keyboard.press('Escape'); await p.waitForTimeout(500); };
  return { label, p, puts, body, replace };
}
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const A = await session(b, 'A'); const B = await session(b, 'B');
  console.log('both opened:', (await A.body()).match(/Hash\s+\S+/)?.[0], '|', (await B.body()).match(/Hash\s+\S+/)?.[0]);

  await A.replace('Nagabhushan / Harish', 'Nagabhushan / Harish (A)');
  await A.p.getByRole('button', { name: /^Save/ }).click(); await A.p.waitForTimeout(2500);
  console.log('A save ->', A.puts.map((x) => [x.status, x.j?.version]), '| A now shows', (await A.body()).match(/Version\s+\S+/)?.[0]);

  // B still holds the old hash
  await B.replace('Nagabhushan / Harish', 'Nagabhushan / Harish (B)');
  await B.p.getByRole('button', { name: /^Save/ }).click(); await B.p.waitForTimeout(2500);
  console.log('B save ->', B.puts.map((x) => [x.status, x.j?.error || x.j?.currentHash?.slice(0, 10)]));
  const bt = await B.body();
  console.log('B shows conflict banner:', /changed on disk since you opened it/.test(bt), '| buttons Reload/Keep mine:', await B.p.getByRole('button', { name: 'Reload' }).count(), await B.p.getByRole('button', { name: /Keep mine/ }).count());
  await B.p.screenshot({ path: `${OUT}/50-stale-409.png` });

  // Keep mine: the next save replaces the disk version (explicit choice)
  await B.p.getByRole('button', { name: /Keep mine/ }).click(); await B.p.waitForTimeout(500);
  await B.p.getByRole('button', { name: /^Save/ }).click(); await B.p.waitForTimeout(2500);
  console.log('B after Keep mine + Save ->', B.puts.map((x) => x.status), '| conflict gone:', !/changed on disk since you opened it/.test(await B.body()));
  await B.p.screenshot({ path: `${OUT}/51-keep-mine-saved.png` });
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
