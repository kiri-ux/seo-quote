// "0/MO BRAND VOLUME" ON A CLIENT WHO HAS BRAND VOLUME.
//
// Cisney & O'Donnell PA scanned to zero. Not a quiet market: every name match
// on this page tested the ENTERED name against the phrase, and no phrase
// anyone types ends in "pa". So the term universe summed to nothing, Search
// Protection priced off its floor, and both of the client's own related
// searches landed in the "they name a different company" box.
//
// The server side is covered by tests/brandcore_test.py. This drives the real
// page, because adtini.html carries its OWN copy of the filters — the quote's
// negative phrases are picked client-side, so a fixed server and a stale
// mirror still ship the bug.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

const BRAND = "Cisney & O'Donnell PA";
const LISTED = "Cisney & O'Donnell Builders & Remodelers";

// What the scan comes back with once the server stops discarding it. Note the
// three spellings of one business and the one phrase that is somebody else.
const TERMS = {
  terms: [{term: "cisney & o'donnell", volume: 210, 'class': 'neutral'},
          {term: 'cisney odonnell reviews', volume: 70, 'class': 'watch'},
          {term: "cisney and o'donnell complaints", volume: 20, 'class': 'negative'}],
  total_volume: 300, negative_volume: 20, watch_volume: 70};

