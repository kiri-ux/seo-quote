// INLINE-FLEX, NOT INLINE. Width and height do nothing on an inline box, so the
// info badge collapsed to a faint mark anywhere its label was not itself a flex
// container -- every label outside a <form>, including the builder's toggles.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast?new=1&product=seo',
               {waitUntil:'networkidle'});
  await p.waitForSelector('#fseo [data-k="brand"]', {timeout:15000});

  const badges = async sel => p.$$eval(sel, n => n.map(x => {
    const r = x.getBoundingClientRect();
    const cs = getComputedStyle(x);
    return {w: Math.round(r.width), h: Math.round(r.height),
            display: cs.display, radius: cs.borderRadius,
            tip: (x.getAttribute('data-tip') || '').length};
  }));

  // On the form, where the label IS a flex container.
  let bs = await badges('#fseo .i');
  say('form.some', bs.length > 0, String(bs.length));
  say('form.round', bs.every(x => x.w === 15 && x.h === 15),
      JSON.stringify(bs.slice(0, 3)));

  // In the keyword builder, where it is not.
  await p.click('#kwBuilder');
  await p.waitForTimeout(300);
  bs = await badges('#paneKw .i');
  say('kb.some', bs.length > 0, String(bs.length));
  say('kb.notCollapsed', bs.every(x => x.w === 15 && x.h === 15),
      JSON.stringify(bs));
  say('kb.isFlex', bs.every(x => x.display === 'inline-flex'),
      JSON.stringify(bs.map(x => x.display)));
  say('kb.hasATip', bs.every(x => x.tip > 10), JSON.stringify(bs.map(x => x.tip)));

  // And the hover actually paints a tooltip.
  const tipShown = await p.evaluate(() => {
    const el = document.querySelector('#paneKw .i');
    if (!el) return null;
    const before = getComputedStyle(el, '::after').content;
    return String(before || '').length > 2;
  });
  say('kb.tooltipContent', tipShown === true, String(tipShown));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
