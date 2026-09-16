// The keyword list is as tall as the capture, and scrolls. A 21-term list ran
// to 900px beside a 16:9 frame and the row was mostly white space.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForTimeout(400);

  const hist = '.prod[data-row="0"] [data-pane="history"]';
  // Give the list far more rows than the capture is tall.
  await p.evaluate(() => {
    const r = ROWS[0];
    const seed = ((r.kw || {}).all || [])[0] || {kw: 'x', vol: 10};
    r.kw.all = Array.from({length: 40}, (_, i) =>
      Object.assign({}, seed, {kw: 'term number ' + i}));
    r.result.shot = 'data:image/gif;base64,R0lGODlhEAAQAPAAAP///wAAACH5BAAAAAAALAAAAAAQABAAAAIOhI+py+0Po5y02ouzPgUAOw==';
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.waitForTimeout(400);

  const box = async sel => p.$eval(sel, el => {
    const r = el.getBoundingClientRect();
    return {h: Math.round(r.height), w: Math.round(r.width)};
  });
  const kw = await box(hist + ' .pvkw');
  const serp = await box(hist + ' .pvserp');
  // Within a row of padding: the list follows the capture rather than setting
  // the height itself, which is the thing that was wrong.
  say('heightsMatch', Math.abs(kw.h - serp.h) <= 16, `kw ${kw.h} vs serp ${serp.h}`);
  say('listDidNotStretch', kw.h < 700, 'kw panel is ' + kw.h + 'px for 40 rows');

  // And the list scrolls rather than being cut off.
  const sc = await p.$eval(hist + ' .pvkw .pvscroll', el => ({
    scroll: el.scrollHeight, client: el.clientHeight,
    overflow: getComputedStyle(el).overflowY}));
  say('scrolls', sc.overflow === 'auto' || sc.overflow === 'scroll', sc.overflow);
  say('hasMoreToScroll', sc.scroll > sc.client, `${sc.scroll} vs ${sc.client}`);

  // The capture keeps the landscape frame.
  const frame = await p.$eval(hist + ' .pvserp .shotwrap', el => {
    const r = el.getBoundingClientRect();
    return {ratio: r.width / r.height};
  }).catch(() => null);
  say('landscape', frame && Math.abs(frame.ratio - 16/9) < 0.15,
      frame ? frame.ratio.toFixed(2) : 'no frame');

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
