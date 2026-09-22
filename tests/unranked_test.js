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
                                               unranked_probe_max: 24}));
  await p.route('**/api/ranked_keywords', r => json(r, {owned}));
  // DEEP, NOT ABSENT. Cisney sits somewhere in the top 100 for every remodeling
  // phrase in Huntingdon -- seven probes, seven positions, no gap reported.
  // `deep` is that shape; the default is the outright miss.
  let deep = false;
  await p.route('**/api/rankings', async r => {
    const raw = r.request().postData() || '{}';
    const body = JSON.parse(raw);
    await p.evaluate(b => { window.__lastRankBody = b; }, raw).catch(() => {});
    probes.push((body.batch || []).map(x => x.kw));
    return json(r, {results: (body.batch || []).map((x, i) => ({
      kw: x.kw, pos: deep ? 40 + i : 'Not Found'}))});
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
    ROW = 0;
    draw();
    // THE PROMPT LIVES WHERE THE SEEDS ARE. On the quote row it was a yellow
    // note over a price nobody can act on from there. (2026-09-22)
    renderUnrankedGap(r);
    const hs = [...document.querySelectorAll('[data-unrgap]')];
    return hs.length ? hs.map(x => x.textContent).join(' ').replace(/\s+/g, ' ').trim()
                     : '(no host)';
  }, extra);

  // ---- A CUT LIST OF PURE VARIANTS IS NOT A GAP LIST. Cisney, live: 60-odd
  // seeds, 28 quoted, everything cut a rewording of something quoted. The probe
  // spent all four calls on the highest-volume cut terms -- "bathroom
  // remodeler" against a quoted "bathroom remodel" -- and reported no gap
  // found. (2026-09-22, Kiri)
  await setup({auto: false, kw: {
    all: [{kw: 'bathroom remodel huntingdon pa', vol: 10},
          {kw: 'kitchen remodel huntingdon pa', vol: 10},
          {kw: 'contractor huntingdon pa', vol: 10}],
    seed_ranking: {order: [['bathroom remodeler', 90], ['bathroom remodeling', 80],
                           ['bathroom remodels', 70], ['kitchen remodeling', 60],
                           ['kitchen remodelers', 50], ['general contractors', 40],
                           ['deck builder', 20]]},
    market_pool: [{keyword: 'basement finishing', volume: 30}]}});
  const ord = await p.evaluate(() => unrankedCandidates(ROWS[0]).map(
    x => [x.bare, x.novel, x.src]));
  say('theVariantsAreNotProbedFirst',
      ord.slice(0, 2).every(x => x[1] === true), JSON.stringify(ord));
  say('andTheNewWordLeadsEvenOnLowerDemand',
      ord[0][0] === 'deck builder', JSON.stringify(ord));
  say('andTheCutListStillLeadsThePool',
      ord[1][0] === 'basement finishing' && ord[1][2] === 'pool',
      JSON.stringify(ord));
  say('andTheVariantsAreStillThereBehindThem',
      ord.length === 8 && ord.slice(2).every(x => x[1] === false),
      JSON.stringify(ord));
  // THE POOL RUNS ON BEHIND THE CUT LIST, not only in its place. A cut list of
  // variants used to end the search.
  say('andThePoolIsReachedThoughSomethingWasCut',
      ord.some(x => x[2] === 'pool'), JSON.stringify(ord));

  // ---- THE CUT LIST IS THE FIRST SOURCE
  let txt = await setup({auto: false, kw: {
    seed_ranking: {order: [['bathroom showroom', 40], ['kitchen showroom', 30]]}}});
  say('itSaysTheyRankForEverything',
      /rank for every one of the quoted terms/.test(txt), txt);
  say('andOffersToLookOutsideTheGrid', /Find 3 outside the grid/.test(txt), txt);
  // THE BUTTON IS THE OFFER. Naming the candidate source under it was a
  // sentence about the machinery; which well it drew from does not change what
  // the operator does next.
  say('andNoSourceNarration', !/terms the grid cut/.test(txt), txt);

  // ---- AND THE MARKET POOL WHEN NOTHING WAS CUT. This is Cisney: 19 seeds for
  // 20 slots, so seed_ranking carries `skipped` and no order at all.
  txt = await setup({auto: false, kw: {
    seed_ranking: {skipped: '19 seeds for 20 slots, so every seed is quoted and '
                          + 'nothing was cut to reserve from'},
    market_pool: [{keyword: 'basement finishing', volume: 90},
                  {keyword: 'deck builder', volume: 70}]}});
  // NOTHING CUT FALLS BACK TO THE MARKET POOL. This is Cisney: 19 seeds for 20
  // slots, so seed_ranking carries `skipped` and no order at all.
  say('nothingCutStillOffersTheProbe', /Find 3 outside the grid/.test(txt), txt);

  // ---- NO CANDIDATES, NO BOX. It used to print "They rank for every one of
  // the quoted terms. No term in the grid is a gap. No candidates left to
  // check." -- three sentences to say it could not help. The box earns its
  // place when there is a button in it or a finding under it.
  txt = await setup({auto: false, kw: {seed_ranking: {skipped: 'x'}}});
  say('noCandidatesDrawsNothing', txt === '', JSON.stringify(txt));

  // ---- THE PROBE ITSELF, measured on the live rank check
  probes = [];
  await p.evaluate(() => {
    const r = ROWS[0];
    r.kw.seed_ranking = {order: [['bathroom showroom', 40], ['kitchen showroom', 30],
                                 ['deck builder', 20]]};
    r.unrankedTried = null; r.unrankedResult = null; r.unrankedAuto = true;
    draw();
  });
  // PRESSED, NOT CALLED. The handler was bound to #prods and the prompt moved
  // into the Keyword Builder, so the button rendered, read as enabled and did
  // nothing at all when pressed. Calling findUnranked directly, which is what
  // this test did, could never have caught that. (2026-09-22, Kiri)
  const pressed = await p.evaluate(() => {
    const btn = document.querySelector('[data-unrfind]');
    if (!btn) return '(no button)';
    btn.click();
    return 'clicked';
  });
  say('theButtonIsThere', pressed === 'clicked', pressed);
  // A PRESS THAT DOES NOTHING MUST NAME ITSELF. With no handler bound this
  // waited out the full timeout and died in the runner, which reads as a slow
  // test rather than a dead button.
  let ran = true;
  try {
    await p.waitForFunction(() => !UNRANKED_RUNNING && ROWS[0].unrankedResult,
                            null, {timeout: 20000});
  } catch (e) { ran = false; }
  say('andPressingItRunsTheProbe', ran && probes.length > 0,
      ran ? JSON.stringify(probes) : 'the press did nothing');
  if (!ran) { console.log('FAILED', bad); await b.close(); process.exit(1); }
  const res = await p.evaluate(() => ({
    found: (ROWS[0].unrankedResult.found || []).map(f => f.bare),
    sieved: ROWS[0].unrankedResult.sieved,
    text: [...document.querySelectorAll('[data-unrgap]')]
      .map(x => x.textContent).join(' ').replace(/\s+/g, ' ').trim(),
  }));
  say('theProbeFindsTheGaps', res.found.length >= 3, JSON.stringify(res.found));
  say('andTheSuffixIsOnTheProbedTerm',
      probes.flat().every(k => /huntingdon pa$/.test(k)), JSON.stringify(probes));
  say('andTheFindingIsShown',
      /terms off page one/.test(res.text)
      && /bathroom showroom/.test(res.text), res.text);
  // TEN RESULTS DEEP, SO EVERY FIND IS SIMPLY OFF PAGE ONE. There is no deep
  // position left to print and the header already makes the claim.
  const sent = JSON.parse(await p.evaluate(() => window.__lastRankBody || '{}'));
  say('andTheProbeAsksAPageOneQuestion', sent.top_n === 10, JSON.stringify(sent.top_n));
  say('andTheFindingDoesNotNarrateItself',
      !/measured on the live result page/.test(res.text)
      && !/skipped, already ranked/.test(res.text), res.text);

  // ---- A FOUND GAP IS A PRESS AWAY FROM THE LIST. Printing the terms and
  // making her retype them into the seed box is not a finding, it is homework.
  const add = await p.evaluate(() => {
    const r = ROWS[0];
    // Snapshot, because accepting a term really does change the list now and
    // the sieve case below needs the term back outside the grid.
    window.__snap = {all: (r.kw.all || []).slice(),
                     focus: ((r.data || {}).focus || []).slice(),
                     ultra: (r.kw.ultra || []).slice(),
                     competitive: (r.kw.competitive || []).slice(),
                     long_tail: (r.kw.long_tail || []).slice(),
                     total: r.kw.total_volume};
    const before = kbSeeds().length;
    const gridBefore = (r.kw.all || []).map(x => x.kw);
    const b = [...document.querySelectorAll('[data-unrgap] [data-compadd]')][0];
    if (!b) return {err: '(no chip)'};
    const term = b.dataset.compadd;
    b.click();
    const all = (r.kw.all || []).map(x => x.kw);
    const row = (r.kw.all || []).find(x => x.kw.indexOf(term) === 0);
    return {term, before, after: kbSeeds().length,
            onSeeds: kbSeeds().map(x => String(x).toLowerCase())
              .indexOf(String(term).toLowerCase()) >= 0,
            gridBefore, all, vol: row ? row.vol : null,
            // NOTHING THE BUILD ALREADY MEASURED MAY BE DISTURBED. Accepting a
            // term used to mean rebuilding, which reseeds and remeasures -- a
            // list you liked comes back different, and pays for the calls.
            keptTheRest: gridBefore.every(k => all.indexOf(k) >= 0),
            tiers: ['ultra', 'competitive', 'long_tail']
              .filter(k => (r.kw[k] || []).some(x => x.kw.indexOf(term) === 0))};
  });
  say('aFoundGapIsAChip', !add.err && !!add.term, JSON.stringify(add));
  say('andPressingItSeedsTheList',
      add.after === add.before + 1 && add.onSeeds === true, JSON.stringify(add));
  // ---- AND LANDS ON THE LIST WITHOUT A REBUILD
  say('andTheTermIsOnTheListNow',
      add.all.length === add.gridBefore.length + 1, JSON.stringify(add));
  say('andItKeepsTheListYouHad', add.keptTheRest === true, JSON.stringify(add));
  say('andItCarriesTheMeasuredVolume', add.vol === 40, JSON.stringify(add));
  say('andItLandsInExactlyOneTier', add.tiers.length === 1, JSON.stringify(add));
  say('andTheTermIsSoldInTheGridsForm',
      /huntingdon pa$/.test(add.all[add.all.length - 1]), JSON.stringify(add.all));

  // ---- SIX AT A TIME, AND IT KEEPS GOING PAST EIGHT. Eight candidates found
  // ONE gap on Cisney: seven of the eight were on page one, which is exactly
  // the client this feature exists for. At page-one depth the call is a
  // fraction of what it was, so the budget is 24 in batches of six.
  // (2026-09-22, Kiri)
  probes = [];
  // setup() rewrites r.kw wholesale, and the sieve case below needs the
  // fixture it was given, so this one puts it back.
  await p.evaluate(() => { window.__kw = JSON.parse(JSON.stringify(ROWS[0].kw)); });
  await setup({auto: false, kw: {
    all: [{kw: 'contractor huntingdon pa', vol: 10}],
    seed_ranking: {order: Array.from({length: 20},
                                     (_, i) => ['service ' + i, 100 - i])}}});
  await p.evaluate(() => findUnranked(ROWS[0], false));
  await p.waitForFunction(() => !UNRANKED_RUNNING && ROWS[0].unrankedResult,
                          null, {timeout: 30000});
  say('itAsksSixAtATime', (probes[0] || []).length === 6,
      JSON.stringify(probes[0]));
  const probed = await p.evaluate(() => ROWS[0].unrankedResult.checked);
  say('andItGoesWellPastEight', probed > 8, String(probed));
  say('andNotPastTheBudget', probed <= 24, String(probed));
  await p.evaluate(() => {
    if (window.__kw) ROWS[0].kw = window.__kw;
    ROWS[0].unrankedTried = null; ROWS[0].unrankedResult = null;
  });

  // ---- A DEEP RANK IS A GAP. The probe borrowed zero_ranking_top_n, which is
  // 100 because it drives the PRICE, so a gap meant "absent from the top 100".
  // On a client ranking shallowly for everything that finds nothing, ever:
  // "No gap found in 7 terms checked" on Cisney, twice. (2026-09-22, Kiri)
  deep = true;
  probes = [];
  await p.evaluate(() => {
    const r = ROWS[0];
    const s = window.__snap;
    if (s) {
      r.kw.all = s.all; r.kw.ultra = s.ultra;
      r.kw.competitive = s.competitive; r.kw.long_tail = s.long_tail;
      r.kw.total_volume = s.total; r.data.focus = s.focus;
    }
    r.unrankedTried = null; r.unrankedResult = null; r.ownedCache = null;
    r.unrankedAuto = true;
    draw();
  });
  await p.evaluate(() => findUnranked(ROWS[0], false));
  await p.waitForFunction(() => !UNRANKED_RUNNING && ROWS[0].unrankedResult,
                          null, {timeout: 20000});
  const dp = await p.evaluate(() => ({
    found: (ROWS[0].unrankedResult.found || []).map(f => [f.bare, f.pos]),
    text: [...document.querySelectorAll('[data-unrgap]')]
      .map(x => x.textContent).join(' ').replace(/\s+/g, ' ').trim(),
  }));
  say('aDeepRankIsAGap', dp.found.length >= 3, JSON.stringify(dp.found));
  say('andThePositionIsCarried',
      dp.found.every(f => Number(f[1]) >= 40), JSON.stringify(dp.found));
  // WHERE THEY SIT IS THE WHOLE POINT. #63 and not-ranked are both gaps and
  // they are not the same conversation.
  say('andTheChipSaysWhereTheySit', /#4[0-9]/.test(dp.text), dp.text);
  say('andTheClaimIsPageOne', /off page one/.test(dp.text), dp.text);
  deep = false;

  // ---- A RANK CHECK THAT DID NOT RUN IS NOT A CLIENT WHO RANKS FOR
  // EVERYTHING. Cisney, live: "Retrying 6 that did not answer", fifteen minutes
  // on one press, and then "No gap found in 7 terms checked" -- a claim about
  // the client from a check that never happened. (2026-09-22, Kiri)
  let broke = true;
  await p.unroute('**/api/rankings');
  let calls = 0;
  await p.route('**/api/rankings', r => {
    const body = JSON.parse(r.request().postData() || '{}');
    calls++;
    probes.push((body.batch || []).map(x => x.kw));
    if (!broke) {
      return json(r, {results: (body.batch || []).map(x => ({
        kw: x.kw, pos: deep ? 40 : 'Not Found'}))});
    }
    return json(r, {error_reason: "40501 Invalid Field: 'location_name'",
                    results: (body.batch || []).map(x => ({
                      kw: x.kw, pos: '\u2014', error: true}))});
  });
  probes = []; calls = 0;
  await p.evaluate(() => {
    const r = ROWS[0];
    const s = window.__snap;
    if (s) {
      r.kw.all = s.all; r.kw.ultra = s.ultra;
      r.kw.competitive = s.competitive; r.kw.long_tail = s.long_tail;
      r.kw.total_volume = s.total; r.data.focus = s.focus;
    }
    r.unrankedTried = null; r.unrankedResult = null; r.ownedCache = null;
    r.unrankedAuto = true;
    draw();
  });
  await p.evaluate(() => findUnranked(ROWS[0], false));
  await p.waitForFunction(() => !UNRANKED_RUNNING && ROWS[0].unrankedResult,
                          null, {timeout: 20000});
  const br = await p.evaluate(() => ({
    res: ROWS[0].unrankedResult,
    text: [...document.querySelectorAll('[data-unrgap]')]
      .map(x => x.textContent).join(' ').replace(/\s+/g, ' ').trim(),
  }));
  say('aDeadCheckIsNotNoGapFound',
      !/No gap found/.test(br.text), br.text);
  say('andItSaysTheRankCheckFailed', /Rank check failed/.test(br.text), br.text);
  // THE ENDPOINT ALREADY KNOWS WHY AND THE PANEL WAS DISCARDING IT.
  say('andItSaysWhy', /location_name/.test(br.text), br.text);
  // ONE DEAD BATCH MEANS THE NEXT ONE DIES TOO. Eight probes then six retries
  // is how one press ran for fifteen minutes.
  say('andItStopsRatherThanGrinding', calls === 1, String(calls));
  broke = false;

  // ---- THE SIEVE SKIPS WHAT THE DOMAIN ALREADY RANKS FOR NATIONALLY, and is
  // only a sieve: it can prove a client DOES rank, never that they do not.
  owned = ['bathroom showroom'];
  probes = [];
  await p.evaluate(() => {
    const r = ROWS[0];
    const s = window.__snap;
    if (s) {
      r.kw.all = s.all; r.kw.ultra = s.ultra;
      r.kw.competitive = s.competitive; r.kw.long_tail = s.long_tail;
      r.kw.total_volume = s.total; r.data.focus = s.focus;
    }
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
    return [...document.querySelectorAll('[data-unrgap]')]
      .map(x => x.textContent).join('').trim();
  });
  say('threeGapsAlreadyIsAStoryAndNoPrompt', txt === '', JSON.stringify(txt));

  // ---- AN ORM ROW HAS NO GRID TO HAVE GAPS IN
  const orm = await p.evaluate(() => {
    const r = ROWS[0];
    r.kind = 'orm';
    draw();
    const hs = [...document.querySelectorAll('[data-unrgap]')];
    return hs.length ? hs.map(x => x.textContent).join('').trim() : '(absent)';
  });
  say('anOrmRowGetsNoPrompt', orm === '(absent)' || orm === '', JSON.stringify(orm));

  await b.close();
  console.log(bad ? `FAILED ${bad}` : 'all ok');
  process.exit(bad ? 1 : 0);
})();
