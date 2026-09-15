// THE QUOTES WE HAVE ARE THE QUOTES ON THE PAGE.
//
// One row per client on the list, however many quotes it holds; opening a
// client shows each saved quote as its own row. The quotes saved by the SEO and
// Reputation tabs were written before this page existed, so they are read off
// those shapes rather than ignored. (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";

const CLIENTS = {enabled: true, clients: [
  {client: 'Drainify', order: '56310', planner: 'Kiri', partner: 'ADX Communications',
   status: 'In Progress', built: '2026-09-10', seo: 2, orm: 0,
   seoStrat: ['Core SEO', 'AI Search'], ormStrat: [],
   quotes: [{id: 11, name: 'Drainify — 2026-09-04', updated_at: '2026-09-10T10:00:00'},
            {id: 12, name: 'Drainify UK — 2026-09-04', updated_at: '2026-09-09T10:00:00'}]},
  {client: 'Ski Barn', order: '', planner: 'Stacy', partner: 'Rock Paper Scissors',
   status: 'Pending', built: '2026-08-21', seo: 0, orm: 1,
   seoStrat: [], ormStrat: ['Reactive', 'Proactive'],
   quotes: [{id: 21, name: 'Ski Barn - 8/5/2026 - reactive + proactive',
             updated_at: '2026-08-21T09:00:00'}]},
]};

// what the SEO tab saves
const LEGACY_SEO = {id: 11, name: 'Drainify — 2026-09-04', client: 'Drainify', tool: 'seo',
  updated_at: '2026-09-10T10:00:00', payload: {
    inputs: {brand: 'Drainify', domain: 'drainify.io', keywords: ['drain unblocking', 'cctv survey'],
             negatives: ['jobs'], industries: ['Home Services'], strategy: 'Core SEO + AI Search',
             geo_values: ['Manchester, UK'], geo_scope: 'single_city', addon_markets: 3,
             markup_pct: 0.35, past_seo: true, past_seo_detail: 'agency before us',
             client_budget: 4000, goal: 'Information Requests'},
    kw: {all: [{kw: 'drain unblocking manchester', vol: 2200},
               {kw: 'cctv drain survey manchester', vol: 480}]},
    table: [{kw: 'drain unblocking manchester', pos: 7, ranked_top: true},
            {kw: 'cctv drain survey manchester', pos: 'Not Found'}],
    cpc: {'drain unblocking manchester': 9.4}, kd: {score: 41}, adder: 250,
    totalVol: 2680, pctNotRanking: 50,
    pricing: {anchor: 3800, base: 3800, min_term_months: 6, total_volume: 2680,
              pct_not_ranking: 50, competitive_adder: 250,
              handoff: {package: {base: 3800, intermediate: 5250, advanced: 6700},
                        core_seo_price: {base: 3800}, margin_pct: 0.35,
                        addon_markets: 3, addon_market_price: {base: 900},
                        partner_hard_cost: {base: 2470}, margin_dollars: {base: 1330},
                        ai_search_pct: 57, ai_search_price: {base: 2166}}},
    serp: {img: 'data:image/png;base64,iVBORw0KGgo='}}};

