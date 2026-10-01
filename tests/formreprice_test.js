// ADDING AI SEARCH IS A PRICE CHANGE, NOT A NEW FORECAST.
//
// Regenerate on the form ran the whole pipeline -- competition scored and
// every ranking checked again -- when the only edit was a Strategy chip, which
// reaches /api/price and nothing else. The form now reprices unless a field a
// measurement pass reads (keywords, markets, site, brand, industry, goals)
// moved. (2026-09-29, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';
const PRICE = {anchor: 6100, base: 6100, step: 50, min_term_months: 6,
  total_volume: 4690, pct_not_ranking: 67,
  handoff: {package: {base: 8100, intermediate: 10200, advanced: 13050}}};

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
    route.fulfill({status: 200, contentType: 'application/json',
                   body: JSON.stringify(url === '/api/price' ? PRICE : {})});
  });
  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod[data-row="0"] .qres');

  await p.evaluate(() => {
    const r = ROWS[0];
    r.kind = 'seo';
    r.data = Object.assign({}, r.data, {strategy: ['Core SEO'], city: ['st. louis, MO'],
      g_city: true, industry: ['Home Services'], goals: ['Leads'], brand: 'Mad Hatter',
      site: 'https://www.madhatterstl.com/', markup: 35});
    r.kw = {all: [{kw: 'chimney sweep'}, {kw: 'dryer vent cleaning'}], total_volume: 900};
    r.result = {pricing: {anchor: 5450, pct_not_ranking: 67, total_volume: 4690,
                          handoff: {package: {base: 5450}}},
      priceReq: {band: 'single_city', adder: 550, zero_ranking: false, addon_markets: 0,
                 markup_pct: 35, pct_not_ranking: 67, total_volume: 4690,
                 industry: 'Home Services', ai_search: false, core_seo: true,
                 national_demand: false, pageone_rank: null},
      settings: JSON.parse(JSON.stringify(r.data)), over: {}};
    r.history = [{when: 'now', resp: 'old', quote: r.result,
                  kw: JSON.parse(JSON.stringify(r.kw))}];
    draw();
    open(0, 'form');
  });
  const label = async () => (await p.textContent('#gen')).trim();
  say('an unchanged form reprices', await label() === 'Reprice', await label());

  // Adding a keyword needs the rank check.
  await p.evaluate(() => { ROWS[0].kw.all.push({kw: 'chimney repair'}); genLabel(); });
  say('a new keyword needs the whole run', await label() === 'Regenerate Quote', await label());
  await p.evaluate(() => { ROWS[0].kw.all.pop(); genLabel(); });

  // A rebuild that returns the same terms with new volume is still a rebuild.
  await p.evaluate(() => { ROWS[0].kw.total_volume = 1500; genLabel(); });
  say('a rebuilt list needs the whole run', await label() === 'Regenerate Quote', await label());
  await p.evaluate(() => { ROWS[0].kw.total_volume = 900; genLabel(); });

  // So does a new market.
  await p.evaluate(() => {
    chipbox(document.querySelector('#fseo [data-chips="city"]'),
            ['st. louis, MO', 'chesterfield, MO']);
  });
  say('a new city needs the whole run', await label() === 'Regenerate Quote', await label());
  await p.evaluate(() => {
    chipbox(document.querySelector('#fseo [data-chips="city"]'), ['st. louis, MO']);
  });

  // Adding AI Search reprices.
  await p.evaluate(() => {
    chipbox(document.querySelector('#fseo [data-chips="strategy"]'), ['Core SEO', 'AI Search']);
  });
  say('adding AI Search reprices', await label() === 'Reprice', await label());

  calls.length = 0;
  await p.click('#gen');
  await p.waitForFunction(() => document.getElementById('scrim').hidden, null, {timeout: 15000});
  const priced = calls.filter(c => c.url === '/api/price');
  say('one pricing call', priced.length === 1, JSON.stringify(calls.map(c => c.url)));
  say('nothing is measured again',
      !calls.some(c => /keywords|refine|metrics|rankings|market_signals|serp/.test(c.url)),
      JSON.stringify(calls.map(c => c.url)));
  const req = (priced[0] || {}).body || {};
  say('priced with AI Search', req.ai_search === true && req.core_seo === true,
      JSON.stringify([req.ai_search, req.core_seo]));
  say('the measured inputs are the run’s own',
      req.adder === 550 && req.pct_not_ranking === 67, JSON.stringify(req));
  const after = await p.evaluate(() => ROWS[0].result.settings.strategy);
  say('the run records the strategy it was priced on',
      JSON.stringify(after) === JSON.stringify(['Core SEO', 'AI Search']), JSON.stringify(after));

  say('no page errors', errs.length === 0, JSON.stringify(errs));
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
