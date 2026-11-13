#!/usr/bin/env node
'use strict';
/**
 * Re-run the v2 evaluation over the current batch in match-creation order and recalibrate the
 * global Stage-3 constants after every match.
 *
 *   pass 1 (walk-forward): for each match, in `YYYYMMDD--HH-MM` order, evaluate it with the global
 *           constants (`S0`, funds `K/d0/d1`) that the pool produced so far, then recalibrate them
 *           over the accumulated pool (`policy.tuningPool`, `worthless` excluded) and write them into
 *           `evaluate/config.json`.
 *   pass 2 (final): re-evaluate every current match once more with the converged constants so the
 *           published table uses one single baseline. `stage_1_v2` and the Stage-3 event compile do
 *           not read `S0`, but re-running the canonical entry point keeps every artifact consistent.
 *
 * `meta.json` is never written; the driver hashes it before and after and fails the report if a
 * byte changed.
 *
 * Usage: node evaluate/tools/run_batch_v2.js [--root evaluate/output] [--no-final] [--limit N]
 */
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {evaluateMatch, main: evaluateCorpus} = require('./evaluate_corpus_v2');
const {step: calibrateStep, persist} = require('./calibrate_stage3');

const ROOT = path.resolve(__dirname, '..', '..');
const OUTPUT = path.join(ROOT, 'evaluate', 'output');
const sha256 = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

function creationKey(dir) {
  const name = path.basename(dir);
  const embedded = name.match(/(\d{4})(\d{2})(\d{2})--(\d{2})-(\d{2})/);
  if (embedded) return `${embedded[1]}-${embedded[2]}-${embedded[3]}T${embedded[4]}:${embedded[5]}:00`;
  const metaFile = path.join(dir, 'meta.json');
  if (fs.existsSync(metaFile)) {
    const meta = JSON.parse(fs.readFileSync(metaFile, 'utf8').replace(/^\uFEFF/, ''));
    if (meta.createdAt) return meta.createdAt;
  }
  return `9999-99-99T99:99:99`;
}

function currentMatches(root) {
  return fs.readdirSync(root, {withFileTypes: true})
    .filter(entry => entry.isDirectory() && !['_archive', 'micro', 'events-live'].includes(entry.name))
    .map(entry => path.join(root, entry.name))
    .filter(dir => fs.existsSync(path.join(dir, 'prepared', 'preprocess.json')) ||
      fs.existsSync(path.join(dir, 'stage_3', 'score.json')))
    .sort((a, b) => creationKey(a).localeCompare(creationKey(b)) || path.basename(a).localeCompare(path.basename(b)));
}

async function main(argv = process.argv) {
  const args = argv.slice(2);
  let root = OUTPUT, final = true, limit = Infinity;
  while (args.length) {
    const flag = args.shift();
    if (flag === '--root') root = path.resolve(args.shift());
    else if (flag === '--no-final') final = false;
    else if (flag === '--limit') limit = Number(args.shift());
    else throw Error('Usage: node evaluate/tools/run_batch_v2.js [--root <dir>] [--no-final] [--limit N]');
  }
  const matches = currentMatches(root).slice(0, limit);
  const before = Object.fromEntries(matches.map(dir => [path.basename(dir), sha256(path.join(dir, 'meta.json'))]));
  const startedAt = new Date().toISOString(), steps = [];
  console.log(`batch: ${matches.length} matches, order by creation time`);
  for (const [index, dir] of matches.entries()) {
    const name = path.basename(dir), clock = Date.now();
    const result = await evaluateMatch(dir);
    const calibration = calibrateStep(root, {label: `${index + 1}/${matches.length} ${name}`});
    persist(calibration);
    const record = {index: index + 1, match: name, at: new Date().toISOString(),
      scoreWindowSeconds: result.scoreWindowSeconds, outcome: result.result.outcome,
      scores: result.scores, ms: Date.now() - clock,
      pool: calibration.pool, s0: calibration.next, s0Previous: calibration.previous, outcomes: calibration.outcomes};
    steps.push(record);
    console.log(`[${index + 1}/${matches.length}] ${name} S1 ${result.scores.stage1v2} S3 ${result.scores.stage3}` +
      ` total ${result.scores.totalV2} | S0 ${calibration.next.ambushS0}/${calibration.next.barrageS0}` +
      ` (pool ${calibration.pool.matches}, -${calibration.pool.excluded}) ${record.ms}ms`);
  }
  let finalPass = null;
  if (final) {
    const clock = Date.now();
    await evaluateCorpus(['node', 'evaluate_corpus_v2.js', '--current']);
    finalPass = {at: new Date().toISOString(), ms: Date.now() - clock,
      s0: steps.length ? steps.at(-1).s0 : null};
    console.log(`final pass with S0 ${JSON.stringify(finalPass.s0)} in ${finalPass.ms}ms`);
  }
  const after = Object.fromEntries(matches.map(dir => [path.basename(dir), sha256(path.join(dir, 'meta.json'))]));
  const changed = Object.keys(before).filter(name => before[name] !== after[name]);
  const log = {schema: 1, version: 'batch-v2-v1', startedAt, finishedAt: new Date().toISOString(),
    root: path.relative(ROOT, root).replace(/\\/g, '/') || '.', order: matches.map(dir => path.basename(dir)),
    steps, finalPass, meta: {unchanged: changed.length === 0, changed}};
  const out = path.join(root, '_batch-v2.json');
  fs.writeFileSync(out, JSON.stringify(log, null, 2) + '\n', 'utf8');
  console.log(`wrote ${out}; meta.json unchanged: ${log.meta.unchanged}`);
  if (changed.length) throw Error(`meta.json changed: ${changed.join(', ')}`);
  return log;
}

if (require.main === module) main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
module.exports = {creationKey, currentMatches, main};
