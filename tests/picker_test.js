// Industry / Strategy / Campaign Goals: a styled type-ahead, not an OS select,
// and it stays open across several picks.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  await p.waitForSelector('#fseo [data-chips="industry"] .chipin', {timeout:15000});

  // No native select survives anywhere on the form.
  say('no.native.select', await p.$$eval('.box select', n => n.length) === 0);

  const box = '#fseo [data-chips="industry"]';
  // Focus alone must NOT open it -- the panel would cover Strategy below.
  await p.click(`${box} .chipin`);
  await p.waitForTimeout(150);
  say('closed.on.focus', await p.$eval(`${box} .picks`, el => el.hidden));

  // The caret opens the whole list.
  await p.click(`${box} .pickcar`);
  await p.waitForSelector(`${box} .picks:not([hidden])`, {timeout:5000});
  say('caret.opens', true);

  const n0 = await p.$$eval(`${box} .pick`, n => n.length);
  say('has.options', n0 > 1, `got ${n0}`);

  // Type-ahead filters, and a starts-with match leads.
  await p.fill(`${box} .chipin`, 'dent');
  await p.waitForTimeout(150);
  const shown = await p.$$eval(`${box} .pick`, n => n.map(x => x.dataset.v));
  say('filters', shown.length > 0 && shown.length < n0, `${shown.length} of ${n0}`);
  say('filter.matches', shown.every(v => v.toLowerCase().includes('dent')), shown.slice(0,3).join('|'));
  say('startswith.first', /^dent/i.test(shown[0] || ''), shown[0]);
  say('marks.match', (await p.$$eval(`${box} .pick b`, n => n.length)) > 0);

  // Enter takes the highlighted option and the panel STAYS OPEN.
  await p.keyboard.press('Enter');
  await p.waitForTimeout(150);
  let chips = await p.$$eval(`${box} .chip`, n => n.map(x => x.firstChild.textContent.trim()));
  say('enter.adds', chips.length === 1, chips.join('|'));
  say('stays.open.after.enter',
      await p.$eval(`${box} .picks`, el => !el.hidden));
  say('input.cleared', (await p.inputValue(`${box} .chipin`)) === '');

  // Escape closes the list, which is how you leave a box you are done with.
  await p.keyboard.press('Escape');
  await p.waitForTimeout(120);
  say('escape.closes.first', await p.$eval(`${box} .picks`, el => el.hidden));

  // Clicking a second option adds it without closing -- multiselect.
  const goals = '#fseo [data-chips="goals"]';
  await p.click(`${goals} .chipin`);
  await p.click(`${goals} .pickcar`);
  await p.waitForSelector(`${goals} .picks:not([hidden])`);
  await p.click(`${goals} .pick >> nth=0`);
  await p.waitForTimeout(120);
  say('click.keeps.open', await p.$eval(`${goals} .picks`, el => !el.hidden));
  await p.click(`${goals} .pick >> nth=0`);
  await p.waitForTimeout(120);
  const g = await p.$$eval(`${goals} .chip`, n => n.map(x => x.firstChild.textContent.trim()));
  say('multiselect', g.length === 2, g.join('|'));
  say('no.duplicates', new Set(g.map(x=>x.toLowerCase())).size === g.length, g.join('|'));

  // A taken value leaves the list.
  const left = await p.$$eval(`${goals} .pick`, n => n.map(x => x.dataset.v.toLowerCase()));
  say('taken.removed', !g.some(v => left.includes(v.toLowerCase())), g.join('|'));

  // The modal is still open through all of it.
  say('modal.open', await p.$eval('#scrim', el => !el.hidden));

  // Free text cannot enter a pick box -- Industry must match RZ exactly.
  await p.fill(`${goals} .chipin`, 'zzz not a real goal');
  await p.keyboard.press('Enter');
  await p.waitForTimeout(120);
  const g2 = await p.$$eval(`${goals} .chip`, n => n.map(x => x.firstChild.textContent.trim()));
  say('no.freetext', g2.length === 2, g2.join('|'));

  // Escape closes without closing the modal.
  await p.keyboard.press('Escape');
  await p.waitForTimeout(120);
  say('escape.closes', await p.$eval(`${goals} .picks`, el => el.hidden));
  say('escape.keeps.modal', await p.$eval('#scrim', el => !el.hidden));

  // Seed box has no pick list, so free text still works there.
  await p.click('#kwBuilder');
  await p.waitForTimeout(300);
  const seeds = '#paneKw [data-chips="seeds"]';
  await p.fill(`${seeds} .chipin`, 'vein clinic');
  await p.keyboard.press('Enter');
  await p.waitForTimeout(120);
  const sd = await p.$$eval(`${seeds} .chip`, n => n.map(x => x.firstChild.textContent.trim()));
  say('seeds.freetext', sd.includes('vein clinic'), sd.join('|'));

  // The keyword builder has no "save without generating" -- there is no quote.
  say('kb.no.save', await p.$eval('#save', el => el.hidden));
  await p.click('#kwBuilder');
  await p.waitForTimeout(250);
  say('form.has.save', await p.$eval('#save', el => !el.hidden));

  await b.close();
  console.log(bad ? `failed=${bad}` : 'ok all');
  process.exit(bad ? 1 : 0);
})();
