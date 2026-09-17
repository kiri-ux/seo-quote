// WHICH TOWN THE QUOTE IS BUILT ON, AND WHETHER THAT WAS MEASURED.
//
// The primary market sets the grid suffix, the rank-check location AND the
// price, and nothing on the builder said which town won or why. ENT Consultants
// is an Oxford practice (entoxford.com) whose entire keyword list came back
// suffixed "greenwood", and the only way to find out why was to read the source
// -- which took three attempts, two of which shipped and changed nothing.
//
// The legacy form has warned on this since Ooten Law was priced on Blount County
// for a Knoxville firm. This one never got the line, and the numbers were in the
// response the whole time as city_selection.kept.
//
// Driven through kbDraw with the two shapes that matter, because the difference
// between them is the difference between a measurement and a coin toss.
const {chromium} = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 140)));
  await p.goto('http://127.0.0.1:5199/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForTimeout(1800);

  let bad = 0;
  const say = (n, ok, d) => {
    console.log((ok ? '  ok   ' : '  FAIL ') + n + (ok ? '' : ' :: ' + JSON.stringify(d)));
    if (!ok) bad++;
  };

  const out = await p.evaluate(() => {
    const res = {};
    const el = () => document.getElementById('kbMarketNote');
    const base = {all: [], ultra: [], competitive: [], long_tail: [],
                  grid_axis: {axis: 'services',
                              evidence: {cities_with_demand: 0, cities_scored: 5}}};
    ROW = 0;
    ROWS[0] = ROWS[0] || {};

    // The ENT shape: nothing cleared the floor, so the client's own town wins.
    ROWS[0].kw = Object.assign({}, base, {
      grid_cities: ['oxford, ms'],
      city_selection: {ranked_on_demand: false, measure_floor: 20,
        kept: [['oxford, ms', 0], ['greenwood, ms', 10],
               ['cleveland, ms', 0], ['grenada, ms', 0]]}});
    kbDraw(ROWS[0]);
    res.unmeasured = el().textContent;
    document.getElementById('kbMarketWhy').click();
    res.scores = el().textContent;

    // A market that genuinely measured: say what it scored and what it beat.
    ROWS[0].kw = Object.assign({}, base, {
      grid_cities: ['greenwood, ms'],
      city_selection: {ranked_on_demand: true, measure_floor: 20,
        kept: [['greenwood, ms', 90], ['oxford, ms', 10]]}});
    kbDraw(ROWS[0]);
    res.measured = el().textContent;

    // Nothing to report is nothing on screen, not an empty label.
    ROWS[0].kw = Object.assign({}, base, {grid_cities: [], city_selection: {}});
    kbDraw(ROWS[0]);
    res.empty = el().textContent;
    return res;
  });

  say('names the town the quote is built on',
      /^Built on oxford, ms/.test(out.unmeasured), out.unmeasured);
  say('and says the choice was not measured',
      /4 markets probed, none above 20\/mo/.test(out.unmeasured), out.unmeasured);
  // Without this the line is an assertion with no working. The scores are what
  // let an operator see that the winner beat nothing.
  say('the scores open every market that was probed',
      /greenwood, ms 10\/mo/.test(out.scores) && /oxford, ms 0\/mo/.test(out.scores),
      out.scores);
  say('a measured market says what it scored',
      /90\/mo, highest of 2 markets probed/.test(out.measured), out.measured);
  say('and it is the one named', /^Built on greenwood, ms/.test(out.measured), out.measured);
  say('no selection, no line', out.empty === '', out.empty);
  say('no page errors', errs.length === 0, errs);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
