// AN UNTICKED LISTING IS NOT THIS CLIENT'S, AND IT KEPT COMING BACK.
//
// Milligan Vein's scan returns five Google listings, one of which -- Vein Guys
// Crossville -- sits at the same address as their Crossville clinic and is a
// different company. Unticking it dropped it from the count, and the next
// re-run of the scan ticked it again: r.scanOff was cleared outright, so the
// listing was back in the location count and back in the price.
//
// And the snapshot on the quote showed it either way. The live pane needs every
// listing, because the checkboxes are how a planner unticks one; the snapshot
// is the record of what the price was built on, and an unticked listing is not
// part of it.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

const FIVE = [
  {title: 'Milligan Vein', place_id: 'p1', reviews: 233, rating: 4.9,
   address: '6348 Lonas Spring Dr, Knoxville, TN 37909'},
  {title: 'Milligan Vein Clinic', place_id: 'p2', reviews: 117, rating: 4.9,
   address: '1907 W Morris Blvd, Morristown, TN 37813'},
  {title: 'Milligan Vein Crossville', place_id: 'p3', reviews: 100, rating: 4.9,
   address: '1720 West Ave #101, Crossville, TN 38555'},
  {title: 'Milligan Vein Cleveland', place_id: 'p4', reviews: 10, rating: 4.9,
   address: '2850 Westside Dr NW, Cleveland, TN 37312'},
  {title: 'Vein Guys Crossville', place_id: 'p5', reviews: 0, rating: null,
   address: '1720 West Ave #101, Crossville, TN 38555'},
];
const DONE = FIVE.map((l, i) => ({
  id: 't' + i, place_id: l.place_id, title: l.title, profile_rating: l.rating,
  profile_reviews: l.reviews, neg_1: i === 4 ? 7 : 1, neg_2: 0,
  neg_1_2: i === 4 ? 7 : 1, weak_3: i === 0 ? 2 : 0}));

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});

  await p.route('**/api/rep_scan_**', route => {
    const url = new URL(route.request().url()).pathname;
    if (url === '/api/rep_scan_locations')
      return json(route, {strategy: 'domain', total_reviews: 460, locations: FIVE});
    if (url === '/api/rep_scan_terms')
      return json(route, {terms: [], total_volume: 0, negative_volume: 0,
                          watch_volume: 0, rows_returned: 18, rows_matched: 0});
    if (url === '/api/rep_scan_serp')
      return json(route, {organic: [], forums: [], owned_in_top10: 0,
                          related: [], negative_related: [], negative_pasf: []});
    if (url === '/api/rep_scan_autocomplete') return json(route, {});
    return json(route, {});
  });
  await p.route('**/api/rep_reviews_submit', route => json(route, {
    tasks: DONE.map(x => ({id: x.id, place_id: x.place_id, ok: true}))}));
  await p.route('**/api/rep_reviews_collect', route =>
    json(route, {pending: [], done: DONE}));

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.click('[data-open="2"][data-view="form"]');
  await p.waitForSelector('#form [data-k="brand"]');
  await p.fill('#form [data-k="brand"]', 'Milligan Vein');
  await p.fill('#form [data-k="site"]', 'https://www.milliganvein.com/');
  const scan = async () => {
    await p.click('#scRun');
    await p.waitForFunction(
      () => /Scan complete/.test(document.getElementById('scProg').textContent),
      null, {timeout: 60000});
  };
  await scan();

  const first = await p.evaluate(() => ({
    boxes: document.querySelectorAll('#scLocs .sclx').length,
    locs: document.querySelector('#form [data-k="locations"]').value,
    prog: document.getElementById('scProg').textContent,
  }));
  say('allFiveAreTickableOnTheLivePane', first.boxes === 5, JSON.stringify(first));
  say('andAllFiveArePriced', first.locs === '5', JSON.stringify(first));
  // A ZERO SAYS WHICH ZERO IT IS: 18 terms came back and none were theirs.
  say('theZeroSaysWhichZeroItIs',
      /18 terms, 0 theirs/.test(first.prog), first.prog);

  // Untick the one that is not theirs.
  await p.uncheck('#scLocs .sclx[data-pid="p5"]');
  const off = await p.evaluate(() => ({
    locs: document.querySelector('#form [data-k="locations"]').value,
    reviews: document.querySelector('#form [data-k="reviews"]').value,
  }));
  say('untickingDropsItFromTheCount', off.locs === '4', JSON.stringify(off));
  say('andFromTheFlaggedTotal', off.reviews === '4', JSON.stringify(off));

  // RE-RUN. The decision has to survive it.
  await scan();
  const again = await p.evaluate(() => ({
    off: JSON.parse(JSON.stringify(ROWS[ROW].scanOff || {})),
    ticked: [...document.querySelectorAll('#scLocs .sclx')]
      .filter(x => x.checked).map(x => x.dataset.pid),
    locs: document.querySelector('#form [data-k="locations"]').value,
    reviews: document.querySelector('#form [data-k="reviews"]').value,
  }));
  say('theUntickSurvivesARerun', again.off.p5 === true, JSON.stringify(again.off));
  say('andItIsStillUnticked',
      again.ticked.length === 4 && !again.ticked.includes('p5'),
      JSON.stringify(again.ticked));
  say('andStillOutOfTheCount', again.locs === '4', JSON.stringify(again));
  say('andStillOutOfTheFlaggedTotal', again.reviews === '4', JSON.stringify(again));

  // ---------------------------------------------- the quote's own snapshot
  const snap = await p.evaluate(() => {
    const r = ROWS[ROW];
    const text = h => String(h || '').replace(/<[^>]*>/g, ' ');
    return {quote: text(snapshotParts(r, false).locs),
            live: text(snapshotParts(r, true).locs)};
  });
  say('theQuoteSnapshotLeavesItOut',
      !/Vein Guys/.test(snap.quote), snap.quote.slice(0, 300));
  say('butKeepsTheFourThatArePriced',
      ['Milligan Vein', 'Milligan Vein Clinic', 'Milligan Vein Crossville',
       'Milligan Vein Cleveland'].every(t => snap.quote.includes(t)),
      snap.quote.slice(0, 300));
  say('theLivePaneStillShowsItToUntick',
      /Vein Guys/.test(snap.live), snap.live.slice(0, 300));

  // ...and the proposal and the slides get the same four.
  const sent = await p.evaluate(() => {
    const r = ROWS[ROW], sc = r.scan || {};
    return (((sc.locations || {}).locations) || [])
      .filter(l => scOn(r, l.place_id)).map(l => l.title);
  });
  say('theProposalAndSlidesGetTheSameFour',
      sent.length === 4 && !sent.includes('Vein Guys Crossville'),
      JSON.stringify(sent));

  await b.close();
  console.log(bad ? `FAILED ${bad}` : 'all ok');
  process.exit(bad ? 1 : 0);
})();
