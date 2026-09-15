// AN UNMEASURED RANK CHECK IS NOT A CLIENT WITH NO PRESENCE.
//
// The add-on market count is a recommendation built on whether each market is
// new to the client. When every rank check errors, "ranking in 0 of 4 markets"
// is absence of measurement, not evidence of absence — and charging a campaign
// per market on it is a real price. A contiguous region says so too: adjacent
// markets are already inside the anchor. (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";

const KW = {head: [{kw: 'vein treatment', vol: 40500}],
  ultra: [{kw: 'vein treatment', vol: 40500}], competitive: [], long_tail: [],
  all: [{kw: 'vein treatment knox county', vol: 40500, vol_scope: 'broader',
         vol_area: 'United States'},
        {kw: 'vein clinic knox county', vol: 0}],
  total_volume: 40500};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errs = [];
  const run = async (rankPos) => {
    const p = await b.newPage();
    p.on('pageerror', e => errs.push(e.message));
    const calls = [];
    const json = (route, body) =>
      route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    await p.route('**/api/**', route => {
      const url = new URL(route.request().url()).pathname;
      let bd = {};
      try { bd = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
      calls.push(url);
      if (url === '/api/keywords' || url === '/api/refine') return json(route, KW);
      if (url === '/api/metrics') return json(route, {adder: 0});
      if (url === '/api/rankings')
        return json(route, {results: (bd.batch || []).map(x => ({
          kw: x.kw, pos: rankPos, ranked_top: false, error: rankPos === '—'}))});
      if (url === '/api/addon_suggestion')
        return json(route, {suggested: 3, basis: 'ranking in only 0 of 4 markets, so the rest'
          + ' are a campaign from scratch each', confident: true});
      if (url === '/api/price')
        return json(route, {anchor: 2950, min_term_months: 6,
          handoff: {package: {base: 2950}, margin_pct: 0.35,
                    addon_markets: bd.addon_markets || 0,
                    addon_market_price: {base: 2655}, addon_market_discount_pct: 10}});
      if (url === '/api/serp_recommend') return json(route, {recommended: 'vein treatment knox county'});
      if (url === '/api/serp_queue') return json(route, {task_id: 't', device: 'desktop'});
      if (url === '/api/serp_fetch') return json(route, {ready: false});
      if (url === '/api/lists')
        return json(route, {industries: ['Health Services - Vascular & Vein'], goals: [],
                            strategies: ['Core SEO'], rep_strategies: []});
      return json(route, {services: [], regions: [], geo_anchor: {}});
    });
    await p.goto(BASE + '/adtini/forecast?new=1&product=seo', {waitUntil: 'domcontentloaded'});
    // four counties, one region
    await p.evaluate(() => {
      const d = ROWS[0].data;
      d.brand = 'Vein Clinic'; d.site = 'veins.example';
      d.focus = ['vein treatment'];
      d.g_city = false; d.g_county = true;
      d.county = ['Knox County, TN', 'Cumberland County, TN',
                  'Hamblen County, TN', 'Bradley County, TN'];
      d.expand = 0;
      load(formOf(ROWS[0]), d);
      kbLoad(ROWS[0]);          // the seed box reads the row
    });
    await p.click('#kwBuilder');
    await p.click('#kbBuild');
    await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent));
    await p.click('#gen');
    await p.click('#gen');
    await p.waitForSelector('.prod[data-row="0"] .qres');
    const out = await p.evaluate(() => {
      const cards = [...document.querySelectorAll('.prod[data-row="0"] .pv')]
        .map(x => x.querySelector('small').textContent + ': ' + x.querySelector('b').textContent);
      return {addon: cards.find(c => /^Add-on markets/.test(c)),
              demand: cards.find(c => /^Measured demand/.test(c)),
              ranking: cards.find(c => /^Ranking/.test(c)),
              priced: (JSON.parse(JSON.stringify(ROWS[0].result.pricing.handoff))).addon_markets};
    });
    await p.close();
    out.asked = calls.includes('/api/addon_suggestion');
    return out;
  };

  const errored = await run('—');          // every rank check failed
  const measured = await run(12);          // measured, and not in the top set

  const want = {
    'errored.noRecommendationAsked': [errored.asked, false],
    'errored.pricedWithoutAddOns': [errored.priced, 0],
    'errored.saysWhyThereIsNoCount': [errored.addon,
      'Add-on markets: none · no market count — every rank check errored, so nothing'
      + ' says whether these markets are new to them'],
    'errored.rankingIsUnmeasured': [/unmeasured/.test(errored.ranking || ''), true],
    'measured.recommendationAsked': [measured.asked, true],
    'measured.pricedOnTheRecommendation': [measured.priced, 3],
    'measured.namesTheRegionCaveat': [/contiguous region — adjacent markets are already/
      .test(measured.addon || ''), true],
    'both.widerAreaNamedOnDemand': [/answered from a wider area/.test(measured.demand || ''), true],
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
  console.log('\nerrors: ' + (errs.length ? errs.join('; ') : 'none'));
  console.log(`${Object.keys(want).length} checks, ${bad} failed`);
  process.exit(bad || errs.length ? 1 : 0);
})();
