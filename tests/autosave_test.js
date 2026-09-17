// A RUN SAVES ITSELF.
//
// Saving used to be switched on only while loading a client, so a quote started
// from New quote priced and then vanished. The status endpoint decides it now,
// the row says what happened, and the order number follows the client.
// (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";

const KW = {head: [{kw: 'dental implants boca raton', vol: 3600}],
  ultra: [{kw: 'dental implants boca raton', vol: 3600}], competitive: [], long_tail: [],
  all: [{kw: 'dental implants boca raton', vol: 3600}], total_volume: 3600};

const run = async (b, enabled) => {
  const p = await b.newPage();
  const calls = [], saved = [], meta = [];
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  await p.route('**/api/**', route => {
    const url = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let bd = {};
    try { bd = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
    calls.push(method + ' ' + url);
    if (url === '/api/quotes/status')
      return json(route, {enabled, detail: enabled ? 'Connected to Postgres — saving enabled.'
                                                   : 'No DATABASE_URL set — attach a Postgres instance in Render.'});
    if (url === '/api/quotes' && method === 'POST') { saved.push(bd); return json(route, {ok: true, id: 77}); }
    if (/^\/api\/quotes\/\d+$/.test(url) && method === 'PUT') { saved.push(bd); return json(route, {ok: true}); }
    if (url === '/api/adtini/client_meta') { meta.push(bd); return json(route, {ok: true}); }
    if (url === '/api/keywords' || url === '/api/refine') return json(route, KW);
    if (url === '/api/metrics') return json(route, {adder: 550});
    if (url === '/api/rankings')
      return json(route, {results: (bd.batch || []).map(x => ({kw: x.kw, pos: 4, ranked_top: true}))});
    if (url === '/api/price')
      return json(route, {anchor: 5450, min_term_months: 6, total_volume: 3600,
        pct_not_ranking: 0, handoff: {package: {base: 5450}, margin_pct: 35}});
    if (url === '/api/lists')
      return json(route, {industries: ['Health Services - Pediatrics'], goals: [],
                          strategies: ['Core SEO'], rep_strategies: []});
    if (url === '/api/serp_fetch') return json(route, {ready: false});
    return json(route, {services: [], regions: [], recommended: null});
  });

  // a brand-new quote, the way New quote starts one
  await p.goto(BASE + '/adtini/forecast?new=1&product=seo&order=56311',
    {waitUntil: 'domcontentloaded'});
  await p.evaluate(() => {
    const d = ROWS[0].data;
    d.brand = 'Sage Dental'; d.site = 'mysagedental.com';
    d.focus = ['dental implants'];
    d.g_city = true; d.city = ['Boca Raton, FL'];
    d.expand = 0; d.markup = '35';
    load(formOf(ROWS[0]), d);
    kbLoad(ROWS[0]);
  });
  await p.click('#kwBuilder');
  await p.click('#kbBuild');
  await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent),
    {timeout: 30000});
  await p.click('#gen');
  await p.click('#gen');
  // Attached, not visible: a finished build lands on History now.
  await p.waitForSelector('.prod[data-row="0"] .qres',
                          {state: 'attached', timeout: 30000});
  await p.waitForFunction(() =>
    /Saved|Not saved/.test(document.querySelector('.prod[data-row="0"] .rowmsg').textContent),
    {timeout: 10000});
  const out = await p.evaluate(() => ({
    note: document.querySelector('.prod[data-row="0"] .rowmsg')
      .textContent.split(' · Capturing')[0].trim(),
    saveId: ROWS[0].saveId || null,
  }));
  // a second run updates the same record rather than making another.
  // The build landed on History, and the row's buttons live on Details.
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="details"]');
  await p.click('[data-open="0"][data-view="form"]');
  await p.click('#gen');
  await p.waitForFunction(() =>
    document.querySelectorAll('.prod[data-row="0"] .hist tbody tr').length >= 2
    || document.getElementById('scrim').hidden, {timeout: 30000});
  await p.waitForTimeout(1200);
  await p.close();
  return {calls, saved, meta, errs, ...out};
};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const on = await run(b, true);
  const off = await run(b, false);

  const want = {
    'on.savedOnTheFirstRun': [on.saved.length >= 1, true],
    'on.savedUnderTheClient': [(on.saved[0] || {}).client, 'Sage Dental'],
    'on.savedAsTheSeoTool': [(on.saved[0] || {}).tool, 'seo'],
    'on.nameCarriesTheQuoteId': [/^Search Engine Optimization — Q-\d+$/.test((on.saved[0] || {}).name || ''), true],
    'on.payloadCarriesTheQuote': [!!((on.saved[0] || {}).payload || {}).adtini
      && !!((on.saved[0] || {}).payload || {}).pricing, true],
    // The row carries the save AND what happened to the capture, because a
    // capture that never came back used to say nothing at all.
    'on.rowSaysItSaved': [/^Saved to Sage Dental · Q-\d+\./.test(on.note), true],
    'on.rowSaysWhyNoCapture': [/SERP not captured — .+\.$/.test(on.note), true],
    'on.orderNumberFollowsTheClient': [(on.meta[0] || {}).order_no, '56311'],
    'on.secondRunUpdatesTheSameRecord':
      [on.calls.filter(c => c === 'PUT /api/quotes/77').length >= 1, true],
    'on.onlyOneRecordCreated':
      [on.calls.filter(c => c === 'POST /api/quotes').length, 1],
    // saving off: nothing is posted, and the row says why
    'off.nothingPosted': [off.saved.length, 0],
    'off.rowSaysWhy': [off.note.split(' · SERP')[0],
      'Not saved — saving is off for this deploy. No DATABASE_URL set — attach a '
      + 'Postgres instance in Render.'],
    'errors': [[...on.errs, ...off.errs].join('; '), ''],
  };

  let bad = 0;
  for (const k of Object.keys(want)) {
    const [got, exp] = want[k];
    const ok = JSON.stringify(got) === JSON.stringify(exp);
    if (!ok) bad++;
    console.log((ok ? '  ok   ' : '  FAIL ') + k
      + (ok ? '' : `  got ${JSON.stringify(got)} want ${JSON.stringify(exp)}`));
  }
  await b.close();
  console.log(`\n${Object.keys(want).length} checks, ${bad} failed`);
  process.exit(bad ? 1 : 0);
})();
