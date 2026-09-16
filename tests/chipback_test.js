// BACKSPACE POPS THE LAST CHIP, IN EVERY ONE OF THESE BOXES.
//
// Each is a multi-value question and the only way out of a wrong pick was the
// x -- leaving the keyboard to aim at a 9px target, once per value. The legacy
// form has had Backspace-pop since August; this one never got it.
//
// Two properties do the work, and both are ways it could be quietly wrong:
// it fires only on an EMPTY input, so it never eats a character someone is
// still typing; and it CLICKS THE X rather than removing the chip itself, so
// the standing-rejection bookkeeping behind that handler -- a removed proposal
// goes on seedDrop so the expansion stops offering it -- cannot be skipped.
//
// Driven through dispatched keydown rather than real typing because these boxes
// are inside a panel that is hidden until a client is loaded; the handler is on
// document, so it is the shipped path either way.
const {chromium} = require('/root/work/node_modules/playwright-core');

(async () => {
  const b = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const p = await b.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e).slice(0, 140)));
  await p.goto('http://127.0.0.1:5199/adtini/forecast', {waitUntil: 'domcontentloaded'});
  await p.waitForTimeout(1800);

  let bad = 0;
  const say = (n, ok, d) => {
    console.log((ok ? '  ok   ' : '  FAIL ') + n + (ok ? '' : ' :: ' + JSON.stringify(d)));
    if (!ok) bad++;
  };

  const res = await p.evaluate(() => {
    const out = {};
    const hit = inp => inp.dispatchEvent(new KeyboardEvent(
      'keydown', {key: 'Backspace', bubbles: true, cancelable: true}));
    // Free-text boxes and pick-list boxes take different code paths into the
    // same chipbox, so both kinds are covered.
    for (const k of ['focus', 'negatives', 'city', 'industry', 'goals', 'strategy']) {
      const box = document.querySelector(`[data-chips="${k}"]`);
      if (!box) { out[k] = 'no box'; continue; }
      chipbox(box, ['alpha one', 'beta two']);
      const inp = box.querySelector('.chipin');
      inp.value = '';
      hit(inp);
      out[k] = [...box.querySelectorAll('.chip')].map(c => c.firstChild.textContent.trim());
    }
    const box = document.querySelector('[data-chips="focus"]');
    // Repeated presses walk back through the list.
    chipbox(box, ['one', 'two', 'three']);
    const i0 = box.querySelector('.chipin');
    i0.value = '';
    hit(i0); hit(i0);
    out._twice = [...box.querySelectorAll('.chip')].map(c => c.firstChild.textContent.trim());
    // NOT mid-edit. The event must pass through untouched so the browser
    // deletes a character, and no chip may go.
    chipbox(box, ['alpha one']);
    const inp = box.querySelector('.chipin');
    inp.value = 'gamma';
    const ev = new KeyboardEvent('keydown', {key: 'Backspace', bubbles: true, cancelable: true});
    inp.dispatchEvent(ev);
    out._midEditPrevented = ev.defaultPrevented;
    out._midEditChips = [...box.querySelectorAll('.chip')].length;
    // An empty box must not throw.
    chipbox(box, []);
    const i2 = box.querySelector('.chipin');
    i2.value = '';
    hit(i2);
    out._emptyOk = [...box.querySelectorAll('.chip')].length === 0;
    return out;
  });

  for (const k of ['focus', 'negatives', 'city', 'industry', 'goals', 'strategy'])
    say(`${k}: backspace pops the last chip`,
        Array.isArray(res[k]) && res[k].length === 1 && res[k][0] === 'alpha one', res[k]);
  say('two presses pop two chips, newest first',
      JSON.stringify(res._twice) === JSON.stringify(['one']), res._twice);
  say('does not fire while the input still has text',
      res._midEditPrevented === false && res._midEditChips === 1,
      [res._midEditPrevented, res._midEditChips]);
  say('an empty box is harmless', res._emptyOk === true, res._emptyOk);
  say('no page errors', errs.length === 0, errs);

  console.log(bad ? 'failed=' + bad : 'ok all');
  await b.close();
  process.exit(bad ? 1 : 0);
})();
