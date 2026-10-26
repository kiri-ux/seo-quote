// ONE MARKUP, WHICHEVER BOX WAS TYPED IN LAST. A form set to 0% priced at the
// 48% left in Config, because pricing reads Config first. (2026-10-26, Kiri)
const fs = require('fs');
const src = fs.readFileSync(__dirname + '/../templates/adtini.html', 'utf8');
let pass = 0, fail = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(got)}`);
};
const m = src.match(/function syncCfg\(r\)\{[\s\S]*?\n\}\n/);
check('syncCfg is defined', !!m, true);
let VIEW, PANE = {};
const cfgCollect = () => Object.assign({}, PANE);
const cfgOverride = () => ({});
const syncCfg = eval('(' + m[0].replace(/^function syncCfg/, 'function') + ')');
const price = r => parseFloat(String(r.cfg && r.cfg.markup || r.data.markup || 35));

let r = {data: {markup: '0'}, cfg: {markup: '48', ov_monthly: '1430'}};
VIEW = 'form'; syncCfg(r);
check('form at 0% beats a stale 48% in Config', price(r), 0);
check('and the override stays', r.cfg.ov_monthly, '1430');

r = {data: {markup: '35'}, cfg: {}};
VIEW = 'cfg'; PANE = {markup: '0', ov_monthly: '3750'};
syncCfg(r);
check('Config at 0% prices at 0%', price(r), 0);
check('and writes the form box', r.data.markup, '0');
check('the Config monthly is kept', r.cfg.ov_monthly, '3750');

r = {data: {markup: '35'}};
VIEW = 'form'; syncCfg(r);
check('no Config yet: the form prices', price(r), 35);

check('every price path syncs', (src.match(/^  syncCfg\(r\);$/gm) || []).length, 4);
check('leaving a pane keeps its edits', /function show\(view\)\{[\s\S]{0,600}syncCfg\(r\)/.test(src), true);
console.log(`\nPASS=${pass} FAIL=${fail}`);
process.exit(fail ? 1 : 0);
