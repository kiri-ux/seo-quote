// A CLIENT RANKING FOR EVERYTHING HAS NO STORY IN THE PROPOSAL.
//
// The build-time reservation holds grid slots for terms the client does not
// rank for, but it can only promote from the terms the demand ranking CUT --
// so on a list whose seeds all fit the grid it has nothing to work with.
// Cisney & O'Donnell: 19 seed families, 20 slots, nothing cut, and the
// reservation correctly reported that it could do nothing.
//
// This is the other half, ported from the legacy page. It runs after the rank
// check and MEASURES rather than infers: the best candidates the grid did not
// quote, put through the same live rank check the grid rows went through. The
// ranked-keywords report is a national dataset -- it can prove a client DOES
// rank for something and cannot prove they do not -- so it is only a sieve.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});

  let probes = [], owned = ['contractor huntingdon pa'];
  await p.route('**/api/config', r => json(r, {min_unranked_terms: 3,
                                               unranked_probe_max: 4}));
  await p.route('**/api/ranked_keywords', r => json(r, {owned}));
  await p.route('**/api/rankings', r => {
    const body = JSON.parse(r.request().postData() || '{}');
    probes.push((body.batch || []).map(x => x.kw));
    return json(r, {results: (body.batch || []).map(x => ({
      // Everything probed is a miss, which is the case this exists for.
      kw: x.kw, pos: 'Not Found'}))});
  });

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod');

  // The state after a rank check that came back 100% ranked.
  const setup = (extra) => p.evaluate(e => {
    const r = ROWS[0];
    r.kind = 'seo';
    r.data = Object.assign(r.data || {}, {
      brand: "Cisney & O'Donnell PA", site: 'cisneyremodeling.com',
      g_county: true, county: ['Huntingdon County, PA']});
    r.kw = Object.assign({
      all: [{kw: 'contractor huntingdon pa', vol: 10}],
      grid_cities: ['huntingdon pa'],
    }, e.kw);
    // Every quoted term ranks: no gap in the grid at all.
    r.result = {table: [{kw: 'contractor huntingdon pa', pos: 3}],
                pricing: {}, ranks: {}};
    r.unrankedTried = null; r.unrankedResult = null;
    r.unrankedAuto = e.auto === false ? true : false;
    r.ownedCache = null;
    draw();
    const hs = [...document.querySelectorAll('[data-unrgap="0"]')];
    return hs.length ? hs[0].textContent.replace(/\s+/g, ' ').trim() : '(no host)';
  }, extra);

  // ---- THE CUT LIST IS THE FIRST SOURCE
  let txt = await setup({auto: false, kw: {
    seed_ranking: {order: [['bathroom showroom', 40], ['kitchen showroom', 30]]}}});
  say('itSaysTheyRankForEverything',
      /rank for every one of the quoted terms/.test(txt), txt);
  say('andOffersToLookOutsideTheGrid', /Find 3 outside the grid/.test(txt), txt);
  say('fromTheTermsTheGridCut', /terms the grid cut/.test(txt), txt);

  // ---- AND THE MARKET POOL WHEN NOTHING WAS CUT. This is Cisney: 19 seeds for
  // 20 slots, so seed_ranking carries `skipped` and no order at all.
  txt = await setup({auto: false, kw: {
    seed_ranking: {skipped: '19 seeds for 20 slots, so every seed is quoted and '
                          + 'nothing was cut to reserve from'},
    market_pool: [{keyword: 'basement finishing', volume: 90},
                  {keyword: 'deck builder', volume: 70}]}});
  say('nothingCutFallsBackToTheMarketPool',
      /market terms the grid did not quote/.test(txt), txt);
  say('andStillOffersTheProbe', /Find 3 outside the grid/.test(txt), txt);

  // ---- no candidates anywhere: it says so rather than offering a dead button
  txt = await setup({auto: false, kw: {seed_ranking: {skipped: 'x'}}});
  say('noCandidatesSaysSo', /No candidates left to check/.test(txt), txt);
  say('andOffersNoButton', !/Find 3 outside/.test(txt), txt);

  // ---- THE PROBE ITSELF, measured on the live rank check
  probes = [];
  await p.evaluate(() => {
    const r = ROWS[0];
    r.kw.seed_ranking = {order: [['bathroom showroom', 40], ['kitchen showroom', 30],
                                 ['deck builder', 20]]};
    r.unrankedTried = null; r.unrankedResult = null; r.unrankedAuto = true;
    draw();
  });
  await p.evaluate(() => findUnranked(ROWS[0], false));
  await p.waitForFunction(() => !UNRANKED_RUNNING && ROWS[0].unrankedResult,
                          null, {timeout: 20000});
  const res = await p.evaluate(() => ({
    found: (ROWS[0].unrankedResult.found || []).map(f => f.bare),
    sieved: ROWS[0].unrankedResult.sieved,
    text: (document.querySelector('[data-unrgap="0"]') || {textContent: '(absent)'})
      .textContent.replace(/\s+/g, ' ').trim(),
  }));
  say('theProbeFindsTheGaps', res.found.length >= 3, JSON.stringify(res.found));
  say('andTheSuffixIsOnTheProbedTerm',
      probes.flat().every(k => /huntingdon pa$/.test(k)), JSON.stringify(probes));
  say('andTheFindingIsShown',
      /terms they do not rank for/.test(res.text)
      && /bathroom showroom/.test(res.text), res.text);
  say('measuredOnTheLiveResultPage',
      /measured on the live result page/.test(res.text), res.text);

  // ---- THE SIEVE SKIPS WHAT THE DOMAIN ALREADY RANKS FOR NATIONALLY, and is
  // only a sieve: it can prove a client DOES rank, never that they do not.
  owned = ['bathroom showroom'];
  probes = [];
  await p.evaluate(() => {
    const r = ROWS[0];
    r.unrankedTried = null; r.unrankedResult = null; r.ownedCache = null;
    r.unrankedAuto = true;
    draw();
  });
  await p.evaluate(() => findUnranked(ROWS[0], false));
  await p.waitForFunction(() => !UNRANKED_RUNNING && ROWS[0].unrankedResult,
                          null, {timeout: 20000});
  const sv = await p.evaluate(() => ROWS[0].unrankedResult);
  say('theSieveSkipsAKnownRankedTerm', sv.sieved === 1, JSON.stringify(sv));
  say('andItIsNotProbed',
      !probes.flat().some(k => /bathroom showroom/.test(k)), JSON.stringify(probes));

  // ---- ONE SHOT PER QUOTE. A reprice must not buy a second round of calls.
  const before = probes.length;
  await p.evaluate(() => { draw(); draw(); });
  await new Promise(z => setTimeout(z, 500));
  say('aRedrawDoesNotReprobe', probes.length === before,
      `${before} -> ${probes.length}`);

  // ---- A GRID THAT ALREADY HAS GAPS NEEDS NO PROMPT
  txt = await p.evaluate(() => {
    const r = ROWS[0];
    r.result.table = [{kw: 'a', pos: 'Not Found'}, {kw: 'b', pos: 'Not Found'},
                      {kw: 'c', pos: 'Not Found'}, {kw: 'd', pos: 4}];
    r.unrankedResult = null;
    draw();
    return (document.querySelector('[data-unrgap="0"]') || {textContent: ''})
      .textContent.trim();
  });
  say('threeGapsAlreadyIsAStoryAndNoPrompt', txt === '', JSON.stringify(txt));

  // ---- AN ORM ROW HAS NO GRID TO HAVE GAPS IN
  const orm = await p.evaluate(() => {
    const r = ROWS[0];
    r.kind = 'orm';
    draw();
    const h = document.querySelector('[data-unrgap="0"]');
    return h ? h.textContent.trim() : '(absent)';
  });
  say('anOrmRowGetsNoPrompt', orm === '(absent)' || orm === '', JSON.stringify(orm));

  await b.close();
  console.log(bad ? `FAILED ${bad}` : 'all ok');
  process.exit(bad ? 1 : 0);
})();
