// WITH ADD-ONS, THE MAIN CAMPAIGN IS ONE MARKET.
//
// Valero Law Group: five markets, four add-ons, and the main campaign priced on
// the demand of all five -- so every add-on market was charged twice, once in
// the main price and again as its own campaign. With add-ons the main campaign
// is priced, listed and proposed on the market the build is on; the build still
// crosses every market, because those rows are what the add-on count is
// measured from. With no add-ons nothing changes. (2026-10-02, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";

const row = (kw, vol, city) => ({kw, vol, city});
const ALL = [row('personal injury lawyer seattle', 4000, 'seattle'),
             row('car accident attorney seattle', 2000, 'seattle'),
             row('personal injury lawyer las vegas', 3000, 'las vegas'),
             row('car accident attorney las vegas', 1000, 'las vegas'),
             row('personal injury lawyer reno', 250, 'reno')];
const KW = {head: ALL.slice(0, 2), ultra: ALL.slice(0, 2), competitive: ALL.slice(2),
  long_tail: [], all: ALL, total_volume: 10250,
  grid_cities: ['Seattle, WA', 'Las Vegas, NV', 'Reno, NV']};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errs = [];
  const run = async (suggested) => {
    const p = await b.newPage();
    p.on('pageerror', e => errs.push(e.message));
    const priced = [], props = [];
    const json = (route, body) =>
      route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    await p.route('**/api/**', route => {
      const url = new URL(route.request().url()).pathname;
      let bd = {};
      try { bd = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
      if (url === '/api/keywords' || url === '/api/refine') return json(route, KW);
      if (url === '/api/metrics') return json(route, {adder: 0});
      // Seattle ranks; nothing else does.
      if (url === '/api/rankings')
        return json(route, {results: (bd.batch || []).map(x => ({
          kw: x.kw, pos: /seattle/.test(x.kw) ? 3 : 'Not Found',
          ranked_top: /seattle/.test(x.kw), error: false}))});
      if (url === '/api/addon_suggestion')
        return json(route, {suggested, basis: '', measured: 3, covered: 1});
      if (url === '/api/price') {
        priced.push(bd);
        return json(route, {anchor: 2950, min_term_months: 6,
          total_volume: bd.total_volume, pct_not_ranking: bd.pct_not_ranking,
          addon_markets: bd.addon_markets || 0,
          client_addon_per_market: {base: 2655},
          handoff: {package: {base: 2950}, margin_pct: 0.35,
                    addon_markets: bd.addon_markets || 0,
                    addon_market_price: {base: 2655}, addon_market_discount_pct: 10}});
      }
      if (url === '/api/proposal.docx') {
        props.push(bd);
        return route.fulfill({status: 200, body: 'PK',
          contentType: 'application/octet-stream'});
      }
      if (url === '/api/serp_recommend') return json(route, {});
      if (url === '/api/lists')
        return json(route, {industries: ['Legal - Personal Injury'], goals: [],
                            strategies: ['Core SEO'], rep_strategies: []});
      return json(route, {services: [], regions: [], geo_anchor: {}});
    });
    await p.goto(BASE + '/adtini/forecast?new=1&product=seo', {waitUntil: 'domcontentloaded'});
    await p.evaluate(() => {
      const d = ROWS[0].data;
      d.brand = 'Valero Law Group'; d.site = 'valero.example';
      d.focus = ['personal injury lawyer'];
      d.g_city = true; d.g_county = false;
      d.city = ['Seattle, WA', 'Las Vegas, NV', 'Reno, NV'];
      d.expand = 0;
      load(formOf(ROWS[0]), d);
      kbLoad(ROWS[0]);
    });
    await p.click('#kwBuilder');
    await p.click('#kbBuild');
    await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent));
    await p.click('#gen');
    await p.click('#gen');
    await p.waitForSelector('.prod[data-row="0"] .qres', {state: 'attached'});
    const out = await p.evaluate(() => {
      const cards = [...document.querySelectorAll('.prod[data-row="0"] .pv')]
        .map(x => x.querySelector('small').textContent + ': ' + x.querySelector('b').textContent);
      return {main: cards.find(c => /^Main market/.test(c)),
              addons: cards.find(c => /^Add-on markets/.test(c)),
              ownRow: [...document.querySelectorAll('.prod[data-row="0"] .pvaddon .pv small')].map(x => x.textContent),
              keywords: cards.find(c => /^Keywords/.test(c)),
              headline: ROWS[0].result.headline,
              listed: [...document.querySelectorAll('.prod[data-row="0"] .pvkw td:first-child')]
                .map(x => x.textContent)};
    });
    await p.evaluate(() => downloadProposal(0, 'docx'));
    await p.waitForFunction(() => true);
    await p.waitForTimeout(300);
    // Reprice with the count set to none: back to the whole build.
    await p.evaluate(async () => {
      ROWS[0].cfg = Object.assign({}, ROWS[0].cfg, {addon_markets: '0'});
      ROW = 0;
      await reprice();
    });
    await p.close();
    out.req = priced[0];
    out.reReq = priced[priced.length - 1];
    out.prop = props[0];
    return out;
  };

  const four = await run(2);
  const none = await run(0);

  const want = {
    'addons.pricedOnTheMainMarketsDemand': [four.req.total_volume, 6000],
    'addons.rankingShareIsTheMainMarkets': [four.req.pct_not_ranking, 0],
    'addons.wholeBuildKeptForReprice': [four.req.all_volume, 10250],
    'addons.mainMarketCard': [four.main, 'Main market: Seattle, WA'],
    'addons.addonMarketsCard': [four.addons, 'Add-on markets: Las Vegas, NV, Reno, NV'],
    // ADD-ONS GET THEIR OWN ROW. (2026-10-02, Kiri)
    'addons.ownRow': [(four.ownRow || []).join('|'), 'Add-on pricing|Main market|Add-on markets'],
    'addons.keywordCardCountsTheMainMarket': [four.keywords, 'Keywords: 2 terms'],
    'addons.headlineCountsTheMainMarket': [/· 2 terms ·/.test(four.headline || ''), true],
    'addons.listShowsTheMainMarket': [four.listed,
      ['personal injury lawyer seattle', 'car accident attorney seattle']],
    'addons.proposalKeywords': [(four.prop.kw.all || []).map(x => x.kw),
      ['personal injury lawyer seattle', 'car accident attorney seattle']],
    'addons.proposalTable': [(four.prop.table || []).length, 2],
    'addons.proposalNamesMain': [four.prop.main_market, 'Seattle, WA'],
    'addons.proposalNamesAddOns': [four.prop.addon_market_names, ['Las Vegas, NV', 'Reno, NV']],
    'addons.repriceToNoneIsTheWholeBuild': [four.reReq.total_volume, 10250],
    'addons.repriceToNoneRankingIsTheWholeBuild': [four.reReq.pct_not_ranking, 60],
    'none.pricedOnTheWholeBuild': [none.req.total_volume, 10250],
    'none.rankingShareIsTheWholeBuild': [none.req.pct_not_ranking, 60],
    'none.noMainMarketCard': [none.main, undefined],
    'none.everyKeywordListed': [none.listed.length, 5],
    'none.proposalNamesNoMarket': [none.prop.main_market, ''],
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
