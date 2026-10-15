// THE ORM CONFIG OVERRIDES REACH THE PRICER. generateOrm sent a literal {},
// so Monthly cost / Review removal / Site removal set in Config were saved
// and shown on the run but never priced. (2026-10-15, Kiri)
const fs = require('fs');
const src = fs.readFileSync(__dirname + '/../templates/adtini.html', 'utf8');
const m = src.match(/function ormOverrides\(cfg\)\{[\s\S]*?\n\}\n/);
let pass = 0, fail = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}: ${JSON.stringify(got)}`);
};
check('ormOverrides is defined', !!m, true);
const ormOverrides = eval('(' + m[0].replace(/^function ormOverrides/, 'function') + ')');
check('blank config sends nothing', ormOverrides({ov_monthly: '', ov_review: ''}), {});
check('no config sends nothing', ormOverrides(undefined), {});
check('monthly reaches monthly_hard', ormOverrides({ov_monthly: '1787.5'}), {monthly_hard: 1787.5});
check('all three, typed with $ and commas',
  ormOverrides({ov_review: '$65', ov_std: '4,875', ov_monthly: '1,788'}),
  {review_hard: 65, art_std_hard: 4875, monthly_hard: 1788});
check('generateOrm sends them', /overrides: ormOverrides\(r\.cfg\)/.test(src), true);
console.log(`\nPASS=${pass} FAIL=${fail}`);
process.exit(fail ? 1 : 0);
