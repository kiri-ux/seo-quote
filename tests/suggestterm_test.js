// THE SCAN FINDS THE TERM. "seascape reviews" is a cruise ship, and so is
// "seascape inc reviews" here; it keeps going until page one is the client's,
// and says what it tried. No field to type in. (2026-09-25, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

const SHIP = [{domain: 'cruisecritic.com', title: 'MSC Seascape Review'},
              {domain: 'reddit.com', title: 'MSC Seascape : r/MSCCruises'},
              {domain: 'cruiseline.com', title: 'MSC Seascape Cruise Review'}];
const OURS = [{pos: 1, domain: 'seascapeinc.net', url: 'https://seascapeinc.net', owned: true,
               title: 'Seascape Inc', tactic: 'owned — boost'},
              {pos: 2, domain: 'yelp.com', url: 'https://y', title: 'Seascape Inc - Yelp',
               tactic: 'suppression'}];
const PAGES = {
  '': {query: 'seascape reviews', suggested_query: 'seascape inc',
       organic: [], forums: [], off_brand_results: SHIP},
  'seascape inc': {query: 'seascape inc reviews', suggested_query: 'seascape los alamitos',
       organic: OURS.slice(1), forums: [], off_brand_results: SHIP.slice(0, 2)},
  'seascape los alamitos': {query: 'seascape los alamitos reviews', suggested_query: '',
       organic: OURS, forums: [], off_brand_results: []},
};

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  const bodies = [];
  await p.route('**/api/rep_scan_**', route => {
    const url = new URL(route.request().url()).pathname;
    const body = JSON.parse(route.request().postData() || '{}');
    if (url === '/api/rep_scan_serp') {
      bodies.push(body);
      return json(route, Object.assign({owned_in_top10: 0}, PAGES[body.query || '']));
    }
    if (url === '/api/rep_scan_terms') bodies.push({terms: body.query});
    return json(route, {});
  });
  await p.route('**/api/rep_reviews_**', route => json(route, {pending: [], done: []}));

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.click('[data-open="2"][data-view="form"]');
  await p.waitForSelector('#form [data-k="brand"]');
  say('noSearchTermField', !(await p.$('#form [data-k="search_as"]')));
  await p.fill('#form [data-k="brand"]', 'Seascape, Inc');
  await p.fill('#form [data-k="site"]', 'https://www.seascapeinc.net/');
  await p.click('#scRun');
  await p.waitForFunction(() => /^Scan complete/.test(scProg.textContent), {timeout: 30000});

  const serps = bodies.filter(x => !('terms' in x));
  say('keepsTryingUntilItIsTheClients',
      serps.map(x => x.query || '').join('|') === '|seascape inc|seascape los alamitos',
      JSON.stringify(serps.map(x => x.query)));
  say('neverRepeatsATerm', JSON.stringify(serps[2].tried) === '["seascape inc"]',
      JSON.stringify(serps[2].tried));
  say('theVolumeUsesTheTermItSettledOn',
      bodies.some(x => x.terms === 'seascape los alamitos'),
      JSON.stringify(bodies.filter(x => 'terms' in x)));

  const box = await p.$eval('#scWarn .scw', e => ({cls: e.className, text: e.textContent}));
  say('greenWhenItFoundThem', /\bok\b/.test(box.cls), box.cls);
  say('saysWhatItSearchedAndThatItIsThem',
      /Searched seascape los alamitos reviews · 2 of 2 results name Seascape, Inc · seascapeinc\.net #1/
        .test(box.text), box.text);
  say('andWhatItMovedOff',
      /“seascape reviews”: 3 of 3 another company's · “seascape inc reviews”: 2 of 3 another company's/
        .test(box.text), box.text);

  // A RE-RUN STARTS FROM THE BRAND: nothing typed is carried.
  bodies.length = 0;
  await p.click('#scRun');
  await p.waitForFunction(() => /^Scan complete/.test(scProg.textContent)
    && !document.getElementById('scRun').disabled, {timeout: 30000});
  say('aReRunFindsItAgain',
      bodies.filter(x => !('terms' in x)).map(x => x.query || '').join('|')
        === '|seascape inc|seascape los alamitos');

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
