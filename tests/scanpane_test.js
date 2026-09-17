// THE BRAND SCAN OPENS ON WHAT IS ALREADY ON THE FORM, AND LOOKS LIKE THE
// REST OF THE MODAL.
//
// Two things were wrong when this pane was opened for real (2026-09-17):
//
//   1. Brand name and client website were copied from the row once, when the
//      modal opened. A brand typed on the form after that never reached the
//      scan, so the first thing step 1 asked for was the thing the planner had
//      just finished typing one pane over.
//
//   2. The two fields rendered as bare browser inputs, squeezed to the right
//      half of their labels. The modal's input styling is scoped to `form` and
//      this pane is not inside one, and the .kbrow row rule was written for
//      the keyword builder, where every field is a Yes/No pill.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});

  await p.route('**/api/rep_scan_**', route => {
    const url = new URL(route.request().url()).pathname;
    if (url === '/api/rep_scan_locations') return json(route, {
      strategy: 'domain', locations: [{title: 'Bright Dental', place_id: 'p1', reviews: 12}]});
    if (url === '/api/rep_scan_terms') return json(route, {
      terms: [{term: 'bright dental lawsuit', volume: 260, 'class': 'negative'},
              {term: 'bright dental reviews', volume: 90, 'class': 'watch'},
              {term: 'bright dental hours', volume: 40, 'class': 'neutral'}],
      total_volume: 390, negative_volume: 260, watch_volume: 90});
    if (url === '/api/rep_scan_serp') return json(route, {
      organic: [{pos: 1, domain: 'ripoffreport.com', url: 'https://r/1', tactic: 'site removal'},
                {pos: 2, domain: 'brightdental.com', url: 'https://brightdental.com', owned: true,
                 tactic: 'owned — boost'}],
      forums: [{pos: 5, domain: 'reddit.com', url: 'https://reddit.com/x', tactic: 'site removal'}]});
    if (url === '/api/rep_scan_autocomplete') return json(route, {
      'bright dental': {suggestions: ['bright dental sued'], negative: ['bright dental sued']},
      'bright dental reviews': {suggestions: [], negative: []}});
    return json(route, {});
  });
  await p.route('**/api/rep_reviews_**', route => json(route, {tasks: [], done: [], pending: []}));

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.click('[data-open="2"][data-view="form"]');            // the ORM row
  await p.waitForSelector('#form [data-k="brand"]');

  // ------------------------------------------------ form -> scan, every switch
  await p.fill('#form [data-k="brand"]', 'Bright Dental');
  await p.fill('#form [data-k="site"]', 'https://www.brightdental.com/');
  await p.click('#kwBuilder');
  await p.waitForTimeout(200);
  let v = await p.evaluate(() => ({b: scBrand.value, d: scDomain.value}));
  say('brandFollowsToScan', v.b === 'Bright Dental', v.b);
  say('siteFollowsToScan', v.d === 'https://www.brightdental.com/', v.d);

  // ------------------------------------------------ scan -> form, on the way back
  await p.fill('#scBrand', 'Bright Dental Group');
  await p.click('#back');
  await p.waitForTimeout(200);
  say('correctionReachesForm',
      (await p.inputValue('#form [data-k="brand"]')) === 'Bright Dental Group');

  // ------------------------------------------------ a blank box wipes nothing
  await p.click('#kwBuilder');
  await p.waitForTimeout(150);
  await p.fill('#scDomain', '');
  await p.click('#back');
  await p.waitForTimeout(200);
  say('blankDoesNotWipe',
      (await p.inputValue('#form [data-k="site"]')) === 'https://www.brightdental.com/');

  // ------------------------------------------------ and a later edit still follows
  await p.fill('#form [data-k="brand"]', 'Bright Dental Co');
  await p.click('#kwBuilder');
  await p.waitForTimeout(200);
  say('aLaterEditStillFollows', (await p.inputValue('#scBrand')) === 'Bright Dental Co');

  // ------------------------------------------------ the pane reads as a form
  const look = await p.evaluate(() => {
    const i = document.getElementById('scBrand');
    const lab = i.closest('.f').querySelector('label');
    const cs = getComputedStyle(i);
    const ri = i.getBoundingClientRect(), rl = lab.getBoundingClientRect();
    const panel = document.querySelector('#paneScan .kbside');
    const side = panel.getBoundingClientRect();
    return {w: Math.round(ri.width), side: Math.round(side.width),
            radius: cs.borderRadius, bg: cs.backgroundColor,
            // The chip boxes on the keyword builder's side panel are the
            // reference: a field stands out against the panel, not with it.
            panelBg: getComputedStyle(panel).backgroundColor,
            stacked: rl.bottom <= ri.top + 1};
  });
  say('labelSitsAboveTheField', look.stacked, JSON.stringify(look));
  say('fieldFillsThePanel', look.w > look.side * 0.8, look.w + ' of ' + look.side);
  say('fieldIsRounded', look.radius === '10px', look.radius);
  say('fieldStandsOutFromThePanel',
      look.bg !== 'rgba(0, 0, 0, 0)' && look.bg !== look.panelBg,
      look.bg + ' on ' + look.panelBg);

  // ------------------------------------------------ empty state, then the scan
  say('saysItHasNotScanned', await p.isVisible('#scEmpty'));
  await p.click('#scRun');
  await p.waitForFunction(() => /^Scan complete/.test(scProg.textContent), {timeout: 30000});
  say('emptyStateGoesAway', !(await p.isVisible('#scEmpty')));

  const cols = await p.evaluate(() => ({
    heads: [...document.querySelectorAll('#scCols .col h5')].map(h => h.childNodes[0].textContent.trim()),
    counts: [...document.querySelectorAll('#scCols .col h5 span')].map(s => s.textContent.trim()),
    firstTerm: document.querySelector('#scCols .col li span').textContent,
  }));
  // EVERY COLUMN OFF ITS OWN KEY. These two read `.rows`, which scan_terms and
  // scan_serp have never returned, so both rendered 0 on every real scan.
  say('fourColumns', cols.heads.join(',') === 'Negative terms,Page one,Auto-suggest,Locations',
      cols.heads.join(','));
  say('negativeTermsCounted', cols.counts[0] === '2', cols.counts[0]);
  say('pageOneCounted', cols.counts[1] === '3', cols.counts[1]);
  say('autoSuggestReachesTheScreen', cols.counts[2] === '1', cols.counts[2]);
  say('locationsSayHowTheyMatched', cols.counts[3] === '1 · by website', cols.counts[3]);
  say('negativeTermLeads', cols.firstTerm === 'bright dental lawsuit', cols.firstTerm);

  // THE COUNT AND THE LIST AGREE. The heading used to carry the flagged count
  // while the list fell back to the NEUTRAL terms when nothing was flagged, so
  // a real scan printed "NEGATIVE TERMS 0" above eight terms.
  const agree = await p.evaluate(() => {
    const c = document.querySelectorAll('#scCols .col')[0];
    return {n: c.querySelector('h5 span').textContent.trim(),
            rows: c.querySelectorAll('li').length,
            neutralShown: /bright dental hours/.test(c.textContent)};
  });
  say('flaggedCountMatchesTheList', agree.n === String(agree.rows), JSON.stringify(agree));
  say('neutralTermsAreNotListedAsNegative', !agree.neutralShown);

  // the brand universe is a volume, and it is in the heading
  say('headingCarriesBrandVolume',
      /390\/mo brand volume/.test(await p.textContent('#scHead')),
      await p.textContent('#scHead'));

  // an empty column says so rather than sitting blank
  const empties = await p.evaluate(() => [...document.querySelectorAll('#scCols .col')]
    .filter(c => c.querySelector('h5 span').textContent.trim() === '0')
    .map(c => (c.querySelector('.none') || {}).textContent));
  say('anEmptyColumnSaysNone', empties.length === 0 || empties.every(t => t === 'None'),
      JSON.stringify(empties));

  // two across, not four: four columns in this sheet are ~190px and wrap
  const across = await p.evaluate(() =>
    getComputedStyle(document.getElementById('scCols')).gridTemplateColumns.split(' ').length);
  say('twoColumnsAcross', across === 2, String(across));

  // the brand volume the form is filled from is the one that was measured
  say('volumeFilledFromTheTerms',
      (await p.inputValue('#form [data-k="volume"]')) === '390',
      await p.inputValue('#form [data-k="volume"]'));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
