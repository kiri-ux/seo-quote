// THE ADTINI TAB IS THE TOOL, NOT A MOCK OF IT.
//
// Keyword Builder is step 1 and calls /api/keywords then /api/refine. Generate
// Forecast runs steps 2-4 -- metrics, rankings in batches, price -- and the row
// opens to the quote it produced. The DataForSEO calls are stubbed so this
// measures the wiring: which endpoint, with which payload, in which order.
// (2026-09-15, Kiri)
const { chromium } = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5202';

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
    return json(route, {});
  });

  await p.goto(BASE + '/adtini/forecast', { waitUntil: 'domcontentloaded' });

  // ---------------- step 1: the keyword builder ----------------
  await p.click('[data-open="0"][data-view="form"]');
  await p.click('#kwBuilder');
  await p.click('#kbBuild');
  await p.waitForFunction(() => /^Built /.test(document.getElementById('saved').textContent));

  const kb = await p.evaluate(() => ({
    scope: document.getElementById('kbScope').value,
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
    const io = [...q.querySelectorAll('.qfold')].find(f => /Sent to the IO/.test(f.textContent));
    R.ioKeys = [...io.querySelectorAll('table.kv td:first-child')].map(td => td.textContent.trim());
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
    'kb.calledKeywordsThenRefine': [seq.slice(0, 2).join(','), '/api/keywords,/api/refine'],
    'kb.seedsSent': [Array.isArray(kwCall.body.keywords) && kwCall.body.keywords.length > 0, true],
    'kb.countrySent': [kwCall.body.country, 'US'],
    'kb.refineGetsBuckets': [refCall.body.ultra && refCall.body.ultra.length, 1],
    'kb.refineGetsBand': [!!refCall.body.geo_scope, true],
    // the pane opens on the row's own scope, and that scope is what prices
    'kb.scopeFromRow': [kb.scope, 'single_city'],
    'kb.countryFromRow': [kb.country, 'United States'],
    'kb.note': [kb.note, 'Built 3 terms.'],
    'kb.head': [kb.head, 'Keyword list (3 terms)'],
    'kb.counts': [kb.counts.join(','), '1,1,1'],
    'kb.terms': [kb.terms.join(' / '),
      'dental implants / dental implants boca raton / affordable dental implants near me'],
    'kb.widenShown': [kb.widenShown, true],
    'kb.widenText': [kb.widenText, 'One term is 77% of measured demand.'],
    'kb.srcTags': [srcTags.join(','), '[seed],[grid],[site]'],
    // steps 2-4
    'run.order': [seq.slice(2).join(','), '/api/metrics,/api/rankings,/api/price'],
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
      'Sent to the IO — 3 fields / Keyword table — 3 terms'
      + ' / Sent to the proposal — 3 fields'],
    'res.rankRows': [res.rankRows.join(' // '),
      'dental implants | 3,600 | 4 // dental implants boca raton | 880 | Not Found'
      + ' // affordable dental implants near me | 210 | Not Found'],
    'res.ioKeys': [res.ioKeys.join(','), 'package,months,markup_pct'],
    'res.modalClosed': [res.modalClosed, true],
    'res.historyCols': [res.historyCols.join('|'),
      'Date Forecasted|Forecast Prompt|Generated Response|Type|Error'],
    'res.historyRows': [res.historyRows, 1],
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
