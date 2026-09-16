// The run IS the expander. A collapsed header above the table repeated the date
// and headline the row already carries, so one run was on screen twice.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  await p.goto('http://127.0.0.1:5203/adtini/forecast', {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"]', {timeout:15000});
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.waitForTimeout(250);

  const hist = '.prod[data-row="0"] [data-pane="history"]';
  say('noSeparateFold', await p.$$eval(`${hist} > .qres`, n => n.length) === 0,
      'a second collapsed header is still above the table');
  say('rowsDrawn', (await p.$$eval(`${hist} .histrow`, n => n.length)) > 0);
  say('startsClosed', await p.$$eval(`${hist} .histopen`, n => n.length) === 0);
  say('opensLabel', (await p.textContent(`${hist} .histrow .btn-open`)).trim() === 'Open');

  // Clicking the row opens the quote underneath it.
  await p.click(`${hist} .histrow td >> nth=1`);
  await p.waitForTimeout(300);
  say('rowOpens', (await p.$$eval(`${hist} .histopen`, n => n.length)) === 1);
  say('rowMarked', (await p.$$eval(`${hist} .histrow.on`, n => n.length)) === 1);
  say('closeLabel', (await p.textContent(`${hist} .histrow .btn-open`)).trim() === 'Close');
  say('quoteInside', (await p.$$eval(`${hist} .histopen .qbody`, n => n.length)) === 1);
  say('foldsInside', (await p.$$eval(`${hist} .histopen .qfold`, n => n.length)) === 3);
  say('noDuplicateHeader', await p.$$eval(`${hist} > .qres`, n => n.length) === 0);

  // Clicking again closes it.
  await p.click(`${hist} .histrow td >> nth=1`);
  await p.waitForTimeout(300);
  say('rowCloses', (await p.$$eval(`${hist} .histopen`, n => n.length)) === 0);

  // Publish To RZ is not an expander.
  await p.click(`${hist} .histrow .btn-pub`);
  await p.waitForTimeout(250);
  say('publishDoesNotOpen', (await p.$$eval(`${hist} .histopen`, n => n.length)) === 0);

  // The SERP panel offers a capture, and the proposal fold a download.
  await p.click(`${hist} .histrow .btn-open`);
  await p.waitForTimeout(300);
  say('serpButton', (await p.$$eval(`${hist} .pvserp .pvmini`, n => n.length)) === 1);
  const lbl = await p.textContent(`${hist} .pvserp .pvmini`);
  say('serpLabel', ['Capture','Recapture'].includes(lbl.trim()), lbl);
  say('proposalDownload', (await p.$$eval(`${hist} [data-prop]`, n => n.length)) === 1);
  say('downloadLabel',
      (await p.textContent(`${hist} [data-prop]`)).trim() === 'Download proposal');

  await b.close();
  console.log(bad ? `failed=${bad}` : 'ok all');
  process.exit(bad ? 1 : 0);
})();
