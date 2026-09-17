// THE BRAND SCAN PANE: CARRY-THROUGH, AND THE TEN THINGS THE REBUILD DROPPED.
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
  let serpCalls = 0;

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
    if (url === '/api/rep_scan_serp') { serpCalls++; return json(route, SERP); }
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

  // ============================================ carry-through, both directions
  await p.fill('#form [data-k="brand"]', 'Bright Dental Co');
  await p.fill('#form [data-k="site"]', 'https://www.brightdental.com/');
  await p.click('#kwBuilder');
  await p.waitForTimeout(200);
  let v = await p.evaluate(() => ({b: scBrand.value, d: scDomain.value}));
  say('brandFollowsToScan', v.b === 'Bright Dental Co', v.b);
  say('siteFollowsToScan', v.d === 'https://www.brightdental.com/', v.d);

  await p.fill('#scBrand', 'Bright Dental Group');
  await p.click('#back');
  await p.waitForTimeout(200);
  say('correctionReachesForm',
      (await p.inputValue('#form [data-k="brand"]')) === 'Bright Dental Group');

  await p.click('#kwBuilder');
  await p.waitForTimeout(150);
  await p.fill('#scDomain', '');
  await p.click('#back');
  await p.waitForTimeout(200);
  say('blankDoesNotWipe',
      (await p.inputValue('#form [data-k="site"]')) === 'https://www.brightdental.com/');

  await p.fill('#form [data-k="brand"]', 'Bright Dental Co');
  await p.click('#kwBuilder');
  await p.waitForTimeout(200);
  say('aLaterEditStillFollows', (await p.inputValue('#scBrand')) === 'Bright Dental Co');

  // ============================================ the pane reads as a form
  const look = await p.evaluate(() => {
    const i = document.getElementById('scBrand');
    const lab = i.closest('.f').querySelector('label');
    const cs = getComputedStyle(i);
    const ri = i.getBoundingClientRect(), rl = lab.getBoundingClientRect();
    const panel = document.querySelector('#paneScan .kbside');
    return {w: Math.round(ri.width), side: Math.round(panel.getBoundingClientRect().width),
            radius: cs.borderRadius, bg: cs.backgroundColor,
            panelBg: getComputedStyle(panel).backgroundColor,
            stacked: rl.bottom <= ri.top + 1};
  });
  say('labelSitsAboveTheField', look.stacked, JSON.stringify(look));
  say('fieldFillsThePanel', look.w > look.side * 0.8, look.w + ' of ' + look.side);
  say('fieldIsRounded', look.radius === '10px', look.radius);
  say('fieldStandsOutFromThePanel',
      look.bg !== 'rgba(0, 0, 0, 0)' && look.bg !== look.panelBg,
      look.bg + ' on ' + look.panelBg);

  say('saysItHasNotScanned', await p.isVisible('#scEmpty'));
  await p.click('#scRun');
  await p.waitForFunction(() => /^Scan complete/.test(scProg.textContent), {timeout: 30000});
  say('emptyStateGoesAway', !(await p.isVisible('#scEmpty')));

  // ============================================ 1. the scan fills the counts
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

  // ============================================ 8. the volume callout
  const warn = await p.textContent('#scWarn');
  say('negativeVolumeCallout', /260\/mo on negative terms/.test(warn), warn);
  say('watchVolumeCallout', /90\/mo on watch terms/.test(warn), warn);

  // ============================================ 2. the AI Overview
  say('aiOverviewShown', /AI Overview/.test(warn) && /billing practices/.test(warn), warn);
  say('aiOverviewNegativeNamed', /lawsuit/.test(warn), warn);

  // ============================================ 3. related searches
  const acCol = await p.evaluate(() => {
    const c = [...document.querySelectorAll('#scCols .col')]
      .find(x => /Auto-suggest/.test(x.querySelector('h5').textContent));
    return {n: c.querySelector('h5 span').textContent.trim(), text: c.textContent,
            negRows: c.querySelectorAll('li.ac.neg').length,
            magnifiers: c.querySelectorAll('li.ac .mag').length};
  });
  say('negativeRelatedReachesTheScreen', /complaints/.test(acCol.text), acCol.text);
  // ============================================ 9. the facsimile
  say('autoSuggestRendersAsSearchRows', acCol.magnifiers >= 2, String(acCol.magnifiers));
  say('negativeSuggestionsAreMarked', acCol.negRows >= 2, String(acCol.negRows));
  say('offBrandPhraseIsNamedNotHidden',
      /shiny smiles dental reviews/.test(warn) && /different company/.test(warn), warn);

  // ============================================ 6. ratings and tags
  const serp = await p.evaluate(() => {
    const t = document.querySelector('#scSerp');
    return {head: t.querySelector('.scth').textContent,
            rows: [...t.querySelectorAll('tbody tr, table tr')].slice(1).map(tr =>
              [...tr.children].map(td => td.textContent.trim()).join(' | '))};
  });
  say('pageOneCountsControlled', /1 of 4 client-controlled/.test(serp.head), serp.head);
  say('ownedIsTagged', /brightdental\.com.*owned/.test(serp.rows[1]), serp.rows[1]);
  say('thirdPartyIsTagged', /ripoffreport\.com.*3rd party/.test(serp.rows[0]), serp.rows[0]);
  say('tacticIsOnTheRow', /site removal/.test(serp.rows[0]), serp.rows[0]);
  say('ratingIsShown', /1\.4★ \(90\)/.test(serp.rows[0]), serp.rows[0]);
  say('forumsRankWithIt', serp.rows.some(x => /reddit\.com/.test(x)), serp.rows.join(' // '));

  // ============================================ 4. the star breakdown
  const locs = await p.evaluate(() => {
    const t = document.querySelector('#scLocs');
    return {head: t.querySelector('.scth').textContent,
            rows: [...t.querySelectorAll('table tr')].slice(1).map(tr =>
              [...tr.children].map(td => td.textContent.trim()).join('|')),
            hasThreshold: !!document.getElementById('scTh')};
  });
  say('locationsSayHowTheyMatched', /2 of 2 · by website/.test(locs.head), locs.head);
  say('flaggedAndWeakAreBothStated',
      /32 flagged/.test(locs.head) && /16 at 3★/.test(locs.head), locs.head);
  say('starSplitPerLocation', /\|18\|9\|12$/.test(locs.rows[0]), locs.rows[0]);
  say('profileRatingPerLocation', /3\.9★ \/ 212/.test(locs.rows[0]), locs.rows[0]);
  say('addressIsShown', /12 Main St/.test(locs.rows[0]), locs.rows[0]);
  say('thresholdIsOffered', locs.hasThreshold);

  // one star only: 18 + 3
  await p.selectOption('#scTh', '1');
  await p.waitForTimeout(200);
  say('thresholdChangesTheCount',
      (await p.inputValue('#form [data-k="reviews"]')) === '21',
      await p.inputValue('#form [data-k="reviews"]'));
  await p.selectOption('#scTh', '12');
  await p.waitForTimeout(200);

  // ============================================ 5. excluding a location
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

  // ============================================ 7. re-pull one call
  const before = serpCalls;
  await p.click('#scRepullSerp');
  await p.waitForFunction(() => /re-pulled/.test(scProg.textContent), {timeout: 15000});
  say('rePullHitsTheSerpOnce', serpCalls === before + 1, `${before} -> ${serpCalls}`);
  say('andNothingElseReRan',
      (await p.inputValue('#form [data-k="volume"]')) === '390');

  // ============================================ 10. brand / domain mismatch
  const mismatch = await p.evaluate(() => {
    const r = ROWS[ROW];
    r.data.brand = 'Acme Roofing';
    scanDraw(r);
    const t = document.getElementById('scWarn').textContent;
    r.data.brand = 'Bright Dental Co';
    scanDraw(r);
    return {warned: t, gone: document.getElementById('scWarn').textContent};
  });
  say('mismatchIsFlagged', /do not match|not in the website/.test(mismatch.warned),
      mismatch.warned.slice(0, 120));
  say('mismatchOffersTheDomainName', /Use the name from the website/.test(mismatch.warned));
  say('aMatchingPairIsNotFlagged', !/do not match/.test(mismatch.gone),
      mismatch.gone.slice(0, 120));

  // ============================================ the columns still agree
  const cols = await p.evaluate(() => ({
    heads: [...document.querySelectorAll('#scCols .col h5')].map(h => h.childNodes[0].textContent.trim()),
    negN: document.querySelector('#scCols .col h5 span').textContent.trim(),
    negRows: document.querySelectorAll('#scCols .col:first-child li').length,
    firstTerm: document.querySelector('#scCols .col li > span').firstChild.textContent,
    neutralShown: /hours/.test(document.querySelector('#scCols .col').textContent),
    across: getComputedStyle(document.getElementById('scCols'))
      .gridTemplateColumns.split(' ').length,
  }));
  say('twoColumns', cols.heads.join(',') === 'Negative terms,Auto-suggest', cols.heads.join(','));
  say('flaggedCountMatchesTheList', cols.negN === String(cols.negRows),
      cols.negN + ' vs ' + cols.negRows);
  say('neutralTermsAreNotListedAsNegative', !cols.neutralShown);
  say('negativeTermLeads', cols.firstTerm === 'bright dental co lawsuit', cols.firstTerm);
  say('headingCarriesBrandVolume',
      /390\/mo brand volume/.test(await p.textContent('#scHead')),
      await p.textContent('#scHead'));
  say('twoColumnsAcross', cols.across === 2, String(cols.across));

  // ============================================ the form, and the pane's margins
  const formShape = await p.evaluate(() => {
    const f = document.getElementById('form');
    const pane = document.getElementById('paneScan');
    const cs = getComputedStyle(pane);
    return {
      hasIndustry: !!f.querySelector('[data-chips="industry"]'),
      hasCountrySelect: !!f.querySelector('select[data-k="country"]'),
      // the geo block still asks the same question, once
      hasGeoCountry: !!f.querySelector('[data-chips="countries"]'),
      padLeft: cs.paddingLeft, padTop: cs.paddingTop,
    };
  });
  say('industryIsOnTheForm', formShape.hasIndustry);
  // COUNTRY WAS ASKED TWICE: a select, and the Geographic Targeting Areas
  // "Country" box. Nothing in the ORM quote read the select.
  say('countrySelectIsGone', !formShape.hasCountrySelect);
  say('geoCountryStillThere', formShape.hasGeoCountry);
  // #paneScan was the one pane in the modal with no padding, so the side panel
  // sat on the sheet's left edge.
  say('theScanPaneHasMargins',
      parseInt(formShape.padLeft, 10) >= 20 && parseInt(formShape.padTop, 10) >= 16,
      formShape.padLeft + ' / ' + formShape.padTop);

  // ============================================ nothing spills out of the sheet
  // The sheet is overflow:hidden, so anything wider than it is simply gone --
  // which is how the ratings column and the whole star split came to be
  // off-screen. Two rules did it: .kbmain is the 1fr grid track and would not
  // shrink below its content, and the global table{min-width:1080px} written
  // for the workflow table applied to these two as well.
  const fits = await p.evaluate(() => {
    const sheet = document.querySelector('.sheet');
    const right = sheet.getBoundingClientRect().right;
    const over = [...document.querySelectorAll('#paneScan *')]
      .filter(e => e.getBoundingClientRect().width
                && e.getBoundingClientRect().right > right + 1)
      .map(e => (e.id || e.className || e.tagName) + '@'
                + Math.round(e.getBoundingClientRect().right));
    return {over, scroll: sheet.scrollWidth, client: sheet.clientWidth};
  });
  say('nothingIsWiderThanTheSheet', fits.over.length === 0, fits.over.join(', '));
  say('andTheSheetDoesNotScrollSideways', fits.scroll <= fits.client,
      fits.scroll + ' vs ' + fits.client);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
