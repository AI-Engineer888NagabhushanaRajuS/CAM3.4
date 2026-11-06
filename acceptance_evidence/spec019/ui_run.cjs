// Real-browser run of the CAM 3.4 assistant against the live stack (Vite :5181, daemon :9334). Usage: node ui_run.cjs <scenario>
const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const fs = require('fs');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019';
fs.mkdirSync(OUT, { recursive: true });
const scenario = process.argv[2] || 'explore';

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const net = [];
  page.on('response', async (r) => {
    if (/\/api\/chat/.test(r.url()) && r.request().method() === 'POST') {
      let body = null; try { body = await r.json(); } catch {}
      net.push({ url: r.url(), status: r.status(), req: JSON.parse(r.request().postData() || '{}'), body });
    }
  });
  const log = (...a) => console.log(...a);
  await page.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const tester = page.getByRole('button', { name: /Sign in as Tester/i });
  if (await tester.count()) { await tester.click(); await page.waitForLoadState('networkidle'); }
  await page.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  log('title:', await page.title());

  const ask = async (text, waitMs) => {
    const before = net.length;
    await page.fill('[data-testid="task-input-textarea"]', text);
    await page.click('[data-testid="task-input-submit"]');
    const t0 = Date.now();
    while (net.length === before && Date.now() - t0 < waitMs) await page.waitForTimeout(500);
    await page.waitForTimeout(800);
    return { ms: Date.now() - t0, entry: net[net.length - 1] };
  };
  const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png` });

  if (scenario === 'explore') {
    await shot('00-home');
    log((await page.locator('body').innerText()).slice(0, 1500));
  }

  if (scenario === 'nomodel') {
    // O2 (no scope): a data question opens the RFQ picker populated from the database
    let r = await ask('what is the go / no-go status?', 60000);
    log('S2 chat ms', r.ms, 'ui', r.entry?.body?.ui?.type, 'options', r.entry?.body?.ui?.options?.length, 'model', r.entry?.body?.model);
    log('S2 url:', r.entry?.url, '| status', r.entry?.status);
    log('S2 reply:', JSON.stringify(r.entry?.body).slice(0, 400));
    const dialog = page.getByRole('dialog');
    await dialog.waitFor({ timeout: 10000 });
    log('picker open:', (await dialog.innerText()).replace(/\s+/g, ' ').slice(0, 600));
    await shot('02-picker');
    fs.writeFileSync(`${OUT}/02-pick-rfq-network.json`, JSON.stringify(r.entry, null, 2));

    // O3: All context -> per-RFQ table (no model)
    await dialog.getByRole('button', { name: /All context/i }).click();
    const t0 = Date.now();
    while (net.length < 2 && Date.now() - t0 < 90000) await page.waitForTimeout(500);
    await page.waitForTimeout(1500);
    const all = net[net.length - 1];
    log('S3 scope', JSON.stringify(all?.req?.scope), 'model', all?.body?.model, 'cites', all?.body?.citations?.length);
    log('S3 answer:', (all?.body?.message || '').slice(0, 700));
    await shot('03-all-context');
    fs.writeFileSync(`${OUT}/03-all-context-network.json`, JSON.stringify(all, null, 2));
  }

  if (scenario === 'multi') {
    // pick TWO RFQs in the popup -> per-RFQ table with RFQ ids in the citations (no model), then an unknown part is refused
    let r = await ask('what is the go / no-go status?', 60000);
    const dialog = page.getByRole('dialog');
    await dialog.waitFor({ timeout: 10000 });
    await dialog.getByText('RFQ-CENTUM-PROOF-24', { exact: true }).click();
    await dialog.getByText('RFQ-CENTUM-PROOF-23', { exact: true }).click();
    await shot('04-picker-two-selected');
    const n0 = net.length;
    await dialog.getByRole('button', { name: /Use selected/i }).click();
    let t0 = Date.now();
    while (net.length === n0 && Date.now() - t0 < 120000) await page.waitForTimeout(500);
    await page.waitForTimeout(1500);
    const two = net[net.length - 1];
    log('S-multi req scope', JSON.stringify(two?.req?.scope), 'ms', Date.now() - t0, 'model', two?.body?.model);
    log('S-multi answer:', (two?.body?.message || '').slice(0, 900));
    log('S-multi citations:', JSON.stringify((two?.body?.citations || []).map((c) => [c.sourceType, c.label || c.identifier])).slice(0, 500));
    log('chips:', (await page.locator('body').innerText()).includes('RFQ-CENTUM-PROOF-23'));
    await shot('04-multi-table');
    fs.writeFileSync(`${OUT}/04-multi-network.json`, JSON.stringify(two, null, 2));
  }

  if (scenario === 'unknownpart') {
    // one RFQ in scope (picked in the popup), a part number that exists nowhere: refused plainly, nothing invented
    await ask('what is the go / no-go status?', 60000);
    const dialog = page.getByRole('dialog');
    await dialog.waitFor({ timeout: 10000 });
    await dialog.getByText('RFQ-CENTUM-PROOF-24', { exact: true }).click();
    // do not wait for the model-phrased answer of the first question: Stop it, we test the refusal next
    await dialog.getByRole('button', { name: /Use selected/i }).click();
    await page.waitForTimeout(1500);
    const stop = page.getByRole('button', { name: /Stop/i });
    if (await stop.count()) await stop.first().click();
    await page.waitForTimeout(500);
    const r = await ask('what is the unit price of part ZZZ-NOPE-999 ?', 150000);
    log('S5 ms', r.ms, 'model', r.entry?.body?.model, 'scope', JSON.stringify(r.entry?.req?.scope));
    log('S5 answer:', (r.entry?.body?.message || '').slice(0, 700));
    await shot('05-unknown-part');
    fs.writeFileSync(`${OUT}/05-unknown-part-network.json`, JSON.stringify(r.entry, null, 2));
  }

  if (scenario === 'guide') {
    // O1: plain talk with no RFQ chosen gets a helpful answer from the user guide (never 'No relevant context found')
    const r = await ask('HAI HOW TO USE THIS TOOL ?', 240000);
    log('O1 ms', r.ms, 'model', r.entry?.body?.model, 'status', r.entry?.status, 'cites', JSON.stringify((r.entry?.body?.citations || []).map((c) => [c.sourceType, c.label])).slice(0, 300));
    log('O1 answer:', (r.entry?.body?.message || '').slice(0, 1200));
    log('has canned text:', /No relevant context found/i.test(r.entry?.body?.message || ''));
    await shot('01-guide');
    fs.writeFileSync(`${OUT}/01-guide-network.json`, JSON.stringify(r.entry, null, 2));
  }

  if (scenario === 'verified') {
    // O2: pick RFQ-CENTUM-PROOF-24 in the popup, answer GO citing Manifest!A32:C32
    await ask('what is the go / no-go status?', 60000);
    const dialog = page.getByRole('dialog');
    await dialog.waitFor({ timeout: 10000 });
    await dialog.getByText('RFQ-CENTUM-PROOF-24', { exact: true }).click();
    const n0 = net.length; const t0 = Date.now();
    await dialog.getByRole('button', { name: /Use selected/i }).click();
    while (net.length === n0 && Date.now() - t0 < 240000) await page.waitForTimeout(500);
    await page.waitForTimeout(1500);
    const a = net[net.length - 1];
    log('O2 ms', Date.now() - t0, 'model', a?.body?.model, 'status', a?.status);
    log('O2 answer:', (a?.body?.message || '').slice(0, 900));
    log('O2 cites:', JSON.stringify((a?.body?.citations || []).map((c) => c.label)).slice(0, 300));
    await shot('06-verified-go');
    fs.writeFileSync(`${OUT}/06-verified-network.json`, JSON.stringify(a, null, 2));
  }

  if (scenario === 'attach') {
    // O6 part 1: attach BOM + Volume with NO RFQ chosen -> select/reject popup -> both engines -> released chips
    const dir = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/test_inputs';
    await page.setInputFiles('[data-testid="assistant-file-input"]', [`${dir}/Centum_BOM.xlsx`, `${dir}/Volume_File.xlsx`]);
    const dlg = page.getByRole('dialog');
    await dlg.waitFor({ timeout: 15000 });
    log('popup 1:', (await dlg.innerText()).replace(/\s+/g, ' ').slice(0, 700));
    await shot('07-attach-popup');
    const buttons = await dlg.getByRole('button').allInnerTexts();
    log('popup buttons:', JSON.stringify(buttons));
    const scanResp = page.waitForResponse((r) => /\/attachments\/scan/.test(r.url()) && r.request().method() === 'POST', { timeout: 120000 });
    await dlg.getByRole('button', { name: /^Scan \d+ files?$/ }).click();
    const sr = await scanResp;
    const sj = await sr.json().catch(() => null);
    log('scan', sr.status(), 'url', sr.url().replace(/^https?:\/\/[^/]+/, ''), 'engines', JSON.stringify((sj?.engines || []).map((e) => [e.id, e.status])));
    log('verdicts', JSON.stringify((sj?.results || []).map((x) => [x.name, x.decision, x.clamav?.verdict, x.repel?.verdict, x.attachment_id])));
    fs.writeFileSync(`${OUT}/07-scan-network.json`, JSON.stringify(sj, null, 2));
    await page.waitForTimeout(2500);
    await shot('08-attach-scanned');
    log('dialog text:', (await dlg.innerText().catch(() => '(closed)')).replace(/\s+/g, ' ').slice(0, 700));
    const close = dlg.getByRole('button', { name: /^Close$|Done|Continue/ });
    if (await close.count()) await close.first().click();
    await page.waitForTimeout(1500);
    log('chips:', JSON.stringify(await page.locator('li').allInnerTexts()).slice(0, 400));
    await shot('09-attached-chips');
  }

  if (scenario === 'create') {
    const decision = process.argv[3] || 'cancel';
    const dir = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/test_inputs';
    await page.setInputFiles('[data-testid="assistant-file-input"]', [`${dir}/Centum_BOM.xlsx`, `${dir}/Volume_File.xlsx`]);
    const dlg = page.getByRole('dialog');
    await dlg.waitFor({ timeout: 15000 });
    await dlg.getByRole('button', { name: /^Scan \d+ files?$/ }).click();
    await dlg.getByRole('button', { name: 'Done' }).waitFor({ timeout: 120000 });
    await dlg.getByRole('button', { name: 'Done' }).click();
    log('verdict view shown before Done: yes (button Done present)');
    const r = await ask('create an RFQ from these files for customer 000, project UBR-TEST-3.4', 60000);
    const ui = r.entry?.body?.ui;
    log('C1 ms', r.ms, 'model', r.entry?.body?.model, 'ui', ui?.type, 'fileRefs', JSON.stringify(r.entry?.req?.fileRefs?.map((f) => [f.name, f.rfqId])));
    log('C1 message:', (r.entry?.body?.message || '').slice(0, 500));
    log('C1 params:', JSON.stringify(ui?.params || null).slice(0, 700));
    await shot(`10-confirm-card-${decision}`);
    fs.writeFileSync(`${OUT}/10-propose-network.json`, JSON.stringify(r.entry, null, 2));
    if (ui?.type === 'confirm_action') {
      log('card text:', (await page.locator('[data-testid="confirm-action-card"], section, div').filter({ hasText: /Confirm/ }).last().innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 500));
      const respP = page.waitForResponse((x) => /\/api\/chat\/actions\/confirm/.test(x.url()), { timeout: 240000 });
      await page.getByRole('button', { name: decision === 'confirm' ? /^Confirm/ : /^Cancel/ }).last().click();
      const resp = await respP;
      const body = await resp.json().catch(() => null);
      log('C2', decision, 'status', resp.status(), 'ok', body?.ok, 'rfqId', body?.rfqId);
      log('C2 steps:', JSON.stringify(body?.steps));
      log('C2 message:', body?.message);
      fs.writeFileSync(`${OUT}/11-confirm-${decision}-network.json`, JSON.stringify(body, null, 2));
      await page.waitForTimeout(1500);
      await shot(`11-after-${decision}`);
    }
  }

  if (scenario === 'leftlist') {
    // O6 tail: the RFQ the assistant created shows up in the app's own RFQ list and pipeline view
    const search = page.getByPlaceholder(/Search by RFQ ID/i);
    await search.fill('RFQ-000017');
    await page.waitForTimeout(2500);
    log('visible after search:', (await page.locator('body').innerText()).includes('RFQ-000017'));
    const opt = page.getByText('RFQ-000017', { exact: true }).first();
    if (await opt.count()) await opt.click();
    await page.waitForTimeout(4000);
    const t = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
    log('pipeline view:', t.slice(0, 700));
    log('assistant scope chip:', /RFQ-000017/.test(t));
    await shot('12-rfq-000017-pipeline');
  }

  if (scenario === 'switch') {
    const group = page.getByRole('radiogroup', { name: 'Model provider' });
    await group.waitFor({ timeout: 15000 });
    const read = async () => (await group.getByRole('radio').evaluateAll((els) => els.map((e) => [e.textContent.trim(), e.getAttribute('aria-checked'), e.getAttribute('title')])));
    await page.waitForTimeout(1500);
    log('radios:', JSON.stringify(await read()));
    await shot('13-provider-switch');
    const provRes = await page.evaluate(async () => {
      const raw = Object.keys(localStorage).concat(Object.keys(sessionStorage));
      return raw.filter((k) => /token|session/i.test(k)).length;
    });
    // OpenRouter without a saved key: must not switch silently; opens Settings instead
    await group.getByRole('radio', { name: /OpenRouter/ }).click();
    await page.waitForTimeout(1500);
    const dlgCount = await page.getByRole('dialog').count();
    log('after clicking OpenRouter: dialog open =', dlgCount > 0, '| checked now:', JSON.stringify((await read()).map((r) => [r[0], r[1]])));
    if (dlgCount) { log('dialog text:', (await page.getByRole('dialog').innerText()).replace(/\s+/g, ' ').slice(0, 300)); await shot('14-openrouter-opens-settings'); await page.keyboard.press('Escape'); }
    // Local: forced; the request carries it and the daemon answers with the local model
    await group.getByRole('radio', { name: /Local/ }).click();
    const r = await ask('HAI HOW TO USE THIS TOOL ?', 200000);
    log('request provider:', r.entry?.req?.provider, '| answered by:', r.entry?.body?.model, '| ms', r.ms);
    log('stored choice:', await page.evaluate(() => localStorage.getItem('cam-chat-provider')));
    await shot('15-local-answer');
  }

  fs.writeFileSync(`${OUT}/last-run-net.json`, JSON.stringify(net, null, 2));
  await browser.close();
})().catch((e) => { console.error('RUN FAILED', e.message); process.exit(1); });
