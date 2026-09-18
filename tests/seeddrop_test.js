// A REMOVED SUGGESTION STAYS REMOVED, AND IT IS REVIEWED BEFORE THE BUILD.
// "allergy testing" was proposed on every press, and the only way to reject it
// was to let the whole list be built around it first. Expand is its own button:
// propose, prune, then build. ↻ Refresh focus terms is the one way back from a
// removal -- it takes the tool's own terms off and offers the removed ones
// again -- which is what Restore and Allow again used to be.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  let expandCalls = 0, buildCalls = 0, seedsSent = [], buildBody = {};
  await p.route('**/api/site_services', route => {
    expandCalls++;
    const seeds = (route.request().postDataJSON() || {}).seeds || [];
    seedsSent.push(seeds.slice());
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({services: [
        {term: 'allergy testing', volume: 30},
        {term: 'ear tube surgery', volume: 30}], floor: 20})});
  });
  await p.route('**/api/expand_services', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{"services":[],"floor":20}'}));
  await p.route('**/api/rank_seeds', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{"services":[]}'}));
  await p.route('**/api/suggest_regions', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{"regions":[]}'}));
  await p.route('**/api/keywords', route => {
    buildCalls++;
    buildBody = route.request().postDataJSON() || {};
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({ultra:[{kw:'a',vol:10}], competitive:[], long_tail:[],
                            all:[{kw:'a',vol:10}], total_volume:10})});
  });
  await p.route('**/api/refine', route =>
    route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({ultra:[{kw:'a',vol:10}], competitive:[], long_tail:[],
                            all:[{kw:'a',vol:10}], total_volume:10})}));
  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{}'}));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});
  await p.evaluate(() => {
    const r = ROWS[0];
    r.data.focus = ['Hearing Aids'];
    r.data.site = 'entoxford.com';
    r.seedSrc = {}; r.seedDrop = []; r.suggested = []; r.rankedSeeds = [];
    open(0, 'kw');
  });
  await p.waitForTimeout(400);
  // The line is cleared before each press, so waiting on it cannot be answered
  // by the previous one's.
  const expand = async () => {
    await p.evaluate(() => { $('saved').textContent = ''; });
    await p.click('#kbExpandRun');
    await p.waitForFunction(
      () => /proposed|added nothing|under the|full at/i.test($('saved').textContent),
      {timeout:20000});
  };
  const build = async () => {
    await p.evaluate(() => { $('saved').textContent = ''; });
    await p.click('#kbBuild');
    await p.waitForFunction(() => /^Built /.test($('saved').textContent), {timeout:20000});
  };

  // THE BUTTON PROPOSES AND STOPS. Its terms land in the seed box marked, and
  // nothing is built.
  await expand();
  say('expandedOnce', expandCalls === 1, expandCalls + ' expansion passes');
  say('nothingBuiltYet', buildCalls === 0, buildCalls + ' builds');
  say('noteSaysWhatItProposed',
      /2 terms proposed, marked ✦/.test(await p.textContent('#saved')),
      await p.textContent('#saved'));
  let chips = await p.$$eval('#paneKw [data-chips="seeds"] .chip',
    ns => ns.map(n => [n.firstChild.textContent.trim(), n.classList.contains('sug')]));
  say('bothProposedAreMarked',
      chips.filter(c => c[1]).map(c => c[0]).sort().join('|')
        === 'allergy testing|ear tube surgery', JSON.stringify(chips));

  // X OUT THE WEAK ONE.
  await p.evaluate(() => [...document.querySelectorAll(
    '#paneKw [data-chips="seeds"] .chip')].find(
      c => c.firstChild.textContent.trim() === 'allergy testing').querySelector('b').click());
  await p.waitForTimeout(200);
  say('recordedAsRemoved',
      (await p.evaluate(() => ROWS[0].seedDrop)).join('|') === 'allergy testing',
      JSON.stringify(await p.evaluate(() => ROWS[0].seedDrop)));
  // STATES THE FACT AND STOPS. The legend carries the count; the way back is
  // the Refresh toggle above it, not two link buttons inside a sentence.
  const legend = await p.textContent('#paneKw .seedhint');
  say('legendSaysTheCount', /1 removed\./i.test(legend), legend);
  say('legendOffersNoRestore', !/Restore them/i.test(legend), legend);
  say('legendOffersNoAllowAgain', !/Allow again/i.test(legend), legend);

  // THEN BUILD. It does not ask the expansion at all, and it is told what was
  // removed -- its own sources put "apartments for rent" back in the grid after
  // it had been taken off the seed box.
  const before = expandCalls;
  await build();
  say('builtThisTime', buildCalls === 1, buildCalls + ' builds');
  say('buildIsToldWhatWasRemoved',
      (buildBody.negatives || []).includes('allergy testing'),
      JSON.stringify(buildBody.negatives));
  say('buildDidNotExpand', expandCalls === before,
      (expandCalls - before) + ' extra expansion passes');
  chips = await p.$$eval('#paneKw [data-chips="seeds"] .chip',
    ns => ns.map(n => n.firstChild.textContent.trim()));
  say('weakOneStayedOut', !chips.includes('allergy testing'), JSON.stringify(chips));
  say('goodOneKept', chips.includes('ear tube surgery'), JSON.stringify(chips));

  // PRESS IT AGAIN -- never brings the removed term back.
  seedsSent = [];
  await expand();
  say('secondPressAsksAgain', expandCalls > before, expandCalls + ' total');
  const after = await p.evaluate(() => ROWS[0].data.focus.map(x => x.toLowerCase()));
  say('removedTermNeverReturns', !after.includes('allergy testing'), JSON.stringify(after));

  // A REWORDING IS THE SAME REJECTION. Removing "allergy testing" brought back
  // "allergy skin testing" on the next press.
  await p.evaluate(() => {
    ROWS[0].seedDrop = ['allergy testing', 'sinus surgery'];
    ROWS[0].data.focus = ['Hearing Aids'];
    ROWS[0].suggested = [];
    return null;
  });
  await p.unroute('**/api/site_services');
  await p.route('**/api/site_services', route =>
    route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({services: [
        {term: 'allergy skin testing', volume: 30},
        {term: 'minimally-invasive sinus surgery', volume: 20},
        {term: 'allergy testing', volume: 30},
        {term: 'tonsillectomy', volume: 40}], floor: 20})}));
  await p.evaluate(() => { open(0, 'kw'); });
  await p.waitForTimeout(300);
  await expand();
  const seeds = await p.evaluate(() => ROWS[0].data.focus.map(x => x.toLowerCase()));
  say('exactDropStaysOut', !seeds.includes('allergy testing'), JSON.stringify(seeds));
  say('rewordingStaysOut', !seeds.includes('allergy skin testing'),
      JSON.stringify(seeds));
  say('longerRewordingStaysOut',
      !seeds.includes('minimally-invasive sinus surgery'), JSON.stringify(seeds));
  say('unrelatedStillProposed', seeds.includes('tonsillectomy'),
      JSON.stringify(seeds));

  // AND REFRESH IS THE WAY BACK. It takes the tool's own terms off, clears the
  // block, and the removed ones are offered again on the same press.
  await p.click('#kbRefresh button[data-v="1"]');
  await expand();
  say('refreshClearedTheBlock',
      (await p.evaluate(() => (ROWS[0].seedDrop || []).length)) === 0);
  const back = await p.evaluate(() => ROWS[0].data.focus.map(x => x.toLowerCase()));
  say('removedTermIsOfferedAgain', back.includes('allergy testing'), JSON.stringify(back));
  say('typedOneNotDuplicated',
      back.filter(x => x === 'hearing aids').length === 1, JSON.stringify(back));

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
