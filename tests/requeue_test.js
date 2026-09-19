// THE CAPTURE WAITS FOR THE TASK TO START. "Task Not Found" also comes back
// while the organic task is still queued, so the poll holds for 75 seconds
// before it treats the id as missing and asks for a fresh one.
const {chromium} = require('/root/work/node_modules/playwright-core');
(async () => {
  const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  let bad = 0;
  const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

  const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA'
            + 'C0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  let queued = 0, fetched = 0;
  await p.route('**/api/serp_recommend', r =>
    r.fulfill({status:200, contentType:'application/json', body:'{}'}));
  await p.route('**/api/serp_queue', r => {
    queued++;
    return r.fulfill({status:200, contentType:'application/json',
      body: JSON.stringify({task_id: 'task-' + queued, device: 'desktop',
                            width: 1100, height: 1200, scale: 1})});
  });
  await p.route('**/api/serp_fetch', r => {
    fetched++;
    // The first task is lost; the one queued after it works.
    const body = r.request().postDataJSON() || {};
    if (body.task_id === 'task-1')
      return r.fulfill({status:200, contentType:'application/json',
        body: JSON.stringify({ready:false, gone:true,
                              why:'that queued capture no longer exists'})});
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
  // REAL TIME, NOT POLL COUNT. The first ask waits 12s and the rest 6s apart
  // (2026-09-19), so a requeue and a second landing is ~20 seconds.
  for (let i = 0; i < 160; i++) {
    const shot = await p.evaluate(() => (ROWS[0].result || {}).shot || '');
    if (shot && queued >= 2) break;
    await p.waitForTimeout(500);
  }

  say('queuedTwice', queued === 2, queued + ' queue calls');
  say('waitedBeforeRequeue', fetched >= 2, 'it requeued without polling');
  say('polledBoth', fetched >= 2, fetched + ' fetch calls');
  const shot = await p.evaluate(() => (ROWS[0].result || {}).shot || '');
  say('captureLanded', shot.startsWith('data:image/'), shot.slice(0, 40));

  const msg = await p.textContent(hist + ' [data-serpmsg]').catch(() => '');
  say('noDeadEndMessage', !/no longer exists/.test(msg), msg);

  await b.close();
  console.log(bad ? 'failed=' + bad : 'ok all');
  process.exit(bad ? 1 : 0);
})();
