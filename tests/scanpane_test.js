// STEP 1 IS ON THE FORM, AND THE SNAPSHOT READS BACK ON THE QUOTE.
//
// The rebuild kept four counts and dropped everything the counts were read off
// — ratings, tactics, the AI Overview, related searches, the per-location star
// split, and every control that let a planner disagree with the scan. Ported
// back from the legacy Reputation page (2026-09-17, Kiri). Each block below is
// one of those, so a regression names itself.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

const SERP = {
  query: 'bright dental co reviews',
  organic: [
    {pos: 1, domain: 'ripoffreport.com', url: 'https://r/1', title: 'Ripoff Report',
     tactic: 'site removal', rating: 1.4, votes: 90},
    {pos: 2, domain: 'brightdental.com', url: 'https://brightdental.com',
     title: 'Bright Dental', owned: true, tactic: 'owned — boost'},
    {pos: 3, domain: 'yelp.com', url: 'https://yelp.com/x', title: 'Yelp',
     tactic: 'suppression', rating: 2.6, votes: 41},
    {pos: 4, domain: 'angi.com', url: 'https://angi.com/x', title: 'Angi',
     tactic: 'positive — leave', rating: 4.6},
  ],
  forums: [{pos: 7, domain: 'reddit.com', url: 'https://reddit.com/x',
            title: 'r/dentistry thread', tactic: 'site removal'}],
  owned_in_top10: 1,
  ai_overview: 'Bright Dental has faced a lawsuit over billing practices.',
  ai_negative: ['lawsuit'],
  related: ['bright dental co complaints'],
  negative_related: ['bright dental co complaints'],
  negative_pasf: [],
  off_brand_phrases: ['shiny smiles dental reviews'],
};

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  let serpCalls = 0, serpBody = {};

  await p.route('**/api/rep_scan_**', route => {
    const url = new URL(route.request().url()).pathname;
    if (url === '/api/rep_scan_locations') return json(route, {
      strategy: 'domain', total_reviews: 300, locations: [
        {title: 'Bright Dental Midtown', place_id: 'p1', reviews: 212, rating: 3.9,
         address: '12 Main St'},
        {title: 'Bright Dental Southside', place_id: 'p2', reviews: 88, rating: 4.4,
         address: '400 South Ave'}]});
    if (url === '/api/rep_scan_terms') return json(route, {
      terms: [{term: 'bright dental co lawsuit', volume: 260, 'class': 'negative'},
              {term: 'bright dental co reviews', volume: 90, 'class': 'watch'},
              {term: 'bright dental co hours', volume: 40, 'class': 'neutral'}],
      total_volume: 390, negative_volume: 260, watch_volume: 90});
    if (url === '/api/rep_scan_serp') {
      serpCalls++;
      try { serpBody = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
      return json(route, SERP);
    }
    if (url === '/api/rep_scan_autocomplete') return json(route, {
      'bright dental co': {suggestions: ['bright dental co sued', 'bright dental co hours'],
                           negative: ['bright dental co sued']},
      'bright dental co reviews': {suggestions: [], negative: []}});
    return json(route, {});
  });
  await p.route('**/api/rep_reviews_submit', route => json(route, {
    tasks: [{id: 't1', place_id: 'p1', ok: true}, {id: 't2', place_id: 'p2', ok: true}]}));
  await p.route('**/api/rep_reviews_collect', route => json(route, {pending: [], done: [
    {id: 't1', place_id: 'p1', title: 'Bright Dental Midtown', profile_rating: 3.9,
     profile_reviews: 212, neg_1: 18, neg_2: 9, neg_1_2: 27, weak_3: 12},
    {id: 't2', place_id: 'p2', title: 'Bright Dental Southside', profile_rating: 4.4,
     profile_reviews: 88, neg_1: 3, neg_2: 2, neg_1_2: 5, weak_3: 4}]}));

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.click('[data-open="2"][data-view="form"]');            // the ORM row
  await p.waitForSelector('#form [data-k="brand"]');

  // ============================================ step 1 is on the form
  // The scan used to be a second pane you opened, scanned in, and came back
  // from -- and the only parts of it that change the price, which listings are
  // this client's and the flag threshold, were stranded over there.
  await p.fill('#form [data-k="brand"]', 'Bright Dental Co');
  await p.fill('#form [data-k="site"]', 'https://www.brightdental.com/');
  const step1 = await p.evaluate(() => ({
    runOnForm: !!document.querySelector('#form #scRun'),
    noScanPane: !document.getElementById('paneScan'),
    noSecondPaneButton: document.getElementById('kwBuilder').hidden,
    gen: document.getElementById('gen').textContent.trim(),
    back: document.getElementById('back').hidden,
  }));
  say('scanRunsFromTheForm', step1.runOnForm);
  // AUTO-SUGGEST / RELATED WAS A CHOICE THAT DOES NOT EXIST: Search Protection
  // is priced as one bundle that always includes it, and nothing read the flag.
  say('noAutoSuggestToggle',
      await p.evaluate(() => !document.querySelector('#form [data-k="autosuggest"]')));
  // "# of Sites" reads like a thing you type; it is a count the scan flags.
  say('theSiteCountIsCalledFlaggedSites',
      await p.evaluate(() => [...document.querySelectorAll('#form label')]
        .some(l => /^Flagged Sites/.test(l.textContent.trim()))));
  say('theSeparatePaneIsGone', step1.noScanPane);
  say('andSoIsItsButton', step1.noSecondPaneButton);
  say('generateIsTheOnlyOtherStep', step1.gen === 'Generate Quote', step1.gen);
  say('noBackToAPaneThatIsGone', step1.back);

  say('theButtonSaysRun', (await p.textContent('#scRun')).trim() === 'Run brand scan',
      await p.textContent('#scRun'));
  await p.click('#scRun');
  await p.waitForFunction(() => /^Scan complete/.test(scProg.textContent), {timeout: 30000});
  // ONE BUTTON. Results and auto-suggest had their own re-pulls, which asked
  // the planner to work out which half of a scan they wanted.
  say('andRerunAfterwards', (await p.textContent('#scRun')).trim() === 'Re-run scan',
      await p.textContent('#scRun'));
  say('noPartialRepullButtons',
      await p.evaluate(() => !document.getElementById('scRepullSerp')
                          && !document.getElementById('scRepullAc')));

  // ============================================ 1. the scan fills the form
  const form = await p.evaluate(() => ({
    reviews: document.querySelector('#form [data-k="reviews"]').value,
    locations: document.querySelector('#form [data-k="locations"]').value,
    volume: document.querySelector('#form [data-k="volume"]').value,
    std: document.querySelector('#form [data-k="std"]').value,
    strategy: [...document.querySelectorAll('#form [data-chips="strategy"] .chip')]
      .map(c => c.firstChild.textContent.trim()),
  }));
  say('flaggedReviewsFilled', form.reviews === '32', form.reviews);          // 27 + 5
  say('locationsFilled', form.locations === '2', form.locations);
  say('volumeFilledFromTheScansOwnTotal', form.volume === '390', form.volume);
  // ripoffreport + reddit route to site removal; yelp suppresses, angi is
  // positive, brightdental.com is theirs.
  say('siteCountFilledFromRemovablePages', form.std === '2', form.std);
  say('strategyPickedFromWhatWasFound',
      ['Review Removals', 'Site/Article Removals', 'Reactive']
        .every(x => form.strategy.includes(x)), form.strategy.join(','));
  say('progressNamesTheRemovablePages', /2 removable pages/.test(
      await p.textContent('#scProg')), await p.textContent('#scProg'));
  // THE GEOGRAPHIC TARGETING AREAS DO SOMETHING NOW. Every scan call was
  // hardcoded to the whole country, so a local client's page one came back
  // full of companies in other states.
  say('theScanIsToldWhichMarket',
      (serpBody.geo_values || []).length > 0, JSON.stringify(serpBody.geo_values));

  // ============================================ the form carries what changes the price
  const onForm = await p.evaluate(() => ({
    warn: document.getElementById('scWarn').textContent,
    locs: document.getElementById('scLocs').textContent,
    // these are a record, not a control: they belong on the quote
    noTermsHere: !document.querySelector('#form .col'),
    noPageOneHere: !/PAGE ONE/i.test(document.getElementById('form').textContent),
    boxes: document.querySelectorAll('#scLocs .sclx').length,
  }));
  say('negativeVolumeCalloutOnTheForm', /260\/mo on negative terms/.test(onForm.warn), onForm.warn);
  say('aiOverviewOnTheForm', /AI Overview/.test(onForm.warn), onForm.warn);
  say('locationsAreOnTheForm', /2 of 2 · by website/.test(onForm.locs), onForm.locs);
  say('withAStarSplit', /18/.test(onForm.locs) && /12/.test(onForm.locs), onForm.locs);
  // FLAGGED IS 1-2 STAR: the threshold dropdown had two settings and nobody
  // picked the other one.
  say('noThresholdDropdown',
      await p.evaluate(() => !document.getElementById('scTh')));
  say('andACheckboxPerLocation', onForm.boxes === 2, String(onForm.boxes));
  say('theRecordPanelsAreNotOnTheForm', onForm.noTermsHere && onForm.noPageOneHere);

  // ============================================ excluding a location
  await p.uncheck('#scLocs .sclx[data-pid="p2"]');
  await p.waitForTimeout(200);
  const after = await p.evaluate(() => ({
    reviews: document.querySelector('#form [data-k="reviews"]').value,
    locations: document.querySelector('#form [data-k="locations"]').value,
    head: document.querySelector('#scLocs .scth').textContent,
  }));
  say('excludingALocationDropsItsReviews', after.reviews === '27', after.reviews);
  say('andDropsTheLocationCount', after.locations === '1', after.locations);
  say('andTheHeadSaysOneOfTwo', /1 of 2/.test(after.head), after.head);
  await p.check('#scLocs .sclx[data-pid="p2"]');
  await p.waitForTimeout(200);
  say('checkingItBackRestoresTheCount',
      (await p.inputValue('#form [data-k="reviews"]')) === '32');

  // ============================================ a re-run is a whole scan
  const before = serpCalls;
  await p.click('#scRun');
  await p.waitForFunction(() => /^Scan complete/.test(scProg.textContent), {timeout: 30000});
  say('aRerunPullsPageOneAgain', serpCalls === before + 1, `${before} -> ${serpCalls}`);
  say('andTheCountsSurvive',
      (await p.inputValue('#form [data-k="volume"]')) === '390',
      await p.inputValue('#form [data-k="volume"]'));

  // ============================================ brand / domain mismatch
  const mismatch = await p.evaluate(() => {
    const r = ROWS[ROW];
    const keep = r.data.brand;
    r.data.brand = 'Acme Roofing';
    scanDraw(r);
    const t = document.getElementById('scWarn').textContent;
    r.data.brand = keep;
    scanDraw(r);
    return {warned: t, gone: document.getElementById('scWarn').textContent};
  });
  say('mismatchIsFlagged', /do not match|not in the website/.test(mismatch.warned),
      mismatch.warned.slice(0, 120));
  say('mismatchOffersTheDomainName', /Use the name from the website/.test(mismatch.warned));
  say('aMatchingPairIsNotFlagged', !/do not match/.test(mismatch.gone),
      mismatch.gone.slice(0, 120));

  // ============================================ the quote shows the scan
  await p.click('#gen');
  await p.waitForSelector('.prod[data-row="2"] .qres', {state: 'attached', timeout: 20000});
  const fold = await p.evaluate(() => {
    const prod = document.querySelector('.prod[data-row="2"]');
    prod.querySelector('.ptabs button[data-tab="history"]').click();
    if (!prod.querySelector('[data-pane="history"] tr.histopen'))
      prod.querySelector('.hist tr.histrow .btn-open').click();
    const q = document.querySelector('.prod[data-row="2"] [data-pane="history"] tr.histopen');
    const f = [...q.querySelectorAll('.qfold > summary')]
      .find(x => /Reputation snapshot/.test(x.textContent));
    if (!f) return {missing: true};
    f.click();
    const box = f.parentNode.querySelector('.scfold');
    return {
      head: f.textContent,
      cols: [...box.querySelectorAll('.col h5')].map(h => h.childNodes[0].textContent.trim()),
      pageOne: /PAGE ONE/i.test(box.textContent),
      locations: /LOCATIONS/i.test(box.textContent),
      firstTerm: box.querySelector('.col li > span').firstChild.textContent,
      ratingShown: /1\.4★ \(90\)/.test(box.textContent),
      tacticShown: /SITE REMOVAL/i.test(box.textContent),
      relatedLabel: /related search/.test(box.textContent),
      // the checkboxes are a record here, not a control
      boxesInert: getComputedStyle(box.querySelector('.sclx')).pointerEvents === 'none',
      tiles: [...q.querySelectorAll('.qtile small')].map(t => t.textContent),
      planner: [...q.querySelectorAll('.pv tr, .plannerview tr')].map(t =>
        t.textContent.replace(/\s+/g, ' ').trim()),
    };
  });
  say('theQuoteCarriesTheSnapshot', !fold.missing);
  say('headNamesTheBrandAndItsVolume', /Bright Dental Co · 390\/mo/.test(fold.head || ''),
      fold.head);
  say('bothColumnsAreThere',
      (fold.cols || []).join(',') === 'Negative terms,Auto-suggest & related',
      (fold.cols || []).join(','));
  say('pageOneIsOnTheQuote', fold.pageOne);
  say('locationsAreOnTheQuote', fold.locations);
  say('withRatings', fold.ratingShown);
  say('withTactics', fold.tacticShown);
  say('negativeTermLeads', fold.firstTerm === 'bright dental co lawsuit', fold.firstTerm);
  // "related" did not say related to what.
  say('relatedSaysWhichBlockItCameFrom', fold.relatedLabel);
  say('theQuotesCheckboxesAreInert', fold.boxesInert);

  // ============================================ nothing spills out
  const fits = await p.evaluate(() => {
    const over = [...document.querySelectorAll('.qfold .scfold *')]
      .filter(e => e.scrollWidth > e.clientWidth + 2 && /TABLE/.test(e.tagName))
      .map(e => e.tagName);
    return over;
  });
  say('theFoldsTablesFit', fits.length === 0, fits.join(','));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
