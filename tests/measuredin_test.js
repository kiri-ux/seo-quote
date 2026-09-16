// THE AREA MEASURED, NOT THE COUNTRY IT SITS IN. A nine-market Mississippi
// build read "90/mo measured · United States", which says the demand was
// measured nationally. It was not.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast', {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"]', {timeout:15000});

  const noteFor = (markets, national) => p.evaluate(({markets, national}) => {
    const r = ROWS[0];
    r.data.g_city = markets.length ? 1 : 0;
    r.data.city = markets.slice();
    r.data.g_country = national ? 1 : 0;
    r.data.national = national ? 1 : 0;
    r.band = null; r._bandKey = null;
    r.kw = r.kw || {};
    r.kw.all = [{kw: 'x', vol: 90}];
    r.kw.total_volume = 90;
    ROW = 0;
    kbDraw(r);
    return document.getElementById('kbNote').textContent;
  }, {markets, national});

  const nine = ['Oxford, MS', 'Grenada, MS', 'Batesville, MS', 'Cleveland, MS',
                'Greenwood, MS', 'Indianola, MS', 'Lexington, MS', 'Hernando, MS',
                'Clarksdale, MS'];
  let t = await noteFor(nine, false);
  say('nine.notTheCountry', !/United States/.test(t), t);
  say('nine.countsMarkets', /9 markets/.test(t), t);
  say('nine.keepsTheVolume', /90\/mo measured/.test(t), t);

  t = await noteFor(['Oxford, MS', 'Grenada, MS'], false);
  say('two.namesThem', /Oxford, MS, Grenada, MS/.test(t), t);
  say('two.notTheCountry', !/United States/.test(t), t);

  t = await noteFor(['Oxford, MS'], false);
  say('one.namesIt', /Oxford, MS/.test(t), t);

  // Nationwide IS the country, and says so.
  t = await noteFor([], true);
  say('national.saysCountry', /United States/.test(t), t);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
