// What you do with a finished quote sits ON the quote: download the proposal,
// copy a link someone else can open. The download was buried inside a
// collapsed fold, and there was no link at all.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const ctx = await b.newContext({permissions: ['clipboard-read', 'clipboard-write']});
  const p = await ctx.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  let docCalls = 0;
  await p.route('**/api/proposal.docx', route => {
    docCalls++;
    return route.fulfill({status:200,
      contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      body: Buffer.from('PK not really a docx')});
  });

  const BASE = 'http://127.0.0.1:5203';
  const hist = '.prod[data-row="0"] [data-pane="history"]';
  const openRun = async () => {
    await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});
    await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
    await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
    await p.waitForTimeout(350);
  };

  await p.goto(BASE + '/adtini/forecast?client=Drainify', {waitUntil:'networkidle'});
  await openRun();

  // Both controls are visible the moment the run is open -- not inside a fold.
  say('actionBar', (await p.$$eval(hist + ' .qacts', n => n.length)) === 1);
  say('download.visible', await p.isVisible(hist + ' .qacts [data-prop]'));
  say('share.visible', await p.isVisible(hist + ' .qacts [data-share]'));
  say('download.label',
      (await p.textContent(hist + ' .qacts [data-prop]')).trim() === 'Download proposal');
  say('share.label',
      (await p.textContent(hist + ' .qacts [data-share]')).trim() === 'Copy review link');
  say('notInAFold', (await p.$$eval(hist + ' .qfold [data-prop]', n => n.length)) === 0);
  say('oneDownloadPerRow', (await p.$$eval(hist + ' [data-prop]', n => n.length)) === 1);

  // The download asks the server for the document.
  await p.click(hist + ' .qacts [data-prop]');
  await p.waitForTimeout(900);
  say('download.called', docCalls === 1, docCalls + ' calls');
  say('download.reports',
      /Downloaded\.|Request failed/.test(await p.textContent(hist + ' [data-propmsg]')),
      await p.textContent(hist + ' [data-propmsg]'));

  // The link is the client and the product, on this origin.
  await p.click(hist + ' .qacts [data-share]');
  await p.waitForTimeout(400);
  let url = await p.evaluate(() => navigator.clipboard.readText()).catch(() => '');
  if (!url) url = await p.inputValue(hist + ' .sharein').catch(() => '');
  say('share.gotALink', !!url, 'nothing was copied and no box appeared');
  const u = url ? new URL(url) : null;
  say('share.path', u && u.pathname === '/adtini/forecast', url);
  say('share.client', u && u.searchParams.get('client') === 'Drainify', url);
  say('share.product', u && u.searchParams.get('review') === 'seo', url);
  say('share.noNewFlag', u && !u.searchParams.has('new'), url);

  // And that link opens straight onto the newest run, expanded -- the person it
  // was sent to should not have to find it.
  if (u) {
    await p.goto(url, {waitUntil:'networkidle'});
    await p.waitForSelector('.prod[data-row="0"]', {timeout:15000});
    await p.waitForTimeout(600);
    say('share.opens', (await p.$$eval('.prod', n => n.length)) > 0);
    say('share.landsOnHistory',
        await p.$eval('.prod[data-row="0"] [data-pane="history"]', el => !el.hidden));
    say('share.runExpanded',
        (await p.$$eval('.prod[data-row="0"] [data-pane="history"] tr.histopen',
                        n => n.length)) === 1);
    say('share.newestRun',
        (await p.$eval('.prod[data-row="0"] [data-pane="history"] tr.histrow',
                       el => el.classList.contains('on'))), 'the open run is not the first');
    say('share.showsTheQuote',
        (await p.$$eval('.prod[data-row="0"] [data-pane="history"] .histopen .pvkw',
                        n => n.length)) === 1);
  }

  // The keyword rows no longer repeat the area name on every line.
  await p.goto(BASE + '/adtini/forecast?client=Drainify', {waitUntil:'networkidle'});
  await openRun();
  const kwText = await p.textContent(hist + ' .pvkw');
  say('rows.noAreaNames', !/statewide|nationwide/i.test(kwText),
      (kwText.match(/\w+ statewide/g) || []).slice(0, 2).join('|'));
  const marks = await p.$$eval(hist + ' .pvkw .volwide', n => n.map(x => ({
    text: x.textContent.trim(), title: x.getAttribute('title') || ''})));
  if (marks.length) {
    say('rows.markIsShort', marks.every(m => m.text === '*'),
        JSON.stringify(marks.slice(0, 2)));
    say('rows.markNamesAreaOnHover',
        marks.every(m => /not this market/.test(m.title)),
        JSON.stringify(marks[0]));
  }
  // The card still names it, once -- when there is anything to name.
  const card = await p.textContent(hist + ' .pview');
  if (marks.length)
    say('card.namesArea', /answered from \S/.test(card), card.slice(0, 120));
  else
    say('card.saysNothingToName', !/answered from/.test(card), card.slice(0, 120));

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
