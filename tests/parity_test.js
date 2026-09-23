// THE NEW TAB MUST PRICE WHAT THE OLD TAB PRICES.
//
// The adtini tab re-implements the step orchestration that the SEO tab has
// carried for months. Same client, same answers, same stubs: what reaches
// /api/price has to match, field for field. Anything that differs here is
// drift introduced by the new wrapper, not a pricing decision. (2026-09-15)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";

const SEEDS = ['emergency dentist', 'dental implants'];
const CITY = 'Boca Raton, FL';
const KW = {
  head: [{kw: 'dental implants boca raton', vol: 3600}],
  ultra: [{kw: 'dental implants boca raton', vol: 3600}],
  competitive: [{kw: 'emergency dentist boca raton', vol: 1900}],
  long_tail: [{kw: 'affordable dental implants near me', vol: 210}],
  all: [{kw: 'dental implants boca raton', vol: 3600},
        {kw: 'emergency dentist boca raton', vol: 1900},
        {kw: 'affordable dental implants near me', vol: 210}],
  services: [{kw: 'dental implants'}], total_volume: 5710, grid: true,
};
const RANK = kw => ({kw, pos: kw.includes('implants boca') ? 4 : 'Not Found',
                     ranked_top: kw.includes('implants boca'), error: false});

const stub = async (p, calls) => {
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  await p.route('**/api/**', route => {
    const url = new URL(route.request().url()).pathname;
    let bd = {};
    try { bd = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
    if (url === '/api/price') calls.price.push(bd);
    if (url === '/api/metrics') calls.metrics.push(bd);
    if (url === '/api/rankings') calls.rankings.push(bd);
    if (url === '/api/keywords' || url === '/api/refine') return json(route, KW);
    if (url === '/api/metrics')
      return json(route, {adder: 550, score: 41, cpc: {}, kd: {}, pageone_rank: 22});
    if (url === '/api/rankings')
      return json(route, {results: (bd.batch || []).map(x => RANK(x.kw)), paa: [], rivals: []});
    if (url === '/api/price')
      return json(route, {anchor: 5450, base: 5450, step: 650, min_term_months: 6,
        total_volume: bd.total_volume, pct_not_ranking: bd.pct_not_ranking,
        client_tiers: {base: 5450, intermediate: 6450, advanced: 7750},
        hard_true_tiers: {base: 3543, intermediate: 4193, advanced: 5038},
        handoff: {package: {base: 5450, intermediate: 6450, advanced: 7750},
                  margin_pct: bd.markup_pct, addon_markets: bd.addon_markets || 0}});
    if (url === '/api/lists')
      return json(route, {industries: ['Health Services - Pediatrics'], goals: ['Phone Calls'],
                          strategies: ['Core SEO'], rep_strategies: []});
    if (url === '/api/quotes' || url === '/api/quotes/status')
      return json(route, {enabled: false, quotes: []});
    if (url === '/api/config') return json(route, {geo_anchor: {}, zero_ranking_tiers: [],
      volume_brackets: [], geo_pct_tiers: [], addon_volume_discount_tiers: [],
      competitive_adder: {}, bid_score_breaks: [5, 15], vol_add_ramp: [40, 60],
      default_markup_pct: 35, min_term_months: 6});
    return json(route, {services: [], regions: [], recommended: null, ready: false});
  });
};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errs = [];

  // ---------------- the legacy tab ----------------
  const legacyCalls = {price: [], metrics: [], rankings: []};
  const lp = await b.newPage();
  lp.on('pageerror', e => errs.push('legacy: ' + e.message));
  await stub(lp, legacyCalls);
  await lp.goto(BASE + '/legacy', { waitUntil: 'domcontentloaded' });
  await lp.evaluate(([seeds, city]) => {
    document.getElementById('brand').value = 'Sage Dental';
    (document.getElementById('sites_in') || {}).value = '';
    stores.sites = ['mysagedental.com'];
    stores.kw = seeds.slice();
    stores.geo = [city];
    stores.industry = ['Health Services - Pediatrics'];
    document.getElementById('geo_scope').value = 'single_city';
    const auto = document.getElementById('autoExpand');
    if (auto) auto.checked = false;                 // no expansion on either side
    const mk = document.getElementById('markup');
    if (mk) mk.value = '35';
  }, [SEEDS, CITY]);
  await lp.click('#step1');
  await lp.waitForSelector('#step2', { timeout: 30000 });
  await lp.waitForFunction(() => typeof ST !== 'undefined' && ST.kw && (ST.kw.all || []).length,
    { timeout: 30000 });
  await lp.click('#step2');
  await lp.waitForSelector('#step3', { timeout: 30000 });
  await lp.waitForFunction(() => typeof ST !== 'undefined' && ST.adder != null, { timeout: 30000 });
  await lp.click('#step3');
  await lp.waitForSelector('#step4', { timeout: 40000 });
  await lp.waitForFunction(() => typeof ST !== 'undefined' && (ST.table || []).length,
    { timeout: 40000 });
  await lp.click('#step4');
  await lp.waitForFunction(() => typeof ST !== 'undefined' && ST.pricing, { timeout: 30000 });

  // ---------------- the adtini tab ----------------
  const adtiniCalls = {price: [], metrics: [], rankings: []};
  const ap = await b.newPage();
  ap.on('pageerror', e => errs.push('adtini: ' + e.message));
  await stub(ap, adtiniCalls);
  await ap.goto(BASE + '/adtini/forecast?new=1&product=seo', { waitUntil: 'domcontentloaded' });
  await ap.evaluate(([seeds, city]) => {
    const d = ROWS[0].data;
    d.brand = 'Sage Dental'; d.site = 'mysagedental.com';
    d.focus = seeds.slice();
    d.g_city = true; d.city = [city];
    d.industry = ['Health Services - Pediatrics'];
    d.strategy = ['Core SEO'];
    d.expand = 0; d.national = 0; d.markup = '35';
    load(formOf(ROWS[0]), d);
    kbLoad(ROWS[0]);
  }, [SEEDS, CITY]);
  await ap.click('#kwBuilder');
  await ap.click('#kbBuild');
  await ap.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent),
    { timeout: 30000 });
  await ap.click('#gen');
  await ap.click('#gen');
  // Attached, not visible: a finished build lands on History now.
  await ap.waitForSelector('.prod[data-row="0"] .qres',
                           { state: 'attached', timeout: 40000 });

  const L = legacyCalls.price[legacyCalls.price.length - 1] || {};
  const A = adtiniCalls.price[adtiniCalls.price.length - 1] || {};
  const LM = legacyCalls.metrics[0] || {};
  const AM = adtiniCalls.metrics[0] || {};
  const LR = legacyCalls.rankings[0] || {};
  const AR = adtiniCalls.rankings[0] || {};
  const same = k => [A[k], L[k]];

  const want = {
    // step 2 asks the same question
    'metrics.head': [(AM.head || []).join(','), (LM.head || []).join(',')],
    'metrics.geo': [(AM.geo_values || []).join(','), (LM.geo_values || []).join(',')],
    'metrics.scope': [AM.geo_scope, LM.geo_scope],
    // step 3 measures the same terms
    'rankings.batch': [(AR.batch || []).map(x => x.kw).join(','),
                       (LR.batch || []).map(x => x.kw).join(',')],
    'rankings.domain': [AR.domain, LR.domain],
    // step 4 prices on the same numbers
    'price.band': same('band'),
    'price.adder': same('adder'),
    'price.zero_ranking': same('zero_ranking'),
    'price.pct_not_ranking': same('pct_not_ranking'),
    'price.total_volume': same('total_volume'),
    'price.markup_pct': same('markup_pct'),
    'price.addon_markets': same('addon_markets'),
    'price.industry': same('industry'),
    'price.national_demand': [!!A.national_demand, !!L.national_demand],
    'price.pageone_rank': same('pageone_rank'),
  };

  let bad = 0;
  for (const k of Object.keys(want)) {
    const [got, exp] = want[k];
    const ok = JSON.stringify(got) === JSON.stringify(exp);
    if (!ok) bad++;
    console.log((ok ? '  ok   ' : '  DRIFT ') + k
      + (ok ? `  (${JSON.stringify(exp)})` : `  adtini ${JSON.stringify(got)} vs legacy ${JSON.stringify(exp)}`));
  }
  await b.close();
  console.log('\nerrors: ' + (errs.length ? errs.join('; ') : 'none'));
  console.log(`${Object.keys(want).length} checks, ${bad} drifted`);
  process.exit(bad ? 1 : 0);
})();
