// KEEP A TERM THE FLOOR DROPPED. Expand names what measured under the floor,
// and a click puts that one term on the seed box -- no Config trip, no lower
// floor for every other term. (2026-10-02, Kiri)
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  await p.route('**/api/**', route => {
    const u = new URL(route.request().url()).pathname;
    const body = /expand_services$/.test(u)
        ? {services: [], floor: 20, proposed: 2,
           rejected: [{term: 'dental implants', volume: 10},
                      {term: 'implants', volume: 0}]}
      : /site_services$/.test(u) ? {services: [{term: 'root canal', volume: 5}], floor: 20}
      : {};
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  });
  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil: 'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout: 15000});
  await p.evaluate(() => {
    const r = ROWS[ROW];
    r.data.focus = ['Implants', 'Dental Work'];
    r.data.site = 'https://example.com/';
    r.seedDrop = []; r.seedSrc = {}; r.suggested = []; r.rankedSeeds = [];
    open(ROW, 'kw');
  });
  await p.waitForTimeout(300);
  await p.click('#kbExpandRun');
  await p.waitForSelector('#saved [data-keepterm]', {timeout: 20000});
  const offered = await p.$$eval('#saved [data-keepterm]', ns => ns.map(n => n.dataset.keepterm));
  say('names the dropped terms', offered.join('|') === 'dental implants|root canal',
      JSON.stringify(offered));
  await p.click('#saved [data-keepterm="dental implants"]');
  const seeds = await p.$$eval('#paneKw [data-chips="seeds"] .chip',
    ns => ns.map(n => n.firstChild.textContent.trim()));
  say('click adds it to the seeds', seeds.includes('dental implants'), JSON.stringify(seeds));
  say('the button goes once used',
      !(await p.$('#saved [data-keepterm="dental implants"]')));
  say('the rest stay offered', !!(await p.$('#saved [data-keepterm="root canal"]')));
  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok');
  process.exit(bad ? 1 : 0);
})();
