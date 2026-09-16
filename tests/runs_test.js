// EVERY GENERATE IS A RUN, AND A RUN CAN BE REMOVED. A build made on the wrong
// markets stayed on the record for ever, and the row reads the newest one.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };
  p.on('dialog', d => d.accept());

  const hist = '.prod[data-row="0"] [data-pane="history"]';
  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});

  // Three runs on the record, newest first.
  await p.evaluate(() => {
    const r = ROWS[0];
    const q = n => Object.assign(JSON.parse(JSON.stringify(r.result)), {
      pricing: Object.assign({}, r.result.pricing,
        {handoff: {package: {base: n, intermediate: n + 100, advanced: n + 200}}})});
    r.history = [
      {when: 'run three', resp: 'c', quote: q(3000)},
      {when: 'run two',   resp: 'b', quote: q(2000)},
      {when: 'run one',   resp: 'a', quote: q(1000)},
    ];
    r.result = r.history[0].quote;
    r.openRun = null;
    draw();
  });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.waitForTimeout(250);

  const rows = () => p.$$eval(hist + ' tr.histrow td:first-child',
                              n => n.map(x => x.textContent.replace(/\s+/g, ' ').trim()));
  say('threeRuns', (await rows()).length === 3, JSON.stringify(await rows()));
  say('newestFirst', /run three/.test((await rows())[0]), (await rows())[0]);
  say('eachHasDelete',
      (await p.$$eval(hist + ' tr.histrow [data-del]', n => n.length)) === 3);

  // Removing the middle run leaves the other two and does not change the row.
  const before = await p.evaluate(() => (ROWS[0].result.pricing.handoff.package.base));
  await p.click(hist + ' tr.histrow:nth-of-type(2) [data-del]');
  await p.waitForTimeout(600);
  let left = await rows();
  say('middleGone', left.length === 2 && !left.some(t => /run two/.test(t)), JSON.stringify(left));
  say('rowUnchanged',
      (await p.evaluate(() => ROWS[0].result.pricing.handoff.package.base)) === before,
      'removing an older run moved the quote');

  // Removing the NEWEST promotes the one before it.
  await p.click(hist + ' tr.histrow:nth-of-type(1) [data-del]');
  await p.waitForTimeout(600);
  left = await rows();
  say('newestGone', left.length === 1 && /run one/.test(left[0]), JSON.stringify(left));
  say('promoted',
      (await p.evaluate(() => ROWS[0].result.pricing.handoff.package.base)) === 1000,
      String(await p.evaluate(() => ROWS[0].result.pricing.handoff.package.base)));
  const resp = await p.textContent(hist + ' tr.histrow');
  say('respFollows', /1,000/.test(resp), resp.replace(/\s+/g, ' ').slice(0, 80));

  // Publish and Open are not delete.
  await p.click(hist + ' tr.histrow .btn-pub');
  await p.waitForTimeout(300);
  say('publishDoesNotDelete', (await rows()).length === 1);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
