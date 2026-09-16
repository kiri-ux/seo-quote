// THE FLYOUT IS NOT A RAIL ICON. nav.rail a forces a 38px square and pale blue
// text, and the menu's links sit inside nav.rail -- so they rendered as greyed
// icon boxes with the labels crushed against them.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  for (const url of ['http://127.0.0.1:5203/adtini',
                     'http://127.0.0.1:5203/adtini/forecast']) {
    const tag = url.endsWith('/adtini') ? 'quotes' : 'forecast';
    await p.goto(url, {waitUntil:'networkidle'});
    await p.waitForSelector('#railNew', {timeout:15000});
    await p.click('#railNew');
    await p.waitForSelector('#railMenu:not([hidden])', {timeout:5000});

    const items = await p.$$eval('#railMenu a', n => n.map(a => {
      const cs = getComputedStyle(a);
      const r = a.getBoundingClientRect();
      const svg = a.querySelector('svg');
      const sr = svg ? svg.getBoundingClientRect() : {width: 0, height: 0};
      return {text: a.textContent.trim(), w: Math.round(r.width),
              h: Math.round(r.height), color: cs.color,
              svgW: Math.round(sr.width), justify: cs.justifyContent};
    }));

    say(tag + '.twoItems', items.length === 2, JSON.stringify(items.map(i => i.text)));
    // Not squeezed into the rail's 38px icon box.
    say(tag + '.notIconSized', items.every(i => i.w > 120),
        JSON.stringify(items.map(i => i.w)));
    say(tag + '.labelsLeftAligned', items.every(i => i.justify === 'flex-start'),
        JSON.stringify(items.map(i => i.justify)));
    // Dark text on a light panel, not the rail's pale blue.
    const pale = c => {
      const m = (c || '').match(/\d+/g) || [];
      return m.length >= 3 && +m[0] > 180 && +m[1] > 180 && +m[2] > 180;
    };
    say(tag + '.textIsReadable', items.every(i => !pale(i.color)),
        JSON.stringify(items.map(i => i.color)));
    say(tag + '.iconsSized', items.every(i => i.svgW >= 14 && i.svgW <= 24),
        JSON.stringify(items.map(i => i.svgW)));

    // The panel sits beside the rail, not under the page heading.
    const box = await p.$eval('#railMenu', el => {
      const r = el.getBoundingClientRect();
      return {left: Math.round(r.left), width: Math.round(r.width)};
    });
    say(tag + '.besideTheRail', box.left >= 54, 'panel left is ' + box.left);
    say(tag + '.notOversized', box.width <= 260, 'panel width is ' + box.width);
  }

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
