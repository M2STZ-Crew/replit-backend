// Every line the Admin console shows through t() has its Tagalog, with the
// same {blanks} (Tagalog everywhere, 1.3). Run: npm run check:tagalog
// Prints the missing lines and exits 1; with --list, prints them as a JSON
// skeleton to fill in.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { TAGALOG } from '../src/i18n/tagalog.js';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'src');
const CALL = /(?<![\w$.])tr?\(\s*'((?:[^'\\\n]|\\.)*)'/g;

function sources(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return sources(p);
    return /\.(jsx?|mjs)$/.test(e.name) && !p.endsWith(join('i18n', 'tagalog.js')) ? [p] : [];
  });
}

const unescape = (s) => s.replace(/\\(.)/g, (_, c) => (c === 'n' ? '\n' : c));
const blanks = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',');

const keys = new Map();
for (const file of sources(root)) {
  const code = readFileSync(file, 'utf8');
  for (const m of code.matchAll(CALL)) {
    const key = unescape(m[1]);
    if (!keys.has(key)) keys.set(key, `${relative(root, file)}:${code.slice(0, m.index).split('\n').length}`);
  }
}

const missing = [...keys].filter(([k]) => !(k in TAGALOG));
const wrongBlanks = [...keys].filter(([k]) => k in TAGALOG && blanks(k) !== blanks(TAGALOG[k]));
const empty = Object.entries(TAGALOG).filter(([, v]) => !String(v).trim());
const unused = Object.keys(TAGALOG).filter((k) => !keys.has(k));

if (process.argv.includes('--list')) {
  console.log(JSON.stringify(Object.fromEntries(missing.map(([k]) => [k, ''])), null, 1));
  process.exit(0);
}
console.log(`${keys.size} lines through t(); ${Object.keys(TAGALOG).length} Tagalog entries.`);
for (const [k, where] of missing) console.log(`missing  ${where}  ${JSON.stringify(k)}`);
for (const [k, where] of wrongBlanks) console.log(`blanks   ${where}  ${JSON.stringify(k)}`);
for (const [k] of empty) console.log(`empty    ${JSON.stringify(k)}`);
if (unused.length) console.log(`(${unused.length} entries no longer used: ${unused.slice(0, 5).map((k) => JSON.stringify(k)).join(', ')}${unused.length > 5 ? ', …' : ''})`);
process.exit(missing.length || wrongBlanks.length || empty.length ? 1 : 0);
