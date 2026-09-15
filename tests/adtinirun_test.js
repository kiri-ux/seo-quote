// THE ADTINI TAB IS THE TOOL, NOT A MOCK OF IT.
//
// Keyword Builder is step 1 and calls /api/keywords then /api/refine. Generate
// Forecast runs steps 2-4 -- metrics, rankings in batches, price -- and the row
// opens to the quote it produced. The DataForSEO calls are stubbed so this
// measures the wiring: which endpoint, with which payload, in which order.
// (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";

const KW = {
  head: [{ kw: 'dental implants', vol: 3600 }],
  ultra: [{ kw: 'dental implants', vol: 3600, src: 'seed' }],
  competitive: [{ kw: 'dental implants boca raton', vol: 880, src: 'grid' }],
  long_tail: [{ kw: 'affordable dental implants near me', vol: 210, src: 'site' }],
  all: [{ kw: 'dental implants', vol: 3600 },
        { kw: 'dental implants boca raton', vol: 880 },
        { kw: 'affordable dental implants near me', vol: 210 }],
  total_volume: 4690,
  widen: { show: true, fact: 'One term is 77% of measured demand.' },
};
const PRICE = {
  anchor: 5450, base: 5450, step: 50,
  handoff: { package: { 'Core SEO': 5450, 'Add-on markets': 1200 },
             months: 6, markup_pct: 0.35 },
};

