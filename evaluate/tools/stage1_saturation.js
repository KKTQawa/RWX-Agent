#!/usr/bin/env node
'use strict';
/**
 * Read-only Stage1 saturation check. It does not re-score any match.
 *
 *   node evaluate/tools/stage1_saturation.js
 *   node evaluate/tools/stage1_saturation.js --csv <detail.csv> --threshold 0.4
 *
 * The input is `_stage1-provisional-detail.csv`; `newU1..newU6` are the per-match
 * provisional u values. Scored features are f1/f2/f3/f5/f6; f4 is diagnostic-only.
 */
const fs = require('node:fs');
const path = require('node:path');
const {saturationCheck, SCORED_FEATURES, DIAGNOSTIC_FEATURES} = require('./stage1_provisional');

const ROOT = path.resolve(__dirname, '..', '..');
const DEFAULT_CSV = path.join(ROOT, 'evaluate', 'output', '_stage1-provisional-detail.csv');
const DEFAULT_OUT = path.join(ROOT, 'evaluate', 'output', '_stage1-saturation');

function parseCsv(text) {
  const rows = [];
  let row = [], field = '', quoted = false;
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { field += '"'; index++; }
      else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ',') { row.push(field); field = ''; }
    else if (char === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (char !== '\r') field += char;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows;
}

function loadRows(file) {
  if (!fs.existsSync(file)) throw Error(`missing detail CSV: ${file}`);
  const table = parseCsv(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  const header = table.shift();
  const index = Object.fromEntries(header.map((name, position) => [name, position]));
  for (const id of [...SCORED_FEATURES, ...DIAGNOSTIC_FEATURES]) {
    if (index[`newU${id.slice(1)}`] == null) throw Error(
      `detail CSV is missing newU${id.slice(1)}; regenerate it with stage1_provisional.js`);
  }
  return table.filter(row => row.length > 1 && row[index.match]).map(row => ({
    match: row[index.match],
    newU: Object.fromEntries([...SCORED_FEATURES, ...DIAGNOSTIC_FEATURES]
      .map(id => [id, Number(row[index[`newU${id.slice(1)}`]])])),
  }));
}

function markdown(check, source) {
  return ['# Stage1 provisional 饱和度检查', '',
    `输入：\`${source}\``,
    `阈值：每个计分特征 u=1 的局数占比 ≤ ${(check.threshold * 100).toFixed(0)}%；f4 仅诊断。`, '',
    '| 特征 | 范围 | u=1 | 占比 | max u | P90 u | 判定 |',
    '|---|---|---|---|---|---|---|',
    ...check.features.map(feature => `| ${feature.id} | ${feature.scope} | ${feature.count}/${feature.total} | ` +
      `${(feature.share * 100).toFixed(1)}% | ${feature.max ?? '—'} | ${feature.p90 ?? '—'} | ` +
      `${feature.pass == null ? '诊断' : (feature.pass ? '通过' : '**超限**')} |`), '',
    check.pass ? '**PASS**：所有计分特征都 ≤ 40%。'
      : `**FAIL**：${check.violations.join('、')} 超过 40%，才需要放宽 hi。`, ''].join('\n');
}

function main(argv = process.argv) {
  const args = argv.slice(2);
  let csv = DEFAULT_CSV, out = DEFAULT_OUT, threshold = 0.4, quiet = false;
  while (args.length) {
    const flag = args.shift();
    if (flag === '--csv') csv = path.resolve(args.shift());
    else if (flag === '--out') out = path.resolve(args.shift());
    else if (flag === '--threshold') threshold = Number(args.shift());
    else if (flag === '--quiet') quiet = true;
    else throw Error('Usage: node evaluate/tools/stage1_saturation.js [--csv file] [--threshold 0.4] [--out base]');
  }
  const check = saturationCheck(loadRows(csv), threshold);
  const payload = {schema: 1, source: path.relative(ROOT, csv).replace(/\\/g, '/'), ...check};
  fs.mkdirSync(path.dirname(out), {recursive: true});
  fs.writeFileSync(`${out}.json`, JSON.stringify(payload, null, 2) + '\n');
  fs.writeFileSync(`${out}.md`, markdown(check, payload.source) + '\n');
  if (!quiet) {
    console.log(`Stage1 saturation: ${check.pass ? 'PASS' : `FAIL (${check.violations.join(',')})`}`);
    for (const feature of check.features) console.log(
      `${feature.id.padEnd(3)} ${String(feature.count).padStart(2)}/${feature.total} ` +
      `${(feature.share * 100).toFixed(1).padStart(5)}%  maxU ${feature.max ?? '—'}  ${feature.scope}`);
  }
  if (!check.pass) process.exitCode = 1;
  return payload;
}

if (require.main === module) main();
module.exports = {parseCsv, loadRows, markdown, main};
