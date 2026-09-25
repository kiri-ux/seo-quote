// THE SCAN OFFERS A NARROWER TERM when page one is mostly somebody else's.
// "seascape reviews" is a cruise ship; one click searches "seascape inc".
// (2026-09-25)
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

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
    if (url === '/api/rep_scan_serp') {
      const body = JSON.parse(route.request().postData() || '{}');
      bodies.push(body);
      return json(route, body.query ? {
        query: 'seascape inc reviews', owned_in_top10: 0, suggested_query: '',
        organic: [{pos: 1, domain: 'yelp.com', url: 'https://y', title: 'Seascape Inc - Yelp',
                   tactic: 'suppression'}], forums: [], off_brand_results: []}
      : {query: 'seascape reviews', owned_in_top10: 0, suggested_query: 'seascape inc',
         organic: [{pos: 2, domain: 'yelp.com', url: 'https://y', title: 'Seascape Inc - Yelp',
                    tactic: 'suppression'}], forums: [],
         off_brand_results: [{domain: 'cruisecritic.com', title: 'MSC Seascape Review'},
                             {domain: 'reddit.com', title: 'MSC Seascape : r/MSCCruises'}]});
    }
    return json(route, {});
  });
  await p.route('**/api/rep_reviews_**', route => json(route, {pending: [], done: []}));

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.click('[data-open="2"][data-view="form"]');
  await p.waitForSelector('#form [data-k="brand"]');
  await p.fill('#form [data-k="brand"]', 'Seascape, Inc');
  await p.fill('#form [data-k="site"]', 'seascapeinc.net');
  await p.click('#scRun');
  await p.waitForFunction(() => /^Scan complete/.test(scProg.textContent), {timeout: 30000});

  const warn = await p.textContent('#scWarn');
  say('saysHowManyAreSomebodyElses', /2 of 3 page-one results are another company's/.test(warn), warn);
  say('namesTheTerm', /Try seascape inc/.test(warn), warn);

  await p.click('#scUseQuery');
  await p.waitForFunction(() => /^Scan complete/.test(scProg.textContent)
    && !document.getElementById('scUseQuery'), {timeout: 30000}).catch(() => {});
  say('fillsTheField', await p.inputValue('#form [data-k="search_as"]') === 'seascape inc');
  say('andSearchesIt', bodies.length === 2 && bodies[1].query === 'seascape inc',
      JSON.stringify(bodies.map(x => x.query)));
  say('theSuggestionIsGoneOnceUsed', !(await p.$('#scUseQuery')));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
