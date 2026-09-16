// WHICH SEEDS THE CLIENT NAMED AND WHICH THE TOOL PROPOSED. The expansion terms
// are merged into the seed list, and the mark that told them apart lived only in
// memory -- so a reopened quote showed one undifferentiated run of chips.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.route('**/api/serp_**', route =>
    route.fulfill({status:200, contentType:'application/json', body:'{}'}));
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});

  // A quote whose seeds are part typed, part proposed.
  await p.evaluate(() => {
    const r = ROWS[0];
    r.data.focus = ['Hearing Aids', 'ear tube surgery', 'Tonsillectomy',
                    'nasal polyp removal'];
    r.seedSrc = {'ear tube surgery': 'their site',
                 'nasal polyp removal': 'the industry'};
    r.suggested = ['ear tube surgery', 'nasal polyp removal'];
    open(0, 'kw');
  });
  await p.waitForTimeout(400);

  const chips = await p.$$eval('#paneKw [data-chips="seeds"] .chip',
    ns => ns.map(n => ({t: n.firstChild.textContent.trim(),
                        sug: n.classList.contains('sug'),
                        tip: n.getAttribute('title') || ''})));

  say('allFourShown', chips.length === 4, chips.length + ' chips');
  say('proposedAreMarked',
      chips.filter(c => c.sug).map(c => c.t).sort().join('|'),
      'ear tube surgery|nasal polyp removal');
  say('proposedAreMarkedOk',
      chips.filter(c => c.sug).map(c => c.t).sort().join('|')
        === 'ear tube surgery|nasal polyp removal',
      JSON.stringify(chips.map(c => [c.t, c.sug])));
  say('typedAreNotMarked',
      chips.filter(c => !c.sug).map(c => c.t).sort().join('|')
        === 'Hearing Aids|Tonsillectomy',
      JSON.stringify(chips.filter(c => !c.sug).map(c => c.t)));
  say('typedComeFirst',
      !chips[0].sug && !chips[1].sug && chips[2].sug && chips[3].sug,
      JSON.stringify(chips.map(c => c.sug)));
  say('sourceOnTheChip', /their site/.test(
      (chips.find(c => c.t === 'ear tube surgery') || {}).tip || ''),
      (chips.find(c => c.t === 'ear tube surgery') || {}).tip);

  const hint = (await p.textContent('#paneKw .seedhint') || '').trim();
  say('legendCounts', /2 from Product\/Vertical Focus/.test(hint)
      && /2 added by expansion/.test(hint), hint);

  // A quote the tool never expanded says nothing at all.
  await p.evaluate(() => {
    const r = ROWS[0];
    r.data.focus = ['Hearing Aids', 'Tonsillectomy'];
    r.seedSrc = {};
    open(0, 'kw');
  });
  await p.waitForTimeout(300);
  say('silentWhenNothingAdded',
      (await p.textContent('#paneKw .seedhint') || '').trim() === '',
      await p.textContent('#paneKw .seedhint'));
  say('noneMarked',
      (await p.$$eval('#paneKw [data-chips="seeds"] .chip.sug', n => n.length)) === 0);

  // AND IT SURVIVES A SAVE. The provenance rides in the saved payload.
  const pay = await p.evaluate(() => {
    const r = ROWS[0];
    r.seedSrc = {'ear tube surgery': 'their site'};
    r.suggested = ['ear tube surgery'];
    r.rankedSeeds = ['ear tube surgery'];
    return savePayload(r).adtini;
  });
  say('seedSrcSaved', (pay.seedSrc || {})['ear tube surgery'], 'their site');
  say('seedSrcSavedOk', (pay.seedSrc || {})['ear tube surgery'] === 'their site',
      JSON.stringify(pay.seedSrc));
  say('suggestedSaved', (pay.suggested || []).length === 1, JSON.stringify(pay.suggested));
  say('rankedSaved', (pay.rankedSeeds || []).length === 1, JSON.stringify(pay.rankedSeeds));

  // And a reopened row reads it back.
  const back = await p.evaluate(pay => {
    const r = ROWS[0];
    const a = adopt({payload: {adtini: pay}});
    return {src: a.seedSrc, sug: a.suggested};
  }, pay);
  say('adoptCarriesIt', (back.src || {})['ear tube surgery'] === 'their site',
      JSON.stringify(back.src));

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
