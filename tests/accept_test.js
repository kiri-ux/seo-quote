// The report attached to a quote is almost always a slide deck. A .pptx that
// the file picker greys out cannot be attached at all.
const fs = require('fs');
const s = fs.readFileSync(__dirname + '/../templates/adtini.html', 'utf8');
const m = s.match(/id="pastReport"[\s\S]{0,200}?accept="([^"]*)"/);
let bad = 0;
const say = (n, ok, extra='') => { if (!ok) { bad++; console.log('FAIL', n, extra); } };

say('accept.present', !!m, 'no accept attribute on #pastReport');
const list = m ? m[1].split(',').map(x => x.trim().toLowerCase()) : [];
for (const ext of ['.pptx', '.potx', '.pdf', '.docx', '.xlsx', '.csv', '.png', '.jpg'])
  say('accept' + ext, list.includes(ext), list.join(','));

// The legacy reader's own list is the floor -- anything it can read must be
// attachable here too, or the two tabs disagree about what a report is.
const legacy = fs.readFileSync(__dirname + '/../templates/index.html', 'utf8');
const lm = legacy.match(/id="reportFile"[\s\S]{0,120}?accept="([^"]*)"/);
if (lm) for (const ext of lm[1].split(',').map(x => x.trim().toLowerCase()))
  say('legacyparity' + ext, list.includes(ext), `adtini is missing ${ext}`);

console.log(bad ? `failed=${bad}` : `ok=${8 + (lm ? lm[1].split(',').length : 0)} failed=0`);
process.exit(bad ? 1 : 0);
