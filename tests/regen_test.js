// A FULL RUN IS ALWAYS ONE PRESS AWAY, AND REPRICE ASKS THE ADD-ON COUNT AGAIN.
//
// With nothing measured changed the main button only reprices, so a quote
// could not be re-run to pick up new add-on rules. Reprice now re-asks the
// add-on recommendation off the run's ranks, and a Regenerate button sits
// beside it. (2026-10-02, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';
const PRICE = {anchor: 1850, base: 1850, min_term_months: 6,
  handoff: {package: {base: 3350, intermediate: 4400, advanced: 5500}}};

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const errs = [], calls = [];
  p.on('pageerror', e => errs.push(e.message));
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  await p.route('**/api/**', route => {
    const url = new URL(route.request().url()).pathname;
    let body = {};
    try { body = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
    calls.push({url, body});
    const out = url === '/api/price' ? PRICE
      : url === '/api/addon_suggestion'
        ? {suggested: 2, markets_absent: ['Paris, TX', 'Antlers, OK'], confident: true,
           basis: 'contiguous region — 2 over 60 miles from Sherman, TX: a, b.'}
      : {};
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(out)});
  });
  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod[data-row="0"] .qres');
  await p.evaluate(() => {
    const r = ROWS[0];
    r.kind = 'seo';
    r.data = Object.assign({}, r.data, {strategy: ['Core SEO'], g_city: true,
      city: ['Sherman, TX', 'Paris, TX', 'Antlers, OK'], brand: 'Texoma',
      site: 'https://www.smiletexoma.com/', markup: 35});
    r.band = 'contiguous_region';
    r.kw = {all: [{kw: 'dentist sherman tx'}], total_volume: 930,
            grid_cities: ['Sherman, TX']};
    r.result = {pricing: {anchor: 1850, handoff: {package: {base: 3350}}},
      priceReq: {band: 'contiguous_region', adder: 50, addon_markets: 15, markup_pct: 35,
                 pct_not_ranking: 86, total_volume: 930, core_seo: true},
      table: [{kw: 'dentist sherman tx', pos: 'Not Found'},
              {kw: 'dentist paris tx', pos: 'Not Found'}],
      settings: JSON.parse(JSON.stringify(r.data)), over: {}};
    r.history = [{when: 'now', resp: 'old', quote: r.result,
                  kw: JSON.parse(JSON.stringify(r.kw))}];
    draw();
    open(0, 'form');
  });
  say('reprice is the main button', (await p.textContent('#gen')).trim() === 'Reprice');
  say('regenerate sits beside it', await p.isVisible('#regen'));

  calls.length = 0;
  await p.click('#gen');
  await p.waitForFunction(() => document.getElementById('scrim').hidden, null, {timeout: 15000});
  const asked = calls.find(c => c.url === '/api/addon_suggestion');
  say('reprice asks the add-on count again', !!asked, JSON.stringify(calls.map(c => c.url)));
  say('with the scope and main market',
      asked && asked.body.band === 'contiguous_region' && asked.body.main === 'Sherman, TX',
      JSON.stringify((asked || {}).body));
  const priced = calls.find(c => c.url === '/api/price');
  say('priced on the new count', priced && priced.body.addon_markets === 2,
      JSON.stringify((priced || {}).body));
  say('nothing is measured again',
      !calls.some(c => /keywords|refine|metrics|rankings|serp/.test(c.url)));

  // A Config count still wins.
  await p.evaluate(() => { ROWS[0].cfg = {addon_markets: '1'}; open(0, 'form'); });
  calls.length = 0;
  await p.click('#gen');
  await p.waitForFunction(() => document.getElementById('scrim').hidden, null, {timeout: 15000});
  const p2 = calls.find(c => c.url === '/api/price');
  say('config count wins', p2 && p2.body.addon_markets === 1, JSON.stringify((p2 || {}).body));
  say('and is not re-asked', !calls.some(c => c.url === '/api/addon_suggestion'));

  // Regenerate runs the whole forecast.
  await p.evaluate(() => { ROWS[0].cfg = {}; window.__gen = 0;
                           window.generate = () => { window.__gen++; }; open(0, 'form'); });
  await p.click('#regen');
  say('regenerate runs the forecast', await p.evaluate(() => window.__gen) === 1);

  // Hidden when the main button already regenerates.
  await p.evaluate(() => { ROWS[0].kw.all.push({kw: 'dentist denison tx'}); genLabel(); });
  say('hidden when the main button regenerates', !(await p.isVisible('#regen')));

  say('no page errors', errs.length === 0, JSON.stringify(errs));
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
