// Live keyboard proof: ProviderSwitch radiogroup and the Manifests editor tablist.
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  const group = p.getByRole('radiogroup', { name: 'Model provider' }); await group.waitFor({ timeout: 20000 });
  await p.waitForTimeout(1500);
  const state = async () => p.evaluate(() => ({ focus: document.activeElement?.textContent?.trim(), checked: [...document.querySelectorAll('[role=radiogroup][aria-label="Model provider"] [role=radio]')].filter((r) => r.getAttribute('aria-checked') === 'true').map((r) => r.textContent.trim()), tabbable: [...document.querySelectorAll('[role=radiogroup][aria-label="Model provider"] [role=radio]')].filter((r) => r.tabIndex === 0).map((r) => r.textContent.trim()), settingsOpen: !!document.querySelector('[data-testid="settings-dialog"]') }));
  await group.getByRole('radio', { name: /^Auto/ }).click();
  console.log('start (Auto clicked):', JSON.stringify(await state()));
  for (const k of ['ArrowRight', 'ArrowRight', 'ArrowRight', 'ArrowLeft']) { await p.keyboard.press(k); await p.waitForTimeout(250); console.log(k.padEnd(10), JSON.stringify(await state())); }

  await p.getByRole('button', { name: /^Manifests$/ }).click();
  await p.getByText('Input Standardization').first().waitFor({ timeout: 20000 });
  await p.getByText('Input Standardization').first().click();
  await p.waitForSelector('.monaco-editor', { timeout: 30000 });
  const tabs = async () => p.evaluate(() => ({ focus: document.activeElement?.textContent?.trim().slice(0, 18), selected: [...document.querySelectorAll('[role=tab]')].filter((x) => x.getAttribute('aria-selected') === 'true').map((x) => x.textContent.trim().slice(0, 18)), tabbable: [...document.querySelectorAll('[role=tab]')].filter((x) => x.tabIndex === 0).length }));
  await p.getByRole('tab', { name: /^JSON/ }).focus();
  console.log('tabs start:', JSON.stringify(await tabs()));
  for (const k of ['ArrowRight', 'ArrowRight', 'ArrowRight', 'End', 'Home']) { await p.keyboard.press(k); await p.waitForTimeout(400); console.log('tabs', k.padEnd(10), JSON.stringify(await tabs())); }
  await b.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
