// The capture frame holds its landscape shape before there is a capture, so
// the keyword list beside it does not collapse to two rows.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});
  await p.evaluate(() => {
    const r = ROWS[0];
    delete r.result.shot;                       // nothing captured
    const seed = ((r.kw || {}).all || [])[0] || {kw: 'x', vol: 10};
    r.kw.all = Array.from({length: 30}, (_, i) =>
      Object.assign({}, seed, {kw: 'term number ' + i}));
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForTimeout(400);

  const hist = '.prod[data-row="0"] [data-pane="history"]';
  say('placeholderFrame',
      (await p.$$eval(hist + ' .pvserp .shotwrap.empty', n => n.length)) === 1,
      'no frame when nothing is captured');
  say('saysNotCaptured',
      /Not captured/.test(await p.textContent(hist + ' .pvserp')));

  const h = async sel => p.$eval(sel, el => Math.round(el.getBoundingClientRect().height));
  const kw = await h(hist + ' .pvkw');
  const serp = await h(hist + ' .pvserp');
  say('listNotCollapsed', kw > 200, 'keyword panel is only ' + kw + 'px');
  say('stillMatches', Math.abs(kw - serp) <= 16, 'kw ' + kw + ' vs serp ' + serp);

  const frame = await p.$eval(hist + ' .pvserp .shotwrap', el => {
    const r = el.getBoundingClientRect();
    return r.width / r.height;
  });
  say('frameIsLandscape', Math.abs(frame - 16/9) < 0.15, frame.toFixed(2));

  const sc = await p.$eval(hist + ' .pvkw .pvscroll', el => ({
    scroll: el.scrollHeight, client: el.clientHeight}));
  say('listScrolls', sc.scroll > sc.client, sc.scroll + ' vs ' + sc.client);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
