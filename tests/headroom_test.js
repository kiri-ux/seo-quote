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

  // ---- slots actually held: the terms, their volume, and what they displaced
  let r = await show({headroom: [['ski tuning', 320], ['snowboard rental', 210]],
                      headroom_displaced: [['ski shop', 2420]],
                      headroom_basis: '27 ranked keywords read for skibarn.com',
                      headroom_seen: SEEN});
  say('heldSlotsAreNamed', /2 slots held for terms they don't rank for yet/.test(r.text), r.text);
  say('withTheirVolumes', /ski tuning \(320\/mo\)/.test(r.text), r.text);
  say('andWhatTheyDisplaced', /in place of ski shop/.test(r.text), r.text);
  say('andWhereTheRankingsCameFrom', /27 ranked keywords read for skibarn\.com/.test(r.text), r.text);

  // ---- THE CASE SHE ASKED FOR: they already rank for everything quoted, and
  // the reservation says so instead of staying quiet.
  r = await show({headroom_met: 3, headroom_seen: Object.assign({}, SEEN, {fresh: 3})});
  say('pastTheReservationIsReported',
      /3 of the quoted terms are ones they don't rank for/.test(r.text), r.text);
  say('andSaysNothingWasSwapped', /nothing swapped/.test(r.text), r.text);

  // ---- nothing known about their positions: this one needs a human
  r = await show({headroom_skipped: 'could not be read (403)'});
  say('noRankingsIsAWarning', /No slots held for unranked terms/.test(r.text), r.text);
  say('andNamesWhy', /could not be read \(403\)/.test(r.text), r.text);

  // ---- every candidate below the cut is also already ranked
  r = await show({headroom_dry: 'every candidate the ranking cut is also a term they already rank for',
                  headroom_seen: SEEN});
  say('dryIsReported', /every candidate the ranking cut/.test(r.text), r.text);

  // ---- it ran and changed nothing. THE SILENT CASE.
  r = await show({headroom_seen: SEEN});
  say('theSilentCaseIsNoLongerSilent',
      /ran and changed nothing/.test(r.text), r.text);
  say('andTheCountsAreThere',
      /wanted 4, 0 already in the grid of 27 known ranked terms, 9 candidates below the cut/.test(r.text),
      r.text);

  // ---- THE RESERVATION DID NOT RUN. Switched off in config, or no service
  // slots to reserve from. Without this the panel drew nothing, which is
  // indistinguishable from the panel not working -- the same silence the other
  // branches exist to end, one level up.
  r = await show({order: [['a', 10, 10]], headroom_off: 'grid_headroom_slots is 0'});
  say('theReserveBeingOffIsReported',
      /No slots held for unranked terms/.test(r.text)
      && /grid_headroom_slots is 0/.test(r.text), r.text);

  // ---- an older saved quote: the ranking ran, no headroom key exists at all
  r = await show({order: [['a', 10, 10]], order_basis: 'x'});
  say('anOlderBuildSaysSoRatherThanNothing',
      /No unranked-term reservation on this build/.test(r.text), r.text);
  say('andSaysWhatToDo', /re-run the build/.test(r.text), r.text);

  // ---- nothing to say at all: no ranking ran either
  r = await show({});
  say('nothingToSayHidesTheLine', r.hidden && r.text === '', JSON.stringify(r));

  // ---- THE RANK CHECK OUTRANKS THE RANKED-KEYWORDS REPORT. On Ski Barn this
  // read "20 of the quoted terms are ones they don't rank for" directly above
  // "19/19 found in top 100" -- two numbers about the same twenty terms,
  // contradicting each other, because the reservation asks ranked_keywords at
  // build time and the rank check asks the live result page.
  const clash = await p.evaluate(() => {
    ROWS[ROW = 0].result = {table: [
      {kw: 'a', pos: 3}, {kw: 'b', pos: 7}, {kw: 'c', pos: 'Not Found'}]};
    drawHeadroom({seed_ranking: {headroom_met: 20,
                  headroom_seen: {want: 4, fresh: 20, own: 27, pool: 9, source: 'x'}}});
    return document.getElementById('kbHeadroom').textContent.replace(/\s+/g, ' ');
  });
  say('theRankCheckIsGivenTheLastWord',
      /the rank check found only 1 of 3 measured/.test(clash), clash);

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
