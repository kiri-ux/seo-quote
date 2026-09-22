// ROOM TO GROW, AND WHETHER THE RESERVATION ACTUALLY DID ANYTHING.
//
// Ranking the grid purely by measured demand hands every slot to the terms a
// client with existing SEO already owns -- those are the ones with volume
// attached -- so the proposal argues for a campaign to win what is already
// won. A few slots are reserved for the highest-demand terms the client is NOT
// ranking for. The server has run this on every adtini build since it shipped
// and the page showed none of it, which is the case it was built for: a client
// ranking for 100% of the quoted terms, with nothing on the proposal they
// don't already have.
//
// A SILENT NO-OP IS THE FAILURE MODE. The reservation has shipped twice
// looking like it worked, because every outcome except a swap was silent. Each
// outcome is checked here for that reason.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod');

  const show = sr => p.evaluate(s => {
    drawHeadroom({seed_ranking: s});
    const el = document.getElementById('kbHeadroom');
    return {hidden: el.hidden, text: el.textContent.replace(/\s+/g, ' ').trim()};
  }, sr);

  const SEEN = {want: 4, fresh: 0, own: 27, pool: 9,
                source: '27 ranked keywords read for skibarn.com'};

  // ---- WHAT IT DID, AND NOTHING ELSE.
  //
  // Held slots are the only outcome that changes the quote. Every other one --
  // the reserve switched off, the seeds all fitting the grid, the
  // ranked-keywords report disagreeing with the live rank check -- was a line
  // explaining why there was no line, and each is a fact about the machinery
  // rather than about the client. They live in the code now.
  let r = await show({headroom: [['ski tuning', 320], ['snowboard rental', 210]],
                      headroom_displaced: [['ski shop', 2420]],
                      headroom_basis: '27 ranked keywords read for skibarn.com',
                      headroom_seen: SEEN});
  say('heldSlotsAreNamed', /2 slots held for terms they don't rank for/.test(r.text),
      r.text);
  say('withTheirVolumes', /ski tuning \(320\/mo\)/.test(r.text), r.text);
  say('andWhatTheyDisplaced', /in place of ski shop/.test(r.text), r.text);
  say('andNoBasisNarration', !/ranked keywords read for/.test(r.text), r.text);
  say('andNoSlotArithmetic', !/wanted 4/.test(r.text), r.text);

  // Every outcome that held nothing renders nothing at all.
  for (const [label, sr] of [
    ['past the reservation', {headroom_met: 3, headroom_seen: SEEN}],
    ['the reserve is off', {order: [['a', 10, 10]], headroom_off: 'grid_headroom_slots is 0'}],
    ['nothing was cut', {skipped: '19 seeds for 20 slots'}],
    ['every candidate is ranked', {headroom_dry: 'x', headroom_seen: SEEN}],
    ['it ran and did nothing', {headroom_seen: SEEN}],
    ['the ranking failed', {failed: 'no volume data'}],
    ['an older build', {order: [['a', 10, 10]]}],
    ['nothing at all', {}],
  ]) {
    r = await show(sr);
    say(`nothingHeldDrawsNothing: ${label}`, r.hidden && r.text === '',
        JSON.stringify(r));
  }

  // ---- AND THE BUILD'S OWN ANSWER SURVIVES THE REFINE PASS.
  //
  // This is why the panel drew nothing on a real build. /api/keywords ranks the
  // seeds and reserves the slots; /api/refine rewords the finished buckets and
  // has no reason to produce any of that. The page replaced r.kw with the
  // refine response outright -- and refine's response DECLARES seed_ranking
  // while filling it from a stage that never computes it, so it always came
  // back {} and always won.
  const merged = await p.evaluate(() => {
    const build = {
      all: [{kw: 'a'}], city_selection: {kept: [['huntingdon, pa', 10]]},
      seed_ranking: {order: [['contractor', 10, 10]],
                     headroom: [['ski tuning', 320]],
                     headroom_seen: {want: 4, fresh: 0, own: 27, pool: 9,
                                     source: 'x'}},
    };
    const refine = {
      all: [{kw: 'a'}, {kw: 'b'}],          // refine's own answer, and it wins
      seed_ranking: {},                      // declared, never computed
      city_selection: {},                    // same story
      tier_moves: [{from: 'ultra', to: 'competitive'}],   // only refine has it
    };
    const out = mergeBuild(build, refine);
    return {
      terms: out.all.length,
      heldSlots: ((out.seed_ranking || {}).headroom || []).length,
      keptCities: ((out.city_selection || {}).kept || []).length,
      refineOnly: (out.tier_moves || []).length,
    };
  });
  say('refineWinsWhereItHasAnAnswer', merged.terms === 2, JSON.stringify(merged));
  say('theReserveSurvivesTheRefinePass', merged.heldSlots === 1, JSON.stringify(merged));
  say('andSoDoesTheMarketPick', merged.keptCities === 1, JSON.stringify(merged));
  say('andRefineOnlyKeysComeThrough', merged.refineOnly === 1, JSON.stringify(merged));

  // An empty answer is not a new answer, but a REAL one replaces the build's.
  const beats = await p.evaluate(() => mergeBuild(
    {seed_ranking: {headroom: [['old', 1]]}},
    {seed_ranking: {headroom: [['new', 2]]}}).seed_ranking.headroom[0][0]);
  say('aRealRefineAnswerStillReplacesTheBuilds', beats === 'new', beats);

  await b.close();
  console.log(bad ? `FAILED ${bad}` : 'all ok');
  process.exit(bad ? 1 : 0);
})();
