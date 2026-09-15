// ORM IS A SCAN, THEN A QUOTE.
//
// No keyword builder: the row's step 1 is Run brand scan -- locations, terms,
// SERP, auto-suggest and the 1-2 star count -- which fills the counts on the
// form. Generate Quote prices those counts through /api/rep_quote, and the row
// opens to what goes to the order form and the proposal. The DataForSEO calls
// are stubbed, so this measures the wiring. (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = "http://127.0.0.1:5203";

const QUOTE = {
  lines: [{label: 'Review Removals', total: 1000}, {label: 'Reactive · Search Protection', total: 3100}],
  totals: {monthly: 3100, removals_max: 1000, total: 19600},
  warnings: ['Success rate: ~60% on reviews newer than 6 months; ~50% on older ones.'],
  handoff: {
    review_removals: true, reviews_count: 14, price_per_review_removal: 100,
    site_article_removals: true, standard_sites: 2, premium_sites: 1,
    price_per_standard_site_removal: 7500, price_per_premium_site_removal: 10000,
    monthly_budget: 3100, search_protection_monthly: 3100, brand_shield_monthly: 5000,
    search_volume: 1030, locations: 3, margin_pct: 0.35,
    partner_monthly_cost: 2015, partner_hard_cost_per_review: 65,
    partner_hard_cost_per_standard_site: 4875, partner_hard_cost_per_premium_site: 6500,
    partner_search_protection_monthly: 2015, partner_brand_shield_monthly: 3250,
    partner_review_removals_total: 910, partner_standard_sites_total: 9750,
    partner_premium_sites_total: 6500, margin_dollars_monthly: 1085,
    strategy: ['Review Removals', 'Site/Article Removals', 'Reactive', 'Proactive'],
    removal_pages: [{pos: 4, domain: 'ripoffreport.com', url: 'https://x/1', tier: 'premium'}],
    suppression_pages: [{pos: 2, domain: 'yelp.com', url: 'https://y/2'}],
  },
};

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage();
  const errs = [], calls = [];
  p.on('pageerror', e => errs.push(e.message));
  const json = (route, body) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

  await p.route('**/api/**', route => {
    const url = new URL(route.request().url()).pathname;
    let body = {};
    try { body = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
    calls.push({ url, body });
    if (url === '/api/rep_scan_locations') return json(route, {strategy: 'domain', locations: [
      {title: 'Sage Dental of Midtown Atlanta', place_id: 'p1', reviews: 214},
      {title: 'Sage Dental of Tucker', place_id: 'p2', reviews: 174},
      {title: 'Sage Dental of Conway', place_id: 'p3', reviews: 58}]});
    if (url === '/api/rep_scan_terms') return json(route, {rows: [
      {keyword: 'sage dental reviews', volume: 720},
      {keyword: 'sage dental lawsuit', volume: 170},
      {keyword: 'sage dental complaints', volume: 140}]});
    if (url === '/api/rep_scan_serp') return json(route, {rows: [
      {pos: 1, domain: 'trustpilot.com', url: 'https://trustpilot.com/x'},
      {pos: 2, domain: 'sage-dental.com', url: 'https://sage-dental.com'},
      {pos: 3, domain: 'ripoffreport.com', url: 'https://ripoffreport.com/y'}]});
    if (url === '/api/rep_scan_autocomplete') return json(route, {rows: [{term: 'sage dental sued'}]});
    if (url === '/api/rep_reviews_submit') return json(route, {tasks: [{id: 't1', ok: true}]});
    if (url === '/api/rep_reviews_collect') return json(route, {
      done: [{id: 't1', neg_1_2: 14, neg_1: 9}], pending: []});
    if (url === '/api/rep_quote') return json(route, QUOTE);
    if (url === '/api/config') return json(route, {geo_anchor: {}, zero_ranking_tiers: [],
      volume_brackets: [], geo_pct_tiers: [], addon_volume_discount_tiers: [],
      competitive_adder: {}, bid_score_breaks: [5, 15], vol_add_ramp: [40, 60]});
    return json(route, {});
  });

  await p.goto(BASE + '/adtini/forecast', { waitUntil: 'domcontentloaded' });
  await p.click('[data-open="2"][data-view="form"]');           // the ORM row

  const pane = await p.evaluate(() => ({
    pill: document.getElementById('kwBuilder').textContent.trim(),
    gen: document.getElementById('gen').textContent.trim(),
  }));
  await p.click('#kwBuilder');
  const opened = await p.evaluate(() => ({
    title: document.querySelector('.sheet .top h2').textContent.trim(),
    scanPane: !document.getElementById('paneScan').hidden,
    noKeywordPane: document.getElementById('paneKw').hidden,
    brand: document.getElementById('scBrand').value,
  }));

  await p.click('#scRun');
  await p.waitForFunction(() => /^Scan complete/.test(document.getElementById('scProg').textContent),
    { timeout: 30000 });
  const scan = await p.evaluate(() => ({
    prog: document.getElementById('scProg').textContent,
    cols: [...document.querySelectorAll('#paneScan .col h5')].map(h => h.childNodes[0].textContent.trim()),
    counts: [...document.querySelectorAll('#paneScan .col h5 span')].map(s => s.textContent),
    firstTerm: (document.querySelector('#paneScan .col li span') || {}).textContent,
  }));

  // the scan filled the form, so the quote prices what was measured
  const form = await p.evaluate(() => {
    document.getElementById('gen').click();          // scan pane -> form
    return {reviews: document.querySelector('#form [data-k="reviews"]').value,
            locations: document.querySelector('#form [data-k="locations"]').value,
            volume: document.querySelector('#form [data-k="volume"]').value};
  });

  await p.click('#gen');                              // Generate Quote
  await p.waitForSelector('.prod[data-row="2"] .qres', { timeout: 15000 });
  const res = await p.evaluate(() => {
    const R = {};
    const q = document.querySelector('.prod[data-row="2"] .qres');
    R.headline = q.querySelector('summary').textContent.trim();
    R.tiles = [...q.querySelectorAll('.qtile')].map(t =>
      t.querySelector('small').textContent + ' ' + t.querySelector('b').textContent);
    R.folds = [...q.querySelectorAll('.qfold > summary')].map(s => s.textContent.replace(/\s+/g, ' ').trim());
    R.planner = [...q.querySelectorAll('.pview .pv')]
      .map(x => x.querySelector('small').textContent + ': ' + x.querySelector('b').textContent);
    R.closed = [...q.querySelectorAll('.qfold')].every(f => !f.open);
    const foldBy = re => [...q.querySelectorAll('.qfold')]
      .find(f => re.test(f.querySelector('summary').textContent));
    const ordFold = foldBy(/^Order form/), proFold = foldBy(/^Proposal/);
    ordFold.open = true; proFold.open = true;
    const rowIn = (fold, k) => {
      const tr = [...fold.querySelectorAll('tbody tr')]
        .find(t => (t.querySelector('td span') || {}).textContent === k);
      return tr ? [...tr.children].map(td => td.textContent.trim()) : null;
    };
    R.ordSections = [...ordFold.querySelectorAll('tr.sec th')].map(t => t.textContent.trim());
    R.proSections = [...proFold.querySelectorAll('tr.sec th')].map(t => t.textContent.trim());
    R.reviewsRow = rowIn(ordFold, 'reviews_count');
    R.snapshotRow = rowIn(proFold, 'negative_terms');
    R.starsRow = rowIn(proFold, 'review_breakdown');
    R.partnerRow = rowIn(ordFold, 'partner_monthly_cost');
    R.partnerNotOnProposal = rowIn(proFold, 'partner_monthly_cost');
    R.stratRow = rowIn(ordFold, 'strategy');
    R.noKeywordTable = !proFold.querySelector('table.kv');
    return R;
  });

  const seq = calls.map(c => c.url).filter(u => u !== '/api/config');
  const quoteCall = calls.find(c => c.url === '/api/rep_quote') || { body: {} };

  const want = {
    'orm.stepOneIsAScan': [pane.pill.replace(/^\S+\s/, ''), 'Brand Scan'],
    'orm.generateIsAQuote': [pane.gen, 'Generate Quote'],
    'orm.paneTitle': [opened.title, 'Brand Scan'],
    'orm.scanPaneOpens': [opened.scanPane, true],
    'orm.noKeywordBuilder': [opened.noKeywordPane, true],
    'orm.brandFromRow': [opened.brand, 'Sage Dental'],
    'scan.order': [seq.slice(0, 4).join(','),
      '/api/rep_scan_locations,/api/rep_scan_terms,/api/rep_scan_serp,/api/rep_scan_autocomplete'],
    'scan.countsReviews': [seq.slice(4, 6).join(','),
      '/api/rep_reviews_submit,/api/rep_reviews_collect'],
    'scan.cols': [scan.cols.join(','), 'Negative terms,Page one,Locations'],
    'scan.counts': [scan.counts.join(','), '3,3,3'],
    'scan.firstTerm': [scan.firstTerm, 'sage dental reviews'],
    'scan.namesTheListing': [/Google lists them as/.test(scan.prog), true],
    'scan.reportsWhatItFound': [scan.prog.split(' · ').slice(1, 4).join(' · '),
      '14 flagged reviews · 3 locations · 1,030/mo brand volume'],
    'form.reviewsFilled': [form.reviews, '14'],
    'form.locationsFilled': [form.locations, '3'],
    'form.volumeFilled': [form.volume, '1030'],
    'quote.campaignFromStrategy': [quoteCall.body.campaign, 'bundle'],
    'quote.reviewsCounted': [(quoteCall.body.reviews || {}).count, 14],
    'quote.sitesCounted': [`${(quoteCall.body.articles || {}).standard}/${(quoteCall.body.articles || {}).premium}`, '2/1'],
    'quote.volumeCarried': [(quoteCall.body.search || {}).volume, 1030],
    'quote.locationsCarried': [(quoteCall.body.shield || {}).locations, 3],
    'quote.pagesCarried': [((quoteCall.body.articles || {}).pages || []).length, 3],
    'quote.marginIsFraction': [quoteCall.body.margin_pct, 0.35],
    'order.strategyTravels': [res.stratRow.join(' | '),
      'StrategystrategyOrder form | 4 · Review Removals, Site/Article Removals, Reactive…']
      .map(x => typeof x === 'string' ? x.replace('Order form', '') : x),
    'res.headline': [res.headline, 'Quote results — $3,100/mo · 2 lines · 4 workstreams'],
    'res.tiles': [res.tiles.join(' / '),
      'Monthly $3,100 / Removals — max $1,000 / Total $19,600'],
    'res.noKeywordFold': [res.folds.some(f => /Keyword table/.test(f)), false],
    'res.plannerView': [res.planner.slice(0, 3).join(' | '),
      'Reactive — Search Protection: $3,100/mo | Proactive — Brand Shield: $5,000/mo'
      + ' | Review removals: 14 × $100'],
    'res.foldsStartClosed': [res.closed, true],
    'order.sections': [res.ordSections.join(' / '),
      'Product card / Partner cost and margin'],
    'proposal.sections': [res.proSections.join(' / '), 'Proposal payload'],
    'order.reviewsCounted': [res.reviewsRow.join(' | '), '# of Reviewsreviews_count | 14'],
    'proposal.snapshotTerms': [res.snapshotRow[1],
      '3 · sage dental reviews, sage dental lawsuit, sage dental complaints'],
    'proposal.starsCaptured': [res.starsRow[1], 'locations: 3 · flagged: 14 · one_star: 9'],
    'order.partnerCost': [res.partnerRow.join(' | '),
      'Partner Hard Cost — per monthpartner_monthly_cost | $2,015'],
    'proposal.noPartnerCost': [res.partnerNotOnProposal, null],
    'proposal.noKeywordTable': [res.noKeywordTable, true],
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
