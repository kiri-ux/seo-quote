// THE CLIENT'S SITE, ONE CLICK AWAY. It is on every SEO quote already; nothing
// linked it, so checking what they sell meant copying it out of the form.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"]', {timeout:15000});

  const set = url => p.evaluate(u => {
    ROWS.forEach(r => { if (r.data) r.data.site = ''; });
    if (ROWS[0] && ROWS[0].data) ROWS[0].data.site = u;
    draw();
  }, url);

  await set('https://www.drainify.com/');
  await p.waitForSelector('#siteLink', {timeout:5000});
  say('href', await p.getAttribute('#siteLink', 'href'), 'https://www.drainify.com/');
  say('label', (await p.textContent('#siteLink')).trim(), 'drainify.com');
  say('newTab', await p.getAttribute('#siteLink', 'target'), '_blank');
  say('safeRel', /noopener/.test(await p.getAttribute('#siteLink', 'rel') || ''));
  say('underTheHeading',
      await p.$eval('#siteLink', el =>
        el.previousElementSibling && el.previousElementSibling.tagName === 'H2'));

  // A PILL, CENTRED ON THE HEADING. It sat on the text baseline with a negative
  // top margin, so it read as a stray line rather than a control.
  const pill = await p.$eval('#siteLink', el => {
    const s = getComputedStyle(el);
    const h = el.previousElementSibling.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return {radius: parseFloat(s.borderRadius), display: s.display,
            border: parseFloat(s.borderTopWidth),
            bg: s.backgroundColor, padX: parseFloat(s.paddingLeft),
            offset: Math.abs((r.top + r.height / 2) - (h.top + h.height / 2))};
  });
  say('pill.rounded', pill.radius >= 12, pill.radius + 'px radius');
  say('pill.hasAFill', pill.bg !== 'rgba(0, 0, 0, 0)', pill.bg);
  say('pill.hasAnEdge', pill.border > 0, pill.border + 'px border');
  say('pill.padded', pill.padX >= 8, pill.padX + 'px side padding');
  // A flex item blockifies, so inline-flex computes as flex here. Either is the
  // row-with-a-gap the arrow and the label need.
  say('pill.laysOutAsARow', /flex/.test(pill.display), pill.display);
  say('pill.centredOnTheHeading', pill.offset <= 1.5, pill.offset + 'px off centre');

  // A bare domain still makes a working link.
  await set('drainify.com');
  await p.waitForTimeout(150);
  say('bare.href', await p.getAttribute('#siteLink', 'href'), 'https://drainify.com');
  say('bare.label', (await p.textContent('#siteLink')).trim(), 'drainify.com');

  // No site, no link -- and no empty stub left behind.
  await set('');
  await p.waitForTimeout(150);
  say('none', (await p.$$eval('#siteLink', n => n.length)) === 0);

  // Redrawing does not stack them up.
  await set('drainify.com');
  await p.evaluate(() => { draw(); draw(); });
  await p.waitForTimeout(150);
  say('single', (await p.$$eval('#siteLink', n => n.length)) === 1,
      String(await p.$$eval('#siteLink', n => n.length)));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