// what the Reputation tab saves
const LEGACY_REP = {id: 21, name: 'Ski Barn - 8/5/2026 - reactive + proactive',
  client: 'Ski Barn', tool: 'rep', updated_at: '2026-08-21T09:00:00', payload: {
    form: {brand: 'Ski Barn', domain: 'skibarn.com', nReviews: '31', nLocations: '2',
           nArtStd: '3', nArtPrem: '1', volume: '2400', clientMargin: '0.35',
           useReviews: true, useArticles: true, useSearchBundle: true, useGeo: true,
           campaign: 'bundle'},
    rep_totals: {monthly: 12550, one_time: 95250, total: 133000},
    quote: {lines: [{label: 'Review Removals', total: 3100},
                    {label: 'Reactive · Search Protection', total: 9450}],
            totals: {monthly: 12550, removals_max: 95250, total: 133000},
            handoff: {reviews_count: 31, price_per_review_removal: 100, locations: 2,
                      search_volume: 2400, monthly_budget: 12550,
                      strategy: ['Review Removals', 'Site/Article Removals', 'Reactive', 'Proactive']}},
    scan: {data: {terms: {rows: [{keyword: 'ski barn reviews', volume: 390}]},
                  serp: {rows: [{pos: 3, domain: 'yelp.com'}]},
                  locations: {locations: [{title: 'Ski Barn Wayne', reviews: 412},
                                          {title: 'Ski Barn Paramus', reviews: 88}]}},
           negDone: [{neg_1_2: 21}, {neg_1_2: 10, neg_1: 6}]}}};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  const errs = [], posted = [];
  p.on('pageerror', e => errs.push(e.message));
  const json = (route, body) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

  await p.route('**/api/**', route => {
    const url = new URL(route.request().url()).pathname;
    if (url === '/api/adtini/clients') return json(route, CLIENTS);
    if (url === '/api/quotes/11') return json(route, LEGACY_SEO);
    if (url === '/api/quotes/12') {
      const older = JSON.parse(JSON.stringify(LEGACY_SEO));
      older.id = 12; older.name = 'Drainify UK — 2026-09-04';
      delete older.payload.pricing.handoff;           // saved before the handoff existed
      Object.assign(older.payload.pricing, {
        client_tiers: {base: 3800, intermediate: 5250, advanced: 6700},
        ai_search: {client_total: {base: 5966, intermediate: 8242, advanced: 10516},
                    geo_pct: 57},
        client_addon_per_market: {base: 900},
        addon_discount_pct: 10,
        hard_true_tiers: {base: 2470, intermediate: 3412, advanced: 4355},
        agency_profit_tiers: {base: 1330},
        margin_pct_of_gross: 35});
      return json(route, older);
    }
    if (url === '/api/quotes/21') return json(route, LEGACY_REP);
    if (url === '/api/adtini/client_meta') {
      posted.push(JSON.parse(route.request().postData() || '{}'));
      return json(route, {ok: true});
    }
    return json(route, {});
  });

  // ---------------- the list is the saved quotes ----------------
  await p.goto(BASE + '/adtini', { waitUntil: 'domcontentloaded' });
  await p.waitForFunction(() =>
    [...document.querySelectorAll('tbody td')].some(td => /Drainify/.test(td.textContent)));
  const home = await p.evaluate(() => {
    const cells = tr => [...tr.children].map(td => td.textContent.trim());
    const rows = [...document.querySelectorAll('tbody tr')];
    const R = {rows: rows.length, first: cells(rows[0])};
    R.noSamples = !rows.some(t => /Sage Dental|Junk Bee Gone/.test(t.textContent));
    R.plannerFromStore = rows[1].querySelector('select.who').value;
    R.partnerFromStore = rows[0].querySelector('input.cell').value;
    R.countPerProduct = [...rows[0].querySelectorAll('.tag')].map(t => t.textContent.trim());
    // an edit goes back to the store, against that client
    const sel = rows[0].querySelector('select.stat');
    sel.value = 'Complete';
    sel.dispatchEvent(new Event('change', {bubbles: true}));
    return R;
  });
  await p.waitForFunction(() => true);

  // ---------------- a client's quotes are its rows ----------------
  await p.goto(BASE + '/adtini/forecast?client=Drainify&order=56310', { waitUntil: 'domcontentloaded' });
  await p.waitForFunction(() => document.querySelectorAll('.prod').length === 2);
  const seo = await p.evaluate(() => {
    const R = {};
    R.rows = [...document.querySelectorAll('.prod > h4')].map(h => h.textContent.replace(/\s+/g, ' ').trim());
    const q = document.querySelector('.prod[data-row="0"] .qres');
    R.headline = q.querySelector('summary').textContent.trim();
    R.tiles = [...q.querySelectorAll('.qtile')].map(t =>
      t.querySelector('small').textContent + ' ' + t.querySelector('b').textContent);
    R.planner = [...q.querySelectorAll('.pview .pv')]
      .map(x => x.querySelector('small').textContent + ': ' + x.querySelector('b').textContent);
    R.serp = !!q.querySelector('.pvserp img');
    // the form carries what the quote was built on
    document.querySelector('[data-open="0"][data-view="form"]').click();
    R.brand = document.querySelector('#fseo [data-k="brand"]').value;
    R.city = [...document.querySelectorAll('#fseo [data-chips="city"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    R.cityShown = !document.querySelector('#fseo [data-geo="g_city"]').hidden;
    R.countryHidden = document.querySelector('#fseo [data-geo="g_country"]').hidden;
    R.focus = [...document.querySelectorAll('#fseo [data-chips="focus"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    R.pastShown = [...document.querySelectorAll('#fseo [data-past]')].filter(x => !x.hidden).length;
    R.markets = document.querySelector('#fseo [data-k="markets"]').value;
    document.getElementById('close').click();
    // the second quote on this client was saved before the handoff block
    const q2 = document.querySelector('.prod[data-row="1"] .qres');
    q2.querySelectorAll('.qfold').forEach(f => f.open = true);
    const ordFold = [...q2.querySelectorAll('.qfold')]
      .find(f => /^Order form/.test(f.querySelector('summary').textContent));
    const rowIn = k => {
      const tr = [...ordFold.querySelectorAll('tbody tr')]
        .find(t => (t.querySelector('td span') || {}).textContent === k);
      return tr ? [...tr.children].map(td => td.textContent.trim()) : null;
    };
    R.olderPackage = rowIn('package');
    R.olderMargin = rowIn('margin_pct');
    R.olderPartner = rowIn('partner_hard_cost');
    return R;
  });

  // ---------------- and an ORM quote comes back as ORM ----------------
  await p.goto(BASE + '/adtini/forecast?client=Ski%20Barn', { waitUntil: 'domcontentloaded' });
  await p.waitForFunction(() => document.querySelectorAll('.prod').length === 1);
  const orm = await p.evaluate(() => {
    const R = {};
    R.name = document.querySelector('.prod > h4').textContent.replace(/\s+/g, ' ').trim();
    const q = document.querySelector('.prod[data-row="0"] .qres');
    R.tiles = [...q.querySelectorAll('.qtile')].map(t =>
      t.querySelector('small').textContent + ' ' + t.querySelector('b').textContent);
    R.planner = [...q.querySelectorAll('.pview .pv')]
      .map(x => x.querySelector('small').textContent + ': ' + x.querySelector('b').textContent);
    document.querySelector('[data-open="0"][data-view="form"]').click();
    R.strategy = [...document.querySelectorAll('#form [data-chips="strategy"] .chip')]
      .map(c => c.firstChild.textContent.trim());
    R.reviews = document.querySelector('#form [data-k="reviews"]').value;
    R.locations = document.querySelector('#form [data-k="locations"]').value;
    // the scan that priced it is still on the quote
    document.getElementById('kwBuilder').click();
    R.scanCols = [...document.querySelectorAll('#paneScan .col h5 span')].map(s => s.textContent);
    return R;
  });

  const want = {
    'home.oneRowPerClient': [home.rows, 2],
    'home.sampleRowsGone': [home.noSamples, true],
    'home.rowFromTheStore': [home.first.slice(2, 5).join(' | '),
      '2026-09-10 | Drainify | SEO2'],
    'home.quoteCountPerProduct': [home.countPerProduct.join(','), 'SEO2'],
    'home.plannerFromTheStore': [home.plannerFromStore, 'Stacy'],
    'home.partnerFromTheStore': [home.partnerFromStore, 'ADX Communications'],
    'home.editWritesBackToTheClient': [JSON.stringify(posted[0] || {}),
      '{"client":"Drainify","status":"Complete"}'],
    'seo.everyQuoteIsARow': [seo.rows.length, 2],
    'seo.rowsAreDated': [/9\/10\/2026|2026-09-10/.test(seo.rows[0]), true],
    'seo.legacyQuotePriced': [seo.headline,
      'Quote results — $3,800/mo · 2 terms · 2,680/mo · 50% ranking'],
    'seo.tiersFromTheSavedQuote': [seo.tiles.join(' / '),
      'Base $3,800 / Intermediate $5,250 / Advanced $6,700'],
    'seo.aiSearchRead': [seo.planner.some(x => /AI Search: base \$2,166 · 57% of Core SEO/.test(x)), true],
    'seo.addOnMarketsRead': [seo.planner.some(x => /Add-on markets: 3 × \$900/.test(x)), true],
    'seo.serpCarried': [seo.serp, true],
    'seo.formBrand': [seo.brand, 'Drainify'],
    'seo.formCity': [seo.city.join(','), 'Manchester, UK'],
    'seo.cityFieldShownBecauseTicked': [seo.cityShown, true],
    'seo.countryFieldHiddenBecauseNot': [seo.countryHidden, true],
    'seo.formFocus': [seo.focus.join(','), 'drain unblocking,cctv survey'],
    'seo.pastSeoFieldsOpen': [seo.pastShown, 3],
    'seo.addOnMarketCount': [seo.markets, '3'],
    // a quote saved before the handoff block still reads
    'older.packageRead': [seo.olderPackage.join(' | '),
      'Package $ (Core + AI) — per tierpackage'
      + ' | base: $5,966 · intermediate: $8,242 · advanced: $10,516'],
    'older.marginRead': [seo.olderMargin[1], '0.35'],
    'older.partnerRead': [seo.olderPartner[1],
      'base: $2,470 · intermediate: $3,412 · advanced: $4,355'],
    'orm.readAsOrm': [/^Online Reputation Management/.test(orm.name), true],
    'orm.tiles': [orm.tiles.join(' / '),
      'Monthly $12,550 / Removals — max $95,250 / Total $133,000'],
    'orm.plannerView': [orm.planner.slice(0, 3).join(' | '),
      'Reactive — Search Protection: not on this quote'
      + ' | Proactive — Brand Shield: not on this quote'
      + ' | Review removals: 31 × $100'],
    'orm.strategyRead': [orm.strategy.join(','),
      'Review Removals,Site/Article Removals,Reactive,Proactive'],
    'orm.countsRead': [`${orm.reviews}/${orm.locations}`, '31/2'],
    'orm.scanKept': [orm.scanCols.join(','), '1,1,2'],
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
