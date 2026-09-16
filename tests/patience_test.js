// "Task Not Found" while the organic task is still QUEUED must not be mistaken
// for a lost task. Treating it as terminal made the capture give up seconds
// after queueing, re-queue, ask too early again, and report "keeps being lost".
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA'
            + 'C0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  let queued = 0, polls = 0;
  await p.route('**/api/serp_recommend', r =>
    r.fulfill({status:200, contentType:'application/json', body:'{}'}));
  await p.route('**/api/serp_queue', r => {
    queued++;
    return r.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({task_id:'t' + queued, device:'desktop',
                            width:1100, height:1200, scale:1})});
  });
  // Not found for the first four polls -- the task is still queued -- then it
  // renders. The old code would have given up on the first one.
  await p.route('**/api/serp_fetch', r => {
    polls++;
    if (polls <= 4)
      return r.fulfill({status:200, contentType:'application/json',
        body: JSON.stringify({ready:false, notfound:true, status:'Task Not Found.'})});
    return r.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({ready:true, keyword:'x', data_url: PNG})});
  });

  await p.goto('http://127.0.0.1:5203/adtini/forecast?client=Drainify',
               {waitUntil:'networkidle'});
  await p.waitForSelector('.prod[data-row="0"] .qres', {timeout:15000});
  await p.evaluate(() => { delete ROWS[0].result.shot; draw(); });
  await p.click('.prod[data-row="0"] .ptabs button[data-tab="history"]');
  await p.click('.prod[data-row="0"] .hist tr.histrow .btn-open');
  await p.waitForTimeout(300);

  const hist = '.prod[data-row="0"] [data-pane="history"]';
  await p.click(hist + ' .pvserp .pvmini');
  for (let i = 0; i < 60; i++) {
    const shot = await p.evaluate(() => (ROWS[0].result || {}).shot || '');
    if (shot) break;
    await p.waitForTimeout(500);
  }

  say('keptWaiting', polls >= 5, polls + ' polls before it gave up');
  say('didNotRequeue', queued === 1, queued + ' queue calls — it requeued too early');
  const shot = await p.evaluate(() => (ROWS[0].result || {}).shot || '');
  say('captureLanded', shot.startsWith('data:image/'), shot.slice(0, 30));
  const msg = await p.textContent(hist + ' [data-serpmsg]').catch(() => '');
  say('noLostTaskClaim', !/lost|no longer exists/.test(msg), msg);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
