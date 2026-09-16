// AN ERROR IS A SENTENCE, NOT A PAGE. A 502 from the host answers with an HTML
// error document, and its first 160 characters were printed into panel headings.
const fs = require('fs');
const s = fs.readFileSync(__dirname + '/../templates/adtini.html', 'utf8');
let bad = 0;
const say = (n, ok, extra='') => { if(!ok){bad++; console.log('FAIL', n, extra);} };

say('helperExists', /function httpSays\(/.test(s));
say('postUsesIt', /throw new Error\(httpSays\(r\.status, txt\)\)/.test(s));
say('noRawBodyInErrors', !/txt\.slice\(0,\s*160\)/.test(s), 'still slicing the body');

// The helper itself, on the shapes that actually arrive.
const fn = new Function('return (' + s.match(
  /function httpSays\(status, txt\)\{[\s\S]*?\n\}/)[0] + ')')();
const HTML502 = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">'
  + '<meta name="viewport" content="width=device-width, initial-scale=1">'
  + '<title>502 Bad Gateway</title>';
say('html502', fn(502, HTML502) === 'the server did not answer (502) — it may be restarting',
    fn(502, HTML502));
say('html503', /did not answer \(503\)/.test(fn(503, HTML502)), fn(503, HTML502));
say('html500', fn(500, HTML502) === 'the server returned an error page (500)', fn(500, HTML502));
say('noDoctypeLeaks', !/DOCTYPE/i.test(fn(502, HTML502)), fn(502, HTML502));
say('noTagsLeak', !/[<>]/.test(fn(500, HTML502)), fn(500, HTML502));

// A plain-text body is still worth showing, trimmed to one line.
say('plainText', fn(400, 'At least one keyword is required')
    === 'HTTP 400 — At least one keyword is required', fn(400, 'At least one keyword is required'));
say('collapsesWhitespace', fn(400, 'line one\n\n   line two') === 'HTTP 400 — line one line two',
    fn(400, 'line one\n\n   line two'));
say('empty', fn(504, '') === 'HTTP 504', fn(504, ''));
say('bounded', fn(400, 'x'.repeat(4000)).length < 200, String(fn(400, 'x'.repeat(4000)).length));

console.log(bad ? 'failed=' + bad : 'ok=12 failed=0');
process.exit(bad ? 1 : 0);