const CFG = {
  grid_target_keywords: 32, grid_min_services: 7, grid_max_services: 20, grid_max_cities: 5,
  grid_state_suffix: 'auto', service_min_volume: 30, service_upgrade_ratio: 10,
  service_max_swaps: 3, store_intent_tier_boost: 3,
  cpc_adder_mult: 2.6, cpc_adder_cap: 1300, cpc_adder_knee: 62, cpc_adder_mult_high: 12.3,
  tier_step_pct_of_base: 0.24, cpc_adder_free_below: 5,
  bid_score_breaks: [5, 15], competitive_adder: {0: 0, 1: 150, 2: 250},
  zero_ranking_tiers: [[80, 7], [65, 4], [50, 2], [0, 0]], zero_ranking_top_n: 100,
  vol_free_below: 10000, vol_add_ramp: [40, 60],
  volume_brackets: [[10000, 20000, 0.0702], [20000, 35000, 0.0439], [35000, null, 0.0351]],
  geo_anchor: {single_city: 2250, contiguous_region: 1850, non_contiguous_region: 2050,
               statewide: 2100, nationwide: 1800},
  tier_step_flat: 650, step_ratio: 0.38, volume_add_cap: 450, client_floor: 2950,
  default_markup_pct: 35, nationwide_service_extras: 1,
  geo_pct_tiers: [[90, 74], [70, 66], [40, 59], [0, 48]], geo_pct_default: 57,
  min_term_months: 6, pin_head_terms: 3, pin_min_volume: 300,
};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  const errs = [];
  const calls = [];
  p.on('pageerror', e => errs.push(e.message));

  const json = (route, body) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

  await p.route('**/api/**', route => {
    const url = new URL(route.request().url()).pathname;
    let body = {};
    try { body = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
    calls.push({ url, body });
    if (url === '/api/keywords') return json(route, KW);
    if (url === '/api/refine') return json(route, Object.assign({}, KW, { refined: true }));
    if (url === '/api/metrics') return json(route, { adder: 550, score: 41, pageone_rank: 22 });
    if (url === '/api/rankings') {
      const results = (body.batch || []).map((x, i) => ({
        kw: x.kw, pos: i === 0 ? 4 : 'Not Found', ranked_top: i === 0, error: false }));
      return json(route, { results, paa: [] });
    }
    if (url === '/api/price') return json(route, PRICE);
    if (url === '/api/config') return json(route, CFG);
    if (url === '/api/site_services')
      return json(route, {services: [{term: 'dental crowns', volume: 720}]});
    if (url === '/api/expand_services')
      return json(route, {services: [{term: 'invisalign', volume: 2400},
                                     {term: 'denture repair', volume: 90}]});
    if (url === '/api/rank_seeds')
      return json(route, {services: [{term: 'root canal', volume: 480, ranked_top: true}]});
    if (url === '/api/suggest_regions')
      return json(route, {regions: [{name: 'Palm Beach County'}]});
    return json(route, {});
  });

  await p.goto(BASE + '/adtini/forecast', { waitUntil: 'domcontentloaded' });
  await p.waitForSelector('.prod[data-row="0"] .qres');   // a saved quote is on the row

  // ---------------- a past quote reopens ----------------
  const hist = await p.evaluate(() => {
    const R = {};
    const prod = document.querySelector('.prod[data-row="0"]');
    prod.querySelector('.ptabs button[data-tab="history"]').click();
    R.rows = prod.querySelectorAll('.hist tbody tr').length;
    R.openable = prod.querySelectorAll('.hist [data-hist]').length;
    prod.querySelectorAll('.hist tbody tr')[1].querySelector('[data-hist]').click();
    const q = document.querySelector('.prod[data-row="0"] .qres');
    R.headline = q.querySelector('summary').textContent.trim();
    R.msg = document.querySelector('.prod[data-row="0"] .rowmsg').textContent.trim();
    return R;
  });

  // ---------------- pricing config ----------------
  await p.click('[data-open="0"][data-view="cfg"]');
  const cfg = await p.evaluate(() => {
    const R = {};
    R.title = document.querySelector('.sheet .top h2').textContent.trim();
    R.groups = [...document.querySelectorAll('#cfgGlobal .cfggrp > summary')]
      .map(x => x.childNodes[0].textContent.trim());
    R.anchor = document.querySelector('#cfgGlobal [data-g="geo_anchor.single_city"]').value;
    R.break1 = document.querySelector('#cfgGlobal [data-g="bid_score_breaks.0"]').value;
    R.tierRows = document.querySelectorAll('#cfgGlobal [data-t="zero_ranking_tiers"]').length;
    R.bracketRows = document.querySelectorAll('#cfgGlobal [data-b="volume_brackets"]').length;
    R.openTopBlank = document.querySelectorAll('#cfgGlobal [data-b="volume_brackets"]')[2]
      .querySelectorAll('input')[1].value;
    document.querySelector('#cfgGlobal [data-g="geo_anchor.single_city"]').value = '2400';
    document.querySelector('#cfgGlobal [data-g="cpc_adder_cap"]').value = '1500';
    document.getElementById('save').click();
    return R;
  });
  await p.waitForFunction(() => /constants/.test(document.getElementById('saved').textContent));
  const posted = calls.filter(c => c.url === '/api/config').pop() || { body: {} };

  // ---------------- past-SEO fields ----------------
  const past = await p.evaluate(() => {
    const R = {};
    document.getElementById('close').click();
    document.querySelector('[data-open="0"][data-view="form"]').click();
    const shown = () => [...document.querySelectorAll('#fseo [data-past]')].filter(x => !x.hidden).length;
    R.total = document.querySelectorAll('#fseo [data-past]').length;
    R.yes = shown();                                   // row 0 answered Yes
    document.querySelector('#fseo .yn[data-k="past"] button[data-v="0"]').click();
    R.no = shown();
    document.querySelector('#fseo .yn[data-k="past"] button[data-v="1"]').click();
    R.backOn = shown();
    document.getElementById('close').click();
    document.querySelector('[data-open="1"][data-view="form"]').click();
    R.otherRow = shown();                              // row 1 answered No
    document.getElementById('close').click();
    return R;
  });

  // ---------------- the pipeline, on a row with nothing saved ----------------
  await p.evaluate(() => {
    ROWS.forEach(r => { delete r.result; delete r.kw; r.history = []; });
    draw();
  });
  calls.length = 0;

  // ---------------- step 1: the keyword builder ----------------
  await p.click('[data-open="0"][data-view="form"]');
  await p.click('#kwBuilder');
  await p.click('#kbBuild');
  await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent));

  const kb = await p.evaluate(() => ({
    scopeNote: document.getElementById('kbScopeNote').textContent,
    nat: document.querySelector('#kbNat button.on').dataset.v,
    country: document.getElementById('kbCountry').value,
    note: document.getElementById('saved').textContent,
    head: document.getElementById('kbHead').textContent,
    counts: [...document.querySelectorAll('#paneKw .col h5 span')].map(s => s.textContent),
    terms: [...document.querySelectorAll('#paneKw .col li span:first-child')].map(s => s.textContent),
    widenShown: !document.getElementById('kbWiden').hidden,
    widenText: document.getElementById('kbWiden').textContent,
  }));
  // the [src] toggle labels each term with where it came from
  await p.check('#kbSrc');
  const srcTags = await p.$$eval('#paneKw .col li .s', n => n.map(x => x.textContent));

  // ---------------- steps 2-4: generate forecast ----------------
  await p.click('#gen');                       // applies the list, back on the form
  await p.click('#gen');                       // runs the forecast
  await p.waitForSelector('.prod[data-row="0"] .qres', { timeout: 15000 });

  const res = await p.evaluate(() => {
    const R = {};
    const q = document.querySelector('.prod[data-row="0"] .qres');
    R.headline = q.querySelector('summary').textContent.trim();
    R.tiles = [...q.querySelectorAll('.qtile')].map(t =>
      t.querySelector('small').textContent + ' ' + t.querySelector('b').textContent);
    R.folds = [...q.querySelectorAll('.qfold > summary')].map(s => s.textContent.trim());
    const kwFold = [...q.querySelectorAll('.qfold')].find(f => /Keyword table/.test(f.textContent));
    R.rankRows = [...kwFold.querySelectorAll('table.kv tr')].slice(1)
      .map(tr => [...tr.children].map(td => td.textContent.trim()).join(' | '));
    const io = [...q.querySelectorAll('.qfold')].find(f => /Line item payload/.test(f.textContent));
    R.ioKeys = [...io.querySelectorAll('table.kv td:first-child')].map(td => td.textContent.trim());
    // the matrix: what leaves this quote, and for which destination
    const send = q.querySelector('table.send');
    R.sendSections = [...send.querySelectorAll('tr.sec th')].map(t => t.textContent.trim());
    const rowOf = k => [...send.querySelectorAll('tbody tr')]
      .find(tr => (tr.querySelector('td span') || {}).textContent === k);
    const cells = tr => [...tr.children].map(td => td.textContent.trim());
    R.packageRow = cells(rowOf('package'));
    R.brandRow = cells(rowOf('brand'));
    R.serpRow = cells(rowOf('serp'));
    R.serpIsGap = rowOf('serp').classList.contains('gap');
    R.insightRow = cells(rowOf('widen'));
    R.insightIsGap = rowOf('widen').classList.contains('gap');
    R.foot = q.querySelector('.sendfoot').textContent.replace(/\s+/g, ' ').trim();
    R.modalClosed = document.getElementById('scrim').hidden;
    // the run lands in that row's History tab
    document.querySelector('.prod[data-row="0"] .ptabs button[data-tab="history"]').click();
    R.historyCols = [...document.querySelectorAll('.prod[data-row="0"] .hist thead th')]
      .map(t => t.textContent.trim()).filter(Boolean);
    R.historyRows = document.querySelectorAll('.prod[data-row="0"] .hist tbody tr').length;
    return R;
  });

  const seq = calls.map(c => c.url);
  const kwCall = calls.find(c => c.url === '/api/keywords') || { body: {} };
  const refCall = calls.find(c => c.url === '/api/refine') || { body: {} };
  const metCall = calls.find(c => c.url === '/api/metrics') || { body: {} };
  const rankCalls = calls.filter(c => c.url === '/api/rankings');
  const priceCall = calls.find(c => c.url === '/api/price') || { body: {} };

  const want = {
    // step 1
    // EXPAND ON FOCUS TERMS runs before the build and feeds it
    'kb.expandsFirst': [seq.slice(0, 4).sort().join(','),
      '/api/expand_services,/api/rank_seeds,/api/site_services,/api/suggest_regions'],
    'kb.thenBuildsAndRefines': [seq.slice(4, 6).join(','), '/api/keywords,/api/refine'],
    // a term they already rank for leads, then by volume
    'kb.seedsGrew': [(kwCall.body.keywords || []).slice(3).join(','),
      'root canal,invisalign,dental crowns,denture repair'],
    'kb.regionsCarried': [(kwCall.body.phrase_geos || []).join(','), 'Palm Beach County'],
    'kb.provenanceSent': [(refCall.body.ranked || []).join(','), 'root canal'],
    'kb.businessDescSent': ['business_desc' in kwCall.body, true],
    'kb.seedsSent': [Array.isArray(kwCall.body.keywords) && kwCall.body.keywords.length > 0, true],
    'kb.countrySent': [kwCall.body.country, 'US'],
    'kb.refineGetsBuckets': [refCall.body.ultra && refCall.body.ultra.length, 1],
    'kb.refineGetsBand': [!!refCall.body.geo_scope, true],
    // scope is read off the order, not picked in the builder
    'kb.scopeRead': [kb.scopeNote, 'Geo scope: Single city · Boca Raton, FL'],
    'kb.nationalToggle': [kb.nat, '0'],
    'kb.countryFromRow': [kb.country, 'United States'],
    'kb.note': [kb.note, 'Built 3 terms. · 4 terms added by expansion.'],
    'kb.head': [kb.head, 'Keyword list (3 terms)'],
    'kb.counts': [kb.counts.join(','), '1,1,1'],
    'kb.terms': [kb.terms.join(' / '),
      'dental implants / dental implants boca raton / affordable dental implants near me'],
    'kb.widenShown': [kb.widenShown, true],
    'kb.widenText': [kb.widenText, 'One term is 77% of measured demand.'],
    'kb.srcTags': [srcTags.join(','), '[seed],[grid],[site]'],
    // steps 2-4
    'run.order': [seq.slice(6).join(','), '/api/metrics,/api/rankings,/api/price'],
    'run.headTerms': [(metCall.body.head || []).join(','), 'dental implants'],
    'run.rankBatched': [rankCalls.length, 1],
    'run.rankBatchSize': [(rankCalls[0].body.batch || []).length, 3],
    // one of three ranked in the top set -> 67% not ranking, as a percentage
    'run.bandIsRowScope': [priceCall.body.band, 'single_city'],
    'run.nationalOffForCity': [priceCall.body.national_demand, false],
    'run.pctIsPercent': [priceCall.body.pct_not_ranking, 67],
    'run.zeroRankingOff': [priceCall.body.zero_ranking, false],
    'run.volumeFromBuilder': [priceCall.body.total_volume, 4690],
    'run.adderCarried': [priceCall.body.adder, 550],
    'run.pageoneCarried': [priceCall.body.pageone_rank, 22],
    'run.markupIsFraction': [priceCall.body.markup_pct, 0.35],
    // the row opens to the quote
    'res.headline': [res.headline,
      'Quote results — $5,450/mo · 3 terms · 4,690/mo · 33% ranking'],
    'res.tiles': [res.tiles.join(' / '), 'Core SEO $5,450 / Add-on markets $1,200'],
    'res.folds': [res.folds.join(' / '),
      'What goes where / Line item payload — 3 fields / Keyword table — 3 terms'
      + ' / Proposal payload — 3 fields'],
    'send.sections': [res.sendSections.join(' / '),
      'Order & scope / Client price / Add-on markets / Partner cost'
      + ' / Keywords & measurement / List insights'],
    'send.priceGoesBoth': [res.packageRow.join(' | '),
      'Package — per tierpackage | Core SEO: $5,450 · Add-on markets: $1,200 | ● | ●'],
    'send.brandProposalOnly': [res.brandRow.slice(2).join(' | '), '– | ●'],
    'send.missingIsNamed': [res.serpRow[1], 'not captured'],
    'send.missingIsFlagged': [res.serpIsGap, true],
    'send.insightsAreScreenOnly': [res.insightRow.slice(2).join(' | '), '– | –'],
    'send.insightIsNotAGap': [res.insightIsGap, false],
    'send.counts': [/^Line item \d+ of \d+ · Proposal \d+ of \d+/.test(res.foot), true],
    'res.rankRows': [res.rankRows.join(' // '),
      'dental implants | 3,600 | 4 // dental implants boca raton | 880 | Not Found'
      + ' // affordable dental implants near me | 210 | Not Found'],
    'res.ioKeys': [res.ioKeys.join(','), 'package,months,markup_pct'],
    'res.modalClosed': [res.modalClosed, true],
    'res.historyCols': [res.historyCols.join('|'),
      'Date Forecasted|Forecast Prompt|Generated Response|Type|Error'],
    'res.historyRows': [res.historyRows, 1],
  };

  Object.assign(want, {
    'cfg.title': [cfg.title, 'Pricing Config'],
    'cfg.groups': [cfg.groups.join(' / '),
      'Step 1 · Keyword grid / Step 2 · Competition / Step 3 · Zero-ranking uplift'
      + ' / Step 4 · Volume / Step 4 · Anchors / AI Search / Keyword list consistency'],
    'cfg.anchorLoaded': [cfg.anchor, '2250'],
    'cfg.nestedLoaded': [cfg.break1, '5'],
    'cfg.tierRows': [cfg.tierRows, 4],
    'cfg.bracketRows': [cfg.bracketRows, 3],
    'cfg.openTopIsBlank': [cfg.openTopBlank, ''],
    // AN EDIT PRICES THIS QUOTE, NOT THE SESSION: nothing is posted to
    // /api/config, and only what moved rides along on the pipeline calls.
    'cfg.nothingPostedToSession': [calls.filter(c => c.url === '/api/config'
      && c.body && Object.keys(c.body).length).length, 0],
    'cfg.overlayOnThePrice': [(priceCall.body.cfg || {}).cpc_adder_cap, '1500'],
    'cfg.overlayKeepsTheGroupWhole': [JSON.stringify((priceCall.body.cfg || {}).geo_anchor),
      JSON.stringify({single_city: '2400', contiguous_region: '1850',
        non_contiguous_region: '2050', statewide: '2100', nationwide: '1800'})],
    'cfg.overlayIsOnlyWhatMoved': [Object.keys(priceCall.body.cfg || {}).sort().join(','),
      'cpc_adder_cap,geo_anchor'],
    'cfg.overlayOnStepOne': [Object.keys(kwCall.body.cfg || {}).sort().join(','),
      'cpc_adder_cap,geo_anchor'],
    // past-SEO fields follow the answer
    'past.count': [past.total, 3],
    'past.shownOnYes': [past.yes, 3],
    'past.hiddenOnNo': [past.no, 0],
    'past.backOnYes': [past.backOn, 3],
    'past.hiddenOnRowThatSaidNo': [past.otherRow, 0],
    // a saved quote reopens off History
    'hist.rows': [hist.rows, 2],
    'hist.opensThatQuote': [hist.headline,
      'Quote results — $4,950/mo · 4 terms · 7,100/mo · 100% ranking'],
    'hist.says': [hist.msg, 'Showing the quote built 9/11/26 4:08 PM.'],
  });

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
