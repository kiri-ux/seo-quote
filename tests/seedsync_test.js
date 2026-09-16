// SEED TERMS ARE PRODUCT/VERTICAL FOCUS, WHICHEVER PANE THEY WERE TYPED ON.
// They were copied from the form once, when the modal opened, so a focus term
// added on the form after that never reached the seed box.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  const chips = sel => p.$$eval(sel + ' .chip', ns => ns.map(n => n.firstChild.textContent.trim()));
  const FOCUS = '#fseo [data-chips="focus"]', SEEDS = '#paneKw [data-chips="seeds"]';

  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout:15000});

  // Typed on the form AFTER the modal opened, then over to the builder.
  await p.fill(FOCUS + ' .chipin', 'hearing aids');
  await p.keyboard.press('Enter');
  await p.fill(FOCUS + ' .chipin', 'tonsillectomy');
  await p.keyboard.press('Enter');
  await p.click('#kwBuilder');
  await p.waitForTimeout(250);
  let seeds = await chips(SEEDS);
  say('formToSeeds', seeds.includes('hearing aids') && seeds.includes('tonsillectomy'), seeds.join('|'));
  say('modelFollows', await p.evaluate(() => (ROWS[ROW].data.focus || []).includes('hearing aids')));

  // Added on the builder, then back to the form.
  await p.fill(SEEDS + ' .chipin', 'sinus surgery');
  await p.keyboard.press('Enter');
  await p.click('#back');
  await p.waitForTimeout(250);
  let focus = await chips(FOCUS);
  say('seedsToForm', focus.includes('sinus surgery'), focus.join('|'));
  say('formKeepsTheRest', focus.includes('hearing aids') && focus.includes('tonsillectomy'), focus.join('|'));

  // Removed on the form, gone from the builder.
  await p.evaluate(sel => {
    const chip = [...document.querySelectorAll(sel + ' .chip')]
      .find(c => c.firstChild.textContent.trim() === 'hearing aids');
    chip.querySelector('b').click();
  }, FOCUS);
  await p.click('#kwBuilder');
  await p.waitForTimeout(250);
  seeds = await chips(SEEDS);
  say('formRemovalReachesSeeds', !seeds.includes('hearing aids'), seeds.join('|'));
  say('seedsKeepTheRest', seeds.includes('tonsillectomy') && seeds.includes('sinus surgery'), seeds.join('|'));

  // The proposed-seed mark survives a round trip: a dashed chip on the builder
  // is still dashed after form and back.
  await p.evaluate(() => {
    const r = ROWS[ROW];
    r.seedSrc = {'sinus surgery': 'their site'};
    SEED_SRC = Object.assign({}, r.seedSrc);
    chipbox(document.querySelector('#paneKw [data-chips="seeds"]'), r.data.focus.slice());
  });
  await p.click('#back'); await p.waitForTimeout(150);
  await p.click('#kwBuilder'); await p.waitForTimeout(250);
  const marked = await p.$$eval(SEEDS + ' .chip.sug', ns => ns.map(n => n.firstChild.textContent.trim()));
  say('markSurvivesRoundTrip', marked.join('|') === 'sinus surgery', marked.join('|'));

  // Same pane twice is not a switch: the builder's box is not redrawn under
  // a half-typed entry.
  await p.fill(SEEDS + ' .chipin', 'half typed');
  await p.evaluate(() => show('kw'));
  await p.waitForTimeout(100);
  say('samePaneLeavesInputAlone', (await p.inputValue(SEEDS + ' .chipin')) === 'half typed');

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
