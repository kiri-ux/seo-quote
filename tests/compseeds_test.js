// WHAT THE COMPETITORS RANK FOR, when the client's own list cannot say.
//
// Every other seed source starts from the client: their site, their focus
// terms, their own rankings. That works while the client sells into the market
// being quoted, and it fails the same way on a client who ALREADY RANKS for
// every term they named. Cisney & O'Donnell: 19 seed families, all quoted, all
// ranked, the reservation with nothing cut to promote from and the gap finder
// with nothing to probe. The candidate well was dry because the well was the
// client's own vocabulary.
//
// THE OVERLAP IS THE SIGNAL, NOT THE VOLUME. A term five of nine competitors
// hold is the category's vocabulary; one a single competitor holds alone is
// that competitor's angle.
const {chromium} = require('/root/work/node_modules/playwright-core');
const BASE = 'http://127.0.0.1:5203';

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra = '') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };
  const json = (route, body) =>
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});

  let sent = null, reply = {
    keywords: [
      {term: 'basement finishing', volume: 90, competitors: 3,
       on: ['a.com', 'b.com', 'c.com'], position: 4},
      {term: 'deck builder', volume: 70, competitors: 1, on: ['a.com'], position: 8},
    ],
    domains_read: ['a.com', 'b.com'], domains_failed: ['c.com'],
    total: 12, shared: 1, already_seeded: 2, family_capped: [],
  };
  await p.route('**/api/competitor_seeds', r => {
    try { sent = JSON.parse(r.request().postData() || '{}'); } catch (e) {}
    return json(r, reply);
  });

  await p.goto(BASE + '/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForSelector('.prod');
  await p.click('[data-open="0"][data-view="form"]');
  await p.evaluate(() => {
    const r = ROWS[0];
    r.data = Object.assign(r.data || {}, {
      brand: "Cisney & O'Donnell PA", site: 'cisneyremodeling.com',
      focus: ['contractor', 'kitchen remodel'],
      g_county: true, county: ['Huntingdon County, PA']});
    load(formOf(r), r.data);
    kbLoad(r);
  });
  await p.click('#kwBuilder');

  const there = await p.evaluate(() => ({
    box: !!document.getElementById('kbCompIn'),
    btn: !!document.getElementById('kbCompRead'),
    aboveBuild: !!document.querySelector('.kbcomp ~ #kbBuild'),
  }));
  say('theReaderIsInTheBuilder', there.box && there.btn, JSON.stringify(there));
  say('andSitsAboveBuild', there.aboveBuild, JSON.stringify(there));

  await p.fill('#kbCompIn', 'a.com, b.com\nc.com');
  await p.click('#kbCompRead');
  await p.waitForFunction(() => /rivals|could not/.test(
    document.getElementById('kbCompOut').textContent), null, {timeout: 20000});

  say('theClientsOwnSeedsAreSentToDiffAgainst',
      JSON.stringify((sent || {}).seeds) === JSON.stringify(['contractor', 'kitchen remodel']),
      JSON.stringify((sent || {}).seeds));
  say('andEveryDomainTyped',
      JSON.stringify((sent || {}).competitors) === JSON.stringify(['a.com', 'b.com', 'c.com']),
      JSON.stringify((sent || {}).competitors));
  say('andTheClientsOwnSiteSoItIsNotOffered',
      (sent || {}).domain === 'cisneyremodeling.com', (sent || {}).domain);

  const out = await p.evaluate(() => ({
    text: document.getElementById('kbCompOut').textContent.replace(/\s+/g, ' ').trim(),
    chips: [...document.querySelectorAll('[data-compadd]')].map(x => x.dataset.compadd),
    firstLabel: (document.querySelector('[data-compadd]') || {}).textContent,
  }));
  say('bothTermsAreOffered',
      JSON.stringify(out.chips) === JSON.stringify(['basement finishing', 'deck builder']),
      JSON.stringify(out.chips));
  // THE OVERLAP LEADS: three rivals holding a term is the category's vocabulary.
  say('theRivalCountLeadsTheChip', /3 rivals/.test(out.firstLabel || ''), out.firstLabel);
  say('andTheVolumeIsThere', /90\/mo/.test(out.firstLabel || ''), out.firstLabel);
  say('itSaysHowManySitesWereRead', /from 2 competitors/.test(out.text), out.text);
  say('andHowManyCouldNot', /1 could not be read/.test(out.text), out.text);
  say('andWhatWasAlreadyOnTheList', /2 already on your list/.test(out.text), out.text);

  // ---- ACCEPTED BY HAND BECOMES THE PLANNER'S OWN SEED. Not marked as a
  // suggestion: the competitor-name filter cuts rivals' product names out of
  // TOOL-proposed terms and would cut this straight back out.
  await p.click('[data-compadd="basement finishing"]');
  const added = await p.evaluate(() => ({
    focus: ROWS[0].data.focus,
    marked: !!(SEED_SRC || {})['basement finishing'],
    chipDisabled: document.querySelector('[data-compadd="basement finishing"]').disabled,
    inBox: [...document.querySelectorAll('#paneKw [data-chips="seeds"] .chip')]
      .map(x => x.textContent.replace(/\s*×\s*$/, '').trim()),
  }));
  say('theTermBecomesASeed', added.focus.includes('basement finishing'),
      JSON.stringify(added.focus));
  say('andIsNotMarkedAsASuggestion', added.marked === false, String(added.marked));
  say('andShowsInTheSeedBox', added.inBox.includes('basement finishing'),
      JSON.stringify(added.inBox));
  say('andTheChipCannotBeAddedTwice', added.chipDisabled, String(added.chipDisabled));

  // ---- PULLED, NOT TYPED. The rank check has already read page one for every
  // term in the grid, so the competitors are in hand: nothing to look up and
  // nothing to pay for. /api/rankings has always answered with `rivals` and
  // this tab was dropping them.
  const pulled = await p.evaluate(() => {
    const r = ROWS[0];
    r.result = {
      // as addRivals accumulates them across batches
      rivals: {'yelp.com': 9, 'bigremodeler.com': 7, 'smallremodel.com': 4,
               'angi.com': 8, 'cisneyremodeling.com': 6, 'facebook.com': 5},
      agg: {domains: ['yelp.com', 'angi.com']},
    };
    document.getElementById('kbCompIn').value = '';
    pullCompetitors();
    return {box: document.getElementById('kbCompIn').value,
            note: document.getElementById('kbCompOut').textContent};
  });
  say('itPullsTheRealCompetitors',
      /bigremodeler\.com/.test(pulled.box) && /smallremodel\.com/.test(pulled.box),
      pulled.box);
  // Yelp ranks for everything and sells none of it, so its vocabulary is
  // Yelp's rather than a remodeler's.
  say('andLeavesTheAggregatorsOut',
      !/yelp\.com|angi\.com/.test(pulled.box), pulled.box);
  say('andTheClientsOwnSite', !/cisneyremodeling/.test(pulled.box), pulled.box);
  say('andTheSocialProfiles', !/facebook/.test(pulled.box), pulled.box);
  say('mostSeenFirst',
      pulled.box.indexOf('bigremodeler') < pulled.box.indexOf('smallremodel'),
      pulled.box);
  say('andItSaysHowOftenEachWasSeen', /bigremodeler\.com \(7\)/.test(pulled.note),
      pulled.note);

  // No rank check behind it is a different answer from no competitors.
  const noRank = await p.evaluate(() => {
    ROWS[0].result = {};
    document.getElementById('kbCompIn').value = '';
    pullCompetitors();
    return document.getElementById('kbCompOut').textContent;
  });
  say('noRankCheckSaysSo', /No rank check on this quote yet/.test(noRank), noRank);

  // ---- nothing typed, and nothing to say
  await p.fill('#kbCompIn', '  ');
  await p.click('#kbCompRead');
  say('noDomainsSaysSo',
      /at least one competitor website/i.test(
        await p.evaluate(() => document.getElementById('kbCompOut').textContent)), '');

  // ---- everything they rank for is already on the list
  reply = {keywords: [], domains_read: ['a.com'], domains_failed: [],
           total: 5, already_seeded: 5};
  await p.fill('#kbCompIn', 'a.com');
  await p.click('#kbCompRead');
  await p.waitForFunction(() => /already on your list|Nothing came back/.test(
    document.getElementById('kbCompOut').textContent), null, {timeout: 20000});
  say('allAlreadySeededSaysSo',
      /All 5 terms they rank for are already on your list/.test(
        await p.evaluate(() => document.getElementById('kbCompOut').textContent)), '');

  await b.close();
  console.log(bad ? `FAILED ${bad}` : 'all ok');
  process.exit(bad ? 1 : 0);
})();
