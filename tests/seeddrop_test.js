// A REMOVED SUGGESTION STAYS REMOVED, AND IT IS REVIEWED BEFORE THE BUILD.
// "allergy testing" was proposed on every press, and the only way to reject it
// was to let the whole list be built around it first.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  let expandCalls = 0, buildCalls = 0, seedsSent = [];
  await p.route('**/api/site_services', route => {
    expandCalls++;
    const seeds = (route.request().postDataJSON() || {}).seeds || [];
    seedsSent.push(seeds.slice());
    return route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({services: [
        {term: 'allergy testing', volume: 10},
        {term: 'ear tube surgery', volume: 30}]})});
  });
  await p.route('**/api/expand_services', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{"services":[]}'}));
  await p.route('**/api/rank_seeds', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{"services":[]}'}));
  await p.route('**/api/suggest_regions', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{"regions":[]}'}));
  await p.route('**/api/keywords', route => {
    buildCalls++;
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
    r.data.expand = 1;
    r.seedSrc = {}; r.seedDrop = []; r.expandDone = [];
    open(0, 'kw');
  });
  await p.waitForTimeout(400);

  // FIRST PRESS PROPOSES AND STOPS.
  await p.click('#kbBuild');
  await p.waitForFunction(() => /proposed/.test($('saved').textContent), {timeout:15000});
  say('proposedBeforeBuilding', buildCalls === 0, buildCalls + ' builds on the first press');
  say('saysHowManyAndWhatToDo',
      /2 terms proposed, shown dashed\. Remove any, then press Build keyword list\./
        .test(await p.textContent('#saved')),
      await p.textContent('#saved'));
  let chips = await p.$$eval('#paneKw [data-chips="seeds"] .chip',
    ns => ns.map(n => [n.firstChild.textContent.trim(), n.classList.contains('sug')]));
  say('bothProposedAreDashed',
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
  say('legendSaysTheRule',
      /removed suggestions are not proposed again/i.test(
        await p.textContent('#paneKw .seedhint')),
      await p.textContent('#paneKw .seedhint'));

  // SECOND PRESS BUILDS, WITHOUT ASKING THE EXPANSION AGAIN.
  const before = expandCalls;
  await p.click('#kbBuild');
  await p.waitForFunction(() => /^Built /.test($('saved').textContent), {timeout:20000});
  say('builtThisTime', buildCalls === 1, buildCalls + ' builds');
  say('didNotReExpand', expandCalls === before,
      (expandCalls - before) + ' extra expansion passes');
  chips = await p.$$eval('#paneKw [data-chips="seeds"] .chip',
    ns => ns.map(n => n.firstChild.textContent.trim()));
  say('weakOneStayedOut', !chips.includes('allergy testing'), JSON.stringify(chips));
  say('goodOneKept', chips.includes('ear tube surgery'), JSON.stringify(chips));

  // AND A NEW TYPED SEED DOES ASK AGAIN -- but never for the removed term.
  await p.evaluate(() => {
    ROWS[0].data.focus = ROWS[0].data.focus.concat('Tonsillectomy');
    open(0, 'kw');
  });
  await p.waitForTimeout(300);
  seedsSent = [];
  await p.click('#kbBuild');
  await p.waitForFunction(() => /proposed|^Built /.test($('saved').textContent),
                          {timeout:20000});
  say('newSeedReExpands', expandCalls > before, expandCalls + ' total');
  const after = await p.evaluate(() => ROWS[0].data.focus.map(x => x.toLowerCase()));
  say('removedTermNeverReturns', !after.includes('allergy testing'), JSON.stringify(after));

  // A REWORDING IS THE SAME REJECTION. Removing "allergy testing" brought back
  // "allergy skin testing" on the next press.
  const echo = await p.evaluate(() => {
    ROWS[0].seedDrop = ['allergy testing', 'sinus surgery'];
    ROWS[0].data.focus = ['Hearing Aids'];
    ROWS[0].expandDone = [];
    return null;
  });
  await p.unroute('**/api/site_services');
  await p.route('**/api/site_services', route =>
    route.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({services: [
        {term: 'allergy skin testing', volume: 10},
        {term: 'minimally-invasive sinus surgery', volume: 20},
        {term: 'allergy testing', volume: 30},
        {term: 'tonsillectomy', volume: 40}]})}));
  await p.evaluate(() => { open(0, 'kw'); });
  await p.waitForTimeout(300);
  await p.click('#kbBuild');
  await p.waitForFunction(() => /proposed|^Built /.test($('saved').textContent),
                          {timeout:20000});
  const seeds = await p.evaluate(() => ROWS[0].data.focus.map(x => x.toLowerCase()));
  say('exactDropStaysOut', !seeds.includes('allergy testing'), JSON.stringify(seeds));
  say('rewordingStaysOut', !seeds.includes('allergy skin testing'),
      JSON.stringify(seeds));
  say('longerRewordingStaysOut',
      !seeds.includes('minimally-invasive sinus surgery'), JSON.stringify(seeds));
  say('unrelatedStillProposed', seeds.includes('tonsillectomy'),
      JSON.stringify(seeds));

  // AND THERE IS A WAY BACK.
  await p.evaluate(() => {
    const r = ROWS[0];
    r.seedDrop = ['allergy testing', 'ear tube surgery'];
    r.data.focus = ['Hearing Aids'];
    open(0, 'kw');
  });
  await p.waitForTimeout(300);
  say('restoreOffered', (await p.$$('#seedRestore')).length === 1);
  await p.click('#seedRestore');
  await p.waitForTimeout(300);
  const restored = await p.evaluate(() => ROWS[0].data.focus.map(x => x.toLowerCase()));
  say('bothCameBack',
      restored.includes('allergy testing') && restored.includes('ear tube surgery'),
      JSON.stringify(restored));
  say('dropListCleared',
      (await p.evaluate(() => ROWS[0].seedDrop)).length === 0);
  say('expansionAskedAgain',
      (await p.evaluate(() => ROWS[0].expandDone)).length === 0);
  say('restoreGoesAway', (await p.$$('#seedRestore')).length === 0);
  say('typedOneNotDuplicated',
      restored.filter(x => x === 'hearing aids').length === 1, JSON.stringify(restored));

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
