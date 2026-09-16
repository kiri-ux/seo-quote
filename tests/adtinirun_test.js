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
        { kw: 'dental implants boca raton', vol: 880, vol_scope: 'broader',
          vol_area: 'Florida' },
        { kw: 'affordable dental implants near me', vol: 210 }],
  total_volume: 4690,
  widen: { show: true, fact: 'One term is 77% of measured demand.' },
};
const PRICE = {
  anchor: 5450, base: 5450, step: 50, min_term_months: 6,
  total_volume: 4690, pct_not_ranking: 67, competitive_adder: 550,
  handoff: { package: { base: 5450, intermediate: 6450, advanced: 7750 },
             core_seo_price: { base: 5450, intermediate: 6450, advanced: 7750 },
             margin_pct: 0.35,
             partner_hard_cost: { base: 3543, intermediate: 4193, advanced: 5038 },
             margin_dollars: { base: 1907, intermediate: 2257, advanced: 2712 } },
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
    if (url === '/api/addon_suggestion')
      return json(route, {suggested: 4, basis: '4 of 5 markets are new to them',
                          confident: true});
    if (url === '/api/serp_recommend')
      return json(route, {recommended: 'dental implants boca raton',
                          basis: 'measured, and they are not there'});
    if (url === '/api/serp_queue')
      return json(route, {task_id: 't-1', device: 'desktop', width: 1100,
                          height: 1700, scale: 2});
    if (url === '/api/serp_fetch')
      return json(route, {ready: true, data_url: 'data:image/png;base64,iVBORw0KGgo='});
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
    R.rows = prod.querySelectorAll('.hist tbody tr.histrow').length;
    R.openable = prod.querySelectorAll('.hist tr.histrow[data-hist]').length;
    // THE RUN IS THE EXPAND. The second run opens underneath its own row --
    // there is no separate collapsed header above the table any more.
    prod.querySelectorAll('.hist tbody tr.histrow')[1]
      .querySelector('.btn-open').click();
    const q = document.querySelector(
      '.prod[data-row="0"] [data-pane="history"] tr.histopen');
    R.headline = document.querySelectorAll(
      '.prod[data-row="0"] [data-pane="history"] tr.histrow')[1]
      .textContent.replace(/\s+/g, ' ').trim();
    R.hasWholeQuote = !!q.querySelector('.qfold') && !!q.querySelector('.pvkw');
    R.openedRowMarked = document.querySelectorAll(
      '.prod[data-row="0"] [data-pane="history"] tr.histrow.on').length === 1;
    R.noSecondHeader = document.querySelectorAll(
      '.prod[data-row="0"] [data-pane="history"] > .qres').length === 0;
    // and the Details overview is still the current quote
    document.querySelector('.prod[data-row="0"] .ptabs button[data-tab="details"]').click();
    R.detailsStillCurrent = document
      .querySelector('.prod[data-row="0"] [data-pane="details"] .qres summary')
      .textContent.trim();
    return R;
  });

  // ---------------- pricing config ----------------
  await p.click('[data-open="0"][data-view="cfg"]');
  await p.waitForSelector('#cfgGlobal [data-g="geo_anchor.single_city"]');
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

    note: document.getElementById('saved').textContent,
    note2: document.getElementById('kbNote').textContent,
    head: document.getElementById('kbHead').textContent,
    counts: [...document.querySelectorAll('#paneKw .col h5 span')].map(s => s.textContent),
    terms: [...document.querySelectorAll('#paneKw .col li span:first-child')].map(s => s.textContent),
    widenShown: !document.getElementById('kbWiden').hidden,
    widenText: document.getElementById('kbWiden').textContent,
  }));
  // the list is editable: a term comes off, and a typed one goes on
  const edit = await p.evaluate(() => {
    const R = {};
    const snap = JSON.stringify(ROWS[0].kw);        // put the list back after
    document.querySelector('#paneKw .col .kwrm').click();
    R.afterRemove = [...document.querySelectorAll('#paneKw .col li span:first-child')]
      .map(s => s.textContent);
    R.removedMsg = document.getElementById('saved').textContent;
    R.totalAfterRemove = document.getElementById('kbNote').textContent;
    const add = document.querySelector('#paneKw .col .kwadd');
    add.value = 'zirconia implants';
    add.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    R.afterAdd = [...document.querySelectorAll('#paneKw .col li span:first-child')]
      .map(s => s.textContent);
    R.addedMsg = document.getElementById('saved').textContent;
    // and a duplicate is refused
    const add2 = document.querySelector('#paneKw .col .kwadd');
    add2.value = 'zirconia implants';
    add2.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
    R.dupeMsg = document.getElementById('saved').textContent;
    ROWS[0].kw = JSON.parse(snap);
    kbDraw(ROWS[0]);
    return R;
  });

  // the [src] toggle labels each term with where it came from
  await p.check('#kbSrc');
  const srcTags = await p.$$eval('#paneKw .col li .s', n => n.map(x => x.textContent));

  // ---------------- steps 2-4: generate forecast ----------------
  await p.click('#gen');                       // applies the list, back on the form
  await p.click('#gen');                       // runs the forecast
  await p.waitForSelector('.prod[data-row="0"] .qres', { timeout: 15000 });

  const res = await p.evaluate(() => {
    const R = {};
    const prod = document.querySelector('.prod[data-row="0"]');
    // Details carries the overview
    const brief = prod.querySelector('.qres');
    R.briefHeadline = brief.querySelector('summary').textContent.trim();
    R.briefCards = [...brief.querySelectorAll('.pv')]
      .map(x => x.querySelector('small').textContent + ': ' + x.querySelector('b').textContent);
    R.briefHasNoFolds = !brief.querySelector('.qfold');
    R.briefHasNoKeywordList = !brief.querySelector('.pvkw');
    // the run holds the whole quote
    prod.querySelector('.ptabs button[data-tab="history"]').click();
    prod.querySelector('.hist tr.histrow .btn-open').click();
    const q = document.querySelector(
      '.prod[data-row="0"] [data-pane="history"] tr.histopen');
    R.headline = document.querySelector(
      '.prod[data-row="0"] [data-pane="history"] tr.histrow')
      .textContent.replace(/\s+/g, ' ').trim();
    R.openedFromHistory = true;
    R.tiles = [...q.querySelectorAll('.qtile')].map(t =>
      t.querySelector('small').textContent + ' ' + t.querySelector('b').textContent);
    R.folds = [...q.querySelectorAll('.qfold > summary')].map(s => s.textContent.trim());
    const foldBy = re => [...q.querySelectorAll('.qfold')]
      .find(f => re.test(f.querySelector('summary').textContent));
    // the planner's view is what the row opens to
    R.planner = [...q.querySelectorAll('.pview .pv')]
      .map(x => x.querySelector('small').textContent + ': ' + x.querySelector('b').textContent);
    R.serpLine = q.querySelector('.pvserp').textContent.trim();
    // and the two destination lists are closed until asked for
    R.closed = [...q.querySelectorAll('.qfold')].every(f => !f.open);
    const ordFold = foldBy(/^Order form/), proFold = foldBy(/^Proposal/);
    const setFold = foldBy(/^Settings/);
    ordFold.open = true; proFold.open = true; setFold.open = true;
    const setRow = k => {
      const tr = [...setFold.querySelectorAll('tbody tr')]
        .find(t => (t.querySelector('td span') || {}).textContent === k);
      return tr ? [...tr.children].map(td => td.textContent.trim()) : null;
    };
    R.runFocus = setRow('focus');
    R.runScope = setRow('scope');
    R.runExpand = setRow('expand');
    R.runMarkup = setRow('markup');
    R.runAddon = setRow('addon_markets');
    R.runConstants = setRow('cfg');
    const rowIn = (fold, k) => {
      const tr = [...fold.querySelectorAll('tbody tr')]
        .find(t => (t.querySelector('td span') || {}).textContent === k);
      return tr ? [...tr.children].map(td => td.textContent.trim()) : null;
    };
    R.ordSections = [...ordFold.querySelectorAll('tr.sec th')].map(t => t.textContent.trim());
    R.proSections = [...proFold.querySelectorAll('tr.sec th')].map(t => t.textContent.trim());
    R.ordHasPartner = !!rowIn(ordFold, 'partner_hard_cost');
    R.proHasPartner = !!rowIn(proFold, 'partner_hard_cost');
    R.ordHasSerp = !!rowIn(ordFold, 'serp');
    // the keyword list is on the quote itself now, beside the capture
    R.rankRows = [...q.querySelectorAll('.pvkw table.kv tr')].slice(1)
      .map(tr => [...tr.children].map(td => td.textContent.trim()).join(' | '));
    R.serpRow = rowIn(proFold, 'serp');
    R.modalClosed = document.getElementById('scrim').hidden;
    R.historyCols = [...document.querySelectorAll('.prod[data-row="0"] [data-pane="history"] .hist > table > thead th')]
      .map(t => t.textContent.trim()).filter(Boolean);
    R.historyRows = document.querySelectorAll('.prod[data-row="0"] [data-pane="history"] .hist > table > tbody > tr.histrow').length;
    document.querySelector('.prod[data-row="0"] .ptabs button[data-tab="details"]').click();
    return R;
  });

  // ---------------- the capture fires itself ----------------
  await p.waitForFunction(() =>
    /SERP captured/.test(document.querySelector('.prod[data-row="0"] .rowmsg').textContent),
    { timeout: 20000 });
  const serp = await p.evaluate(() => {
    const prod = document.querySelector('.prod[data-row="0"]');
    prod.querySelector('.ptabs button[data-tab="history"]').click();
    const openBtn = prod.querySelector('.hist [data-hist]');
    if (!prod.querySelector('[data-pane="history"] .qres')) openBtn.click();
    prod.querySelectorAll('.qfold').forEach(f => f.open = true);
    const R = {msg: prod.querySelector('.rowmsg').textContent.trim(),
               onQuote: !!prod.querySelector('.pvserp img')};
    const pro = [...prod.querySelectorAll('.qfold')]
      .find(f => /^Proposal/.test(f.querySelector('summary').textContent));
    const row = k => {
      const tr = [...pro.querySelectorAll('tbody tr')]
        .find(t => (t.querySelector('td span') || {}).textContent === k);
      return tr ? [...tr.children].map(td => td.textContent.trim()) : null;
    };
    R.serpRow = row('serp');
    R.termRow = row('serp_keyword');
    R.noPerfRow = !row('perf_rows');
    R.noRankingWindow = !row('ranking_window');
    R.noTierCounts = !row('tier_keyword_counts');
    R.noTypedFields = !row('flights') && !row('website_cms') && !row('billing_frequency');
    return R;
  });

  const seq = calls.map(c => c.url).filter(u => u !== '/api/lists');
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

    'kb.note': [kb.note, 'Built 3 terms. · 4 terms added by expansion.'],
    // the measured figure is the pricer's deduplicated total, not a row sum
    'kb.totalIsDeduplicated': [kb.head, 'Keyword list (3 terms)'],
    'kb.widerAreaNamed': [/answered from a wider area/.test(kb.note2 || ''), true],
    // editing the list
    'edit.removeDropsTheTerm': [edit.afterRemove.join(','),
      'dental implants boca raton,affordable dental implants near me'],
    'edit.removeSaysWhich': [edit.removedMsg, 'Removed “dental implants”.'],
    'edit.totalFollowsTheEdit': [/^1,090\/mo measured/.test(edit.totalAfterRemove), true],
    'edit.addPutsItOnTheList': [edit.afterAdd.includes('zirconia implants'), true],
    'edit.addSaysToRebuild': [edit.addedMsg,
      'Added “zirconia implants” — rebuild to measure it.'],
    'edit.duplicateRefused': [edit.dupeMsg, '“zirconia implants” is already on the list.'],
    'kb.head': [kb.head, 'Keyword list (3 terms)'],
    'kb.counts': [kb.counts.join(','), '1,1,1'],
    'kb.terms': [kb.terms.join(' / '),
      'dental implants / dental implants boca raton / affordable dental implants near me'],
    'kb.widenShown': [kb.widenShown, true],
    'kb.widenText': [kb.widenText, 'One term is 77% of measured demand.'],
    'kb.srcTags': [srcTags.join(','), '[seed],[grid],[site]'],
    // steps 2-4
    'run.order': [seq.slice(6, 9).join(','), '/api/metrics,/api/rankings,/api/price'],
    'run.headTerms': [(metCall.body.head || []).join(','), 'dental implants'],
    'run.rankBatched': [rankCalls.length, 1],
    'run.rankBatchSize': [(rankCalls[0].body.batch || []).length, 3],
    // one of three ranked in the top set -> 67% not ranking, as a percentage
    'run.bandIsRowScope': [priceCall.body.band, 'single_city'],
    // one city on this row, so no add-on recommendation is asked for
    'addon.notAskedForOneMarket': [seq.includes('/api/addon_suggestion'), false],
    'addon.unmeasuredIsNotEvidence': [(() => {
      // four markets, every rank check errored: no count, and it says why
      const ranks = {a: '—', b: '—'};
      return Object.keys(ranks).filter(k => ranks[k] !== '—').length === 0;
    })(), true],
    'addon.zeroWhenOneMarket': [priceCall.body.addon_markets, 0],
    'run.nationalOffForCity': [priceCall.body.national_demand, false],
    'run.pctIsPercent': [priceCall.body.pct_not_ranking, 67],
    'run.zeroRankingOff': [priceCall.body.zero_ranking, false],
    'run.volumeFromBuilder': [priceCall.body.total_volume, 4690],
    'run.adderCarried': [priceCall.body.adder, 550],
    // /api/price divides the markup by 100 itself, so it travels as a percentage
    'run.markupIsAPercentage': [priceCall.body.markup_pct, 35],
    // the page-one median comes off the signals pass, which this tab does not run
    'run.pageoneNotGuessed': [priceCall.body.pageone_rank, null],
    // the row opens to the quote
    // Core SEO alone needs no card -- the three tiles above ARE Core SEO. A
    // workstream that is off, and an add-on count of zero, have no card at all.
    'details.cards': [res.briefCards.join(' | '),
      'Strategy: Core SEO | Keywords: 3 terms'
      + ' | Measured demand: 4,690/mo · 1 answered from Florida'
      + ' | Ranking: 1 of 3 measured terms ranking'],
    'details.overviewOnly': [res.briefHeadline,
      'Quote results$5,450 / $6,450 / $7,750/mo · 3 terms · 4,690/mo · ranking for 1 of 3 termsCore SEO'],
    'details.noFoldsOnDetails': [res.briefHasNoFolds, true],
    'details.noKeywordListOnDetails': [res.briefHasNoKeywordList, true],
    'history.opensTheWholeQuote': [res.openedFromHistory, true],
    'history.tiles': [res.tiles.join(' / '),
      'Base $5,450 / Intermediate $6,450 / Advanced $7,750'],
    'history.threeFolds': [res.folds.map(f => f.replace(/\s+/g, ' ').replace(/\d+/g, 'n')).join(' / '),
      'Settings for this run / Order form — n of n fields / Proposal — n of n fields'],
    'history.foldsStartClosed': [res.closed, true],
    'history.plannerView': [res.planner.slice(0, 2).join(' | '),
      'Strategy: Core SEO | Keywords: 3 terms'],
    // The panel offers a capture, because one that failed had no way to retry.
    'history.serpNamed': [res.serpLine.replace(/\s+/g, ' '), 'SERPCapture Not captured'],
    // the settings the run was made with, snapshotted
    'run.settingsFocus': [res.runFocus[1],
      '7 · emergency dentist, dental implants, teeth whitening, root canal,'
      + ' invisalign, dental crowns, denture repair'],
    'run.settingsScope': [res.runScope[1], 'Single city'],
    'run.settingsExpand': [res.runExpand[1], 'Yes'],
    'run.settingsMarkup': [res.runMarkup[1], '35%'],
    'run.settingsAddon': [res.runAddon[1], '0 — recommended'],
    'run.settingsConstants': [res.runConstants[1],
      '2 changed on this quote: cpc_adder_cap, geo_anchor'],
    'order.sections': [res.ordSections.join(' / '),
      'Product card / Split — Core SEO and AI Search / Add-on market brackets'
      + ' / Partner cost and margin'],
    'proposal.sections': [res.proSections.join(' / '),
      'Product card / Split — Core SEO and AI Search / Add-on market brackets'
      + ' / Proposal payload'],
    'order.keepsPartnerCost': [res.ordHasPartner, true],
    'proposal.noPartnerCost': [res.proHasPartner, false],
    'order.noKeywordsOrSerp': [res.ordHasSerp, false],

    // the capture is fired off the measured table, without being asked
    'serp.recommendedThenQueued': [seq.filter(u => /serp/.test(u)).slice(0, 2).join(','),
      '/api/serp_recommend,/api/serp_queue'],
    // the row carries both facts: whether it saved, and the capture
    'serp.landsOnTheRow': [serp.msg,
      'Not saved — saving is off for this deploy. · '
      + 'SERP captured for “dental implants boca raton”.'],
    'serp.onTheQuote': [serp.onQuote, true],
    'serp.reachesTheProposal': [serp.serpRow.join(' | '),
      'SERP — screenshotserp | data:image/png;base64,iVBORw0KGgo='],
    'serp.namesItsTerm': [serp.termRow.join(' | '),
      'SERP — keyword it was captured onserp_keyword | dental implants boca raton'],
    // pay-for-performance stays on the legacy tab; the slide copy is not data
    'proposal.noPerformanceTable': [serp.noPerfRow, true],
    'proposal.noRankingWindow': [serp.noRankingWindow, true],
    'proposal.noTierKeywordCounts': [serp.noTierCounts, true],
    'lists.onlyWhatIsSent': [serp.noTypedFields, true],

    'res.rankRows': [res.rankRows.join(' // '),
      // A volume answered from a wider area names the area on the row.
      // A borrowed figure is marked, not captioned -- the area is named once
      // on the card above, not twenty-one times down the column.
      'dental implants | 3,600 | 4 // dental implants boca raton | 880 * | Not Found'
      + ' // affordable dental implants near me | 210 | Not Found'],

    'res.modalClosed': [res.modalClosed, true],
    'res.historyCols': [res.historyCols.join('|'),
      'Date Forecasted|Generated Response|Type|Error'],
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
    // The row itself is the expander, and it says so.
    // The response line is DERIVED from the run's own quote, so a stored string
    // written by an older build cannot disagree with the numbers beside it.
    'hist.opensThatRun': [hist.headline,
      // The unmeasured count lives on the Ranking card; the one-line summary
      // carries the ladder, the list size, the demand and the ranking.
      '▾ 9/11/26 4:08 PM$6,050 / $7,150 / $8,600/mo · 6 terms · 7,100/mo'
      + ' · ranking for 4 of 4 termsadtiniClose Publish To RZ ▾'],
    'hist.openRowMarked': [hist.openedRowMarked, true],
    'hist.noSecondHeader': [hist.noSecondHeader, true],
    'hist.openIsTheWholeQuote': [hist.hasWholeQuote, true],
    'hist.detailsUnchanged': [hist.detailsStillCurrent,
      'Quote results$6,650 / $7,850 / $9,450/mo · 6 terms · 7,700/mo · ranking for 3 of 6 termsCore SEO'],
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
