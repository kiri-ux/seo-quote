// A pasted list becomes chips, not one chip containing a sentence.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  const chips = sel => p.$$eval(`${sel} .chip`, n => n.map(x => x.firstChild.textContent.trim()));

  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  await p.waitForSelector('#fseo [data-chips="focus"] .chipin', {timeout:15000});

  const paste = async (sel, text) => {
    await p.click(`${sel} .chipin`);
    await p.evaluate(({sel, text}) => {
      const inp = document.querySelector(sel + ' .chipin');
      const dt = new DataTransfer();
      dt.setData('text', text);
      inp.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
    }, {sel, text});
    await p.waitForTimeout(120);
  };

  const focus = '#fseo [data-chips="focus"]';
  await paste(focus, 'Electrical Services, Kohler Generator Installation, Generator '
    + 'Installation, Generator Services, Kohler Generator Services, Lighting, '
    + 'Electrical Panels, Electrical Car Charger Installation.');
  let c = await chips(focus);
  say('paste.splits', c.length === 8, `${c.length}: ${c.join('|')}`);
  say('paste.firstClean', c[0] === 'Electrical Services', c[0]);
  say('paste.trailingDotStripped', c[7] === 'Electrical Car Charger Installation', c[7]);
  say('paste.noBlob', !c.some(x => x.includes(',')), c.join('|'));
  say('paste.inputCleared', (await p.inputValue(`${focus} .chipin`)) === '');

  // Newlines and semicolons are list separators too, and duplicates collapse.
  await paste(focus, 'Lighting\nSurge Protection; Panel Upgrade');
  c = await chips(focus);
  say('paste.newlines', c.includes('Surge Protection') && c.includes('Panel Upgrade'), c.join('|'));
  say('paste.dedupes', c.filter(x => x === 'Lighting').length === 1, c.join('|'));

  // City keeps its comma -- "Boca Raton, FL" is one place.
  await p.evaluate(() => {
    const cb = document.querySelector('#fseo [data-k="g_city"]');
    if (cb && !cb.checked) { cb.checked = true; cb.dispatchEvent(new Event('change', {bubbles:true})); }
  });
  await p.waitForTimeout(120);
  // A synthetic paste event inserts no text, so the comma rule is exercised the
  // way a person types it: the field keeps the comma until Enter.
  const city = '#fseo [data-chips="city"]';
  await p.fill(`${city} .chipin`, 'Boca Raton, FL');
  await p.waitForTimeout(120);
  say('city.commaDoesNotSplitOnType',
      (await chips(city)).length === 0, (await chips(city)).join('|'));
  await p.keyboard.press('Enter');
  await p.waitForTimeout(120);
  const cc = await chips(city);
  say('city.keepsComma', cc.includes('Boca Raton, FL'), cc.join('|'));

  // Typing a comma still commits one term at a time.
  await p.fill(`${focus} .chipin`, 'Standby Generators,');
  await p.waitForTimeout(150);
  c = await chips(focus);
  say('typed.comma', c.includes('Standby Generators'), c.join('|'));

  // A pick box matches a pasted list against the list, and ignores the rest.
  const goals = '#fseo [data-chips="goals"]';
  const opts = await p.evaluate(() => (LISTS.goals || []).slice(0, 2));
  await paste(goals, opts.join(', ') + ', Not A Real Goal');
  const g = await chips(goals);
  say('pick.paste.matches', g.length === 2 && g[0] === opts[0] && g[1] === opts[1], g.join('|'));
  say('pick.paste.dropsUnknown', !g.includes('Not A Real Goal'), g.join('|'));

  // The rail + offers the two products.
  await p.goto('http://127.0.0.1:5203/adtini', {waitUntil:'networkidle'});
  say('rail.menuClosed', await p.$eval('#railMenu', el => el.hidden));
  await p.click('#railNew');
  await p.waitForTimeout(150);
  say('rail.menuOpens', await p.$eval('#railMenu', el => !el.hidden));
  const items = await p.$$eval('#railMenu a', n => n.map(a => a.textContent.trim()));
  say('rail.twoItems', items.length === 2, items.join('|'));
  say('rail.labels', items[0] === 'SEO+' && items[1] === 'ORM', items.join('|'));
  const hrefs = await p.$$eval('#railMenu a', n => n.map(a => a.getAttribute('href')));
  say('rail.hrefs', /product=seo$/.test(hrefs[0]) && /product=orm$/.test(hrefs[1]), hrefs.join('|'));
  const btn = await p.$$eval('#newMenu a', n => n.map(a => a.textContent.trim()));
  say('button.sameLabels', btn[0] === 'SEO+' && btn[1] === 'ORM', btn.join('|'));

  await b.close();
  console.log(bad ? `failed=${bad}` : 'ok all');
  process.exit(bad ? 1 : 0);
})();
