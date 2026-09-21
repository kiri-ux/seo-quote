// "USE THE NAME FROM THE WEBSITE" HANDED BACK A DOMAIN WITH A CAPITAL LETTER.
//
// cisneyremodeling.com became "Cisneyremodeling" and went straight into Brand
// Name, which is the field every match in the scan reads. A domain is one word
// and a company name is not.
//
// The stem is split against the words this client is already known by -- the
// Google listing title and the name that was typed, both on screen when the
// link is drawn -- so "cisneyremodeling" splits at the only place it can.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.click('[data-open="2"][data-view="form"]');
  await p.waitForSelector('#form [data-k="brand"]');

  // The splitter, against the names the page actually has on screen.
  const got = await p.evaluate(() => {
    const LISTED = "Cisney & O'Donnell Builders & Remodelers";
    const TYPED = "Cisney & O'Donnell PA";
    return {
      hers: splitStem('cisneyremodeling', [LISTED, TYPED]),
      trade: splitStem('andersonplumbing', ['Anderson Plumbing Heating & Air']),
      shortWord: splitStem('brightdental', ['Bright Dental Co']),
      // NOTHING TO GO ON IS AN EMPTY ANSWER, not a bad guess: the caller then
      // falls through to the page title and finally to the bare stem.
      nothing: splitStem('andersonplumbing', []),
      // "and" is on the stop list and would split this at character three.
      notAtAnd: splitStem('andersonroofing', ['Anderson Roofing']),
    };
  });
  say('splitsHerClientName', got.hers === 'Cisney Remodeling', got.hers);
  say('splitsNameFromTradeWord', got.trade === 'Anderson Plumbing', got.trade);
  say('splitsAShortTradeWord', got.shortWord === 'Bright Dental', got.shortWord);
  say('noSourcesMeansNoGuess', got.nothing === '', got.nothing);
  say('doesNotSplitOnAStopWord', got.notAtAnd === 'Anderson Roofing', got.notAtAnd);

  // ...and end to end, through the form the link actually reads: scSite and
  // scBrand take the live inputs, not the saved row.
  await p.fill('#form [data-k="brand"]', "Cisney & O'Donnell PA");
  await p.fill('#form [data-k="site"]', 'https://cisneyremodeling.com');
  const end = await p.evaluate(() => {
    const r = ROWS[ROW];
    r.scan = {locations: {listed: "Cisney & O'Donnell Builders & Remodelers"},
              serp: {organic: []}, terms: {}};
    return nameFromSite(r);
  });
  say('theLinkWritesARealName', end === 'Cisney Remodeling', end);

  // NEVER WORSE THAN THE STEM IT REPLACED. With no listing and no page title
  // the answer is the old one rather than nothing.
  await p.fill('#form [data-k="brand"]', '');
  await p.fill('#form [data-k="site"]', 'https://zzqqxx.com');
  const bare = await p.evaluate(() => {
    const r = ROWS[ROW];
    r.scan = {};
    return nameFromSite(r);
  });
  say('fallsBackToTheStem', bare === 'Zzqqxx', bare);

  // The page title is the second answer, not the first: an SEO title often
  // leads with a service.
  const viaTitle = await p.evaluate(() => {
    const r = ROWS[ROW];
    r.scan = {serp: {organic: [
      {owned: true, title: 'Zed Quarry Works | Huntingdon PA'}]}};
    return nameFromSite(r);
  });
  say('usesThePageTitleWhenTheSplitCannot',
      viaTitle === 'Zed Quarry Works', viaTitle);

  await b.close();
  console.log(bad ? `FAILED ${bad}` : 'all ok');
  process.exit(bad ? 1 : 0);
})();