const SERP = {
  query: "cisney & o'donnell reviews",
  organic: [{pos: 1, domain: 'cisneyremodeling.com', url: 'https://cisneyremodeling.com',
             title: 'Cisney Remodeling', owned: true, tactic: 'owned — boost'},
            {pos: 2, domain: 'yelp.com', url: 'https://yelp.com/x', title: 'Yelp',
             tactic: 'suppression', rating: 2.1, votes: 14}],
  forums: [], owned_in_top10: 1, ai_overview: '', ai_negative: [],
  // Their own phrases, in the two spellings Google returns them in.
  related: ["cisney & o'donnell complaints", 'cisney odonnell reviews'],
  negative_related: ["cisney & o'donnell complaints"],
  negative_pasf: ['cisney and odonnell lawsuit'],
  // ...and one that really is a different company.
  off_brand_phrases: [],
};

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  const sent = {};

  await p.route('**/api/rep_scan_**', route => {
    const url = new URL(route.request().url()).pathname;
    try { sent[url] = JSON.parse(route.request().postData() || '{}'); } catch (e) {}
    if (url === '/api/rep_scan_locations') return json(route, {
      strategy: 'domain', total_reviews: 27,
      locations: [{title: LISTED, place_id: 'theirs', reviews: 27, rating: 4.3,
                   address: '11923 William Penn Hwy, Huntingdon, PA 16652'}]});
    if (url === '/api/rep_scan_terms') return json(route, TERMS);
    if (url === '/api/rep_scan_serp') return json(route, SERP);
    if (url === '/api/rep_scan_autocomplete') return json(route, {
      "cisney & o'donnell": {suggestions: ["cisney & o'donnell complaints"],
                             negative: ["cisney & o'donnell complaints"]},
      "cisney & o'donnell reviews": {suggestions: [], negative: []}});
    return json(route, {});
  });
  await p.route('**/api/rep_reviews_submit', route => json(route, {
    tasks: [{id: 't1', place_id: 'theirs', ok: true}]}));
  await p.route('**/api/rep_reviews_collect', route => json(route, {pending: [], done: [
    {id: 't1', place_id: 'theirs', title: LISTED, profile_rating: 4.3,
     profile_reviews: 27, neg_1: 4, neg_2: 0, neg_1_2: 4, weak_3: 1}]}));

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.click('[data-open="2"][data-view="form"]');
  await p.waitForSelector('#form [data-k="brand"]');
  await p.fill('#form [data-k="brand"]', BRAND);
  await p.fill('#form [data-k="site"]', 'https://cisneyremodeling.com');
  await p.click('#scRun');
  await p.waitForFunction(
    () => /Scan complete/.test(document.getElementById('scProg').textContent),
    null, {timeout: 60000});

  // ====================================== the number the operator asked about
  const prog = await p.evaluate(() => document.getElementById('scProg').textContent);
  say('progressNoLongerSaysZeroVolume', !/\b0\/mo brand volume/.test(prog), prog);
  say('progressCarriesTheMeasuredVolume', /300\/mo brand volume/.test(prog), prog);
  say('searchVolumeFieldIsFilled',
      await p.evaluate(() => document.querySelector('#form [data-k="volume"]').value) === '300');

  // ====================================== and the name that was SENT
  // Google Ads was being asked to expand "cisney & o'donnell pa", a phrase
  // nobody types, and the listing title rode along so the scan could tell the
  // "pa" from a word that is part of the name.
  say('theListingNameIsSentAsAlias', (sent['/api/rep_scan_terms'] || {}).alias === LISTED,
      JSON.stringify(sent['/api/rep_scan_terms']));
  say('theSerpCallCarriesItToo', (sent['/api/rep_scan_serp'] || {}).alias === LISTED);

  // ====================================== their own phrases are not "excluded"
  // snapshotParts() builds both surfaces from one set of filters: the live
  // pane draws the warnings and the locations, the quote draws the phrase
  // lists as the record of what the price was built on.
  const snap = await p.evaluate(() => {
    const P = snapshotParts(ROWS[ROW], false);
    // boldMod() wraps the modifier in a <b>, so read the text not the markup.
    const text = h => String(h || '').replace(/<[^>]*>/g, ' ');
    return {warn: text(P.warn), lists: text(String(P.serp) + String(P.cols))};
  });
  say('noPhrasesExcludedBanner', !/phrases? excluded/.test(snap.warn),
      snap.warn.slice(0, 400));
  say('theirComplaintsPhraseIsShown', /o.?donnell\s+complaints/i.test(snap.lists),
      snap.lists.slice(0, 400));
  say('andSoIsTheSpellingWithoutTheApostrophe',
      /odonnell\s+lawsuit/i.test(snap.lists), snap.lists.slice(0, 400));

  // ====================================== and they reach the PRICE
  // negPhrases() is what both halves of Search Protection are priced off, and
  // it ran the same broken match, so a client's own negatives were dropped
  // from the quote as other people's phrases.
  const phrases = await p.evaluate(() => {
    const r = ROWS[ROW];
    return negPhrases(r).map(x => String(x).toLowerCase());
  });
  say('theNegativePhrasesReachTheQuote', phrases.length >= 2, JSON.stringify(phrases));
  say('bothSpellingsCount',
      phrases.some(x => x.includes("o'donnell complaints"))
      && phrases.some(x => x.includes('odonnell lawsuit')), JSON.stringify(phrases));

  // ====================================== the 6.6x overcharge stays shut
  // A brand made of common words must not collect other companies' phrases.
  // Same page, same filters, checked directly.
  const guard = await p.evaluate(() => ({
    others: leadsWithBrand(['holy city heating and air complaints',
                            'twin city heating and air lawsuit',
                            'city heating and air complaints'], 'City Heating and Air'),
    denver: brandRest('denver dental', 'Denver Dental Group'),
    tailNeedsTwoSources: leadsWithBrand(["cisney & o'donnell complaints"],
                                        "Cisney & O'Donnell Builders & Remodelers"),
  }));
  say('otherCompaniesStillExcluded',
      guard.others.length === 1 && guard.others[0] === 'city heating and air complaints',
      JSON.stringify(guard.others));
  say('aServiceInACityIsNotTheirBrand', guard.denver === null);
  say('aListingTailNeedsBothNames', guard.tailNeedsTwoSources.length === 0);

  await b.close();
  console.log(bad ? `FAILED ${bad}` : 'all ok');
  process.exit(bad ? 1 : 0);
})();
