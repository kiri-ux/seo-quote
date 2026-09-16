// A WAY OUT THAT IS NOT "APPLY". The builder, the brand scan and the config are
// side panes of the form, and the only button on them committed the work -- so
// looking at a list you did not want meant closing the whole modal.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout:15000});

  // Not on the form itself -- there is nothing to go back to.
  say('form.noBack', await p.$eval('#back', el => el.hidden));

  // On the keyword builder.
  await p.click('#kwBuilder');
  await p.waitForTimeout(250);
  say('kb.backShown', await p.$eval('#back', el => !el.hidden));
  say('kb.label', (await p.textContent('#back')).trim(), 'Back');
  say('kb.applyStillThere', (await p.textContent('#gen')).trim(), 'Apply to the quote');
  say('kb.noSaveButton', await p.$eval('#save', el => el.hidden));

  // It returns to the form and leaves the modal open.
  await p.fill('#paneKw [data-chips="seeds"] .chipin', 'sinus surgery');
  await p.keyboard.press('Enter');
  await p.click('#back');
  await p.waitForTimeout(250);
  say('back.onForm', await p.$eval('#paneForm', el => !el.hidden));
  say('back.kbHidden', await p.$eval('#paneKw', el => el.hidden));
  say('back.modalOpen', await p.$eval('#scrim', el => !el.hidden));
  say('back.hidesItself', await p.$eval('#back', el => el.hidden));
  say('back.generateRestored', (await p.textContent('#gen')).trim(), 'Generate Quote');

  // The seed survives the trip, because Back is not Cancel.
  await p.click('#kwBuilder');
  await p.waitForTimeout(250);
  const seeds = await p.$$eval('#paneKw [data-chips="seeds"] .chip',
                               n => n.map(x => x.firstChild.textContent.trim()));
  say('back.keepsTheSeed', seeds.includes('sinus surgery'), seeds.join('|'));

  // And on Config too.
  await p.click('#back');
  await p.waitForTimeout(200);
  await p.evaluate(() => show('cfg'));
  await p.waitForTimeout(200);
  say('cfg.backShown', await p.$eval('#back', el => !el.hidden));
  await p.click('#back');
  await p.waitForTimeout(200);
  say('cfg.returns', await p.$eval('#paneForm', el => !el.hidden));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
