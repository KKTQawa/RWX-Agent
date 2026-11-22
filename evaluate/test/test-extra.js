'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {mergeRow,identify,cleanOperations,gapStats,fluencyScore,scoredWindow,scoreMatch,report,DEFAULTS}=
  require('../score_extra');
const {current,loadConfig}=require('../config');

const P={spamSeconds:3,bucketSeconds:5,alpha:0.3,positionQuantum:1};
const near=(a,b,eps=1e-9)=>Math.abs(a-b)<eps;

test('before/after rows merge into one command and keep the late fields',()=>{
  const before={nativeId:'N-1',phase:'before',team:0,units:[],operation:'attack',action:'-1',
    x:100,y:200,targetId:null,timeMs:1000};
  const after={phase:'after',units:[7],targetId:42,results:[{applied:true}],timeMs:1000};
  const row=mergeRow(before,after);
  assert.deepEqual(row.units,[7]);
  assert.equal(row.targetId,42);
  assert.equal(row.x,100);
  assert.equal(row.applied,true);
  assert.equal(row.appliedKnown,true);
});

test('operation identity separates action, stop, point orders and unlocated material',()=>{
  assert.deepEqual(identify({operation:'action',action:'u_tank',units:[5]},P),
    {sig:'a:u_tank:5',spamSig:'a:u_tank:5',degraded:false});
  assert.deepEqual(identify({operation:'stop',units:[9]},P),{sig:'s:9',spamSig:'s:9',degraded:false});
  assert.deepEqual(identify({operation:'move',x:100,y:200,units:[1]},P),
    {sig:'p:100:200:',spamSig:'p:100:200:',degraded:false});
  const blind=identify({operation:'move',nativeId:'N-9',units:[1]},P);
  assert.equal(blind.sig,'p:N-9');
  assert.equal(blind.spamSig,null);
  assert.equal(blind.degraded,true);
});

test('a box-select is one operation, not one per unit',()=>{
  const {operations,counters}=cleanOperations([{nativeId:'N-1',team:0,operation:'move',units:[1,2,3],
    x:100,y:200,timeMs:1000}],P);
  assert.equal(operations.length,1);
  assert.equal(operations[0].units,3);
  assert.ok(near(operations[0].weight,1+0.3*Math.log(3),1e-3));
  assert.equal(counters.unitOrders,3);
});

test('repeat orders from the same unit inside the spam window count once',()=>{
  const rows=[{nativeId:'N-1',team:0,operation:'move',units:[1],x:100,y:200,timeMs:1000},
    {nativeId:'N-2',team:0,operation:'move',units:[1],x:100,y:200,timeMs:2000}];
  const {operations,counters}=cleanOperations(rows,P);
  assert.equal(operations.length,1);
  assert.equal(counters.spamDropped,1);
  const later=cleanOperations([rows[0],{...rows[1],timeMs:4000}],P);
  assert.equal(later.operations.length,1); // same 5 s bucket, same point
  assert.equal(later.counters.spamDropped,0); // outside the 3 s spam window
});

test('simultaneous orders to one point merge, different points do not',()=>{
  const rows=[{nativeId:'N-1',team:0,operation:'move',units:[1],x:100,y:200,timeMs:1000},
    {nativeId:'N-2',team:0,operation:'move',units:[2],x:100,y:200,timeMs:1500},
    {nativeId:'N-3',team:0,operation:'move',units:[3],x:900,y:200,timeMs:1200}];
  const {operations}=cleanOperations(rows,P);
  assert.equal(operations.length,2);
  assert.deepEqual(operations.map(op=>op.units).sort(),[1,2]);
});

test('two buildings producing the same unit are two operations',()=>{
  const rows=[{nativeId:'N-1',team:0,operation:'action',action:'u_tank',units:[5],timeMs:1000},
    {nativeId:'N-2',team:0,operation:'action',action:'u_tank',units:[6],timeMs:1200}];
  const {operations}=cleanOperations(rows,P);
  assert.deepEqual(operations.map(op=>op.sig),['a:u_tank:5','a:u_tank:6']);
});

test('material without coordinates degrades to one operation per command',()=>{
  const rows=[{nativeId:'N-1',team:0,operation:'move',units:[1],timeMs:1000},
    {nativeId:'N-2',team:0,operation:'move',units:[1],timeMs:2000}];
  const {operations,counters}=cleanOperations(rows,P);
  assert.equal(operations.length,2);
  assert.equal(counters.degradedCommands,2);
  assert.equal(counters.spamDropped,0);
});

test('gap statistics report mean, spread, cv and burstiness',()=>{
  const stats=gapStats([4,4,4]);
  assert.equal(stats.n,3);
  assert.equal(stats.mean,4);
  assert.equal(stats.sd,0);
  assert.equal(stats.cv,0);
  assert.equal(stats.burstiness,-1);
  assert.equal(gapStats([]).cv,null);
});

test('no operations scores zero instead of throwing',()=>{
  const score=fluencyScore([],{startMs:0,endMs:100000},{mu0:15});
  assert.equal(score.fluency,0);
  assert.equal(score.components.S_rate,0);
  assert.equal(score.rhythm.cv,null);
  assert.equal(score.components.smoothBasis,'no_operations');
});

test('rhythm is the windowed count cv, not the raw gap cv',()=>{
  // 每 30 s 打一簇 5 条：命令间隔极不均匀（gap cv 很大），但每窗操作数完全一样。
  const cluster=base=>Array.from({length:5},(_,index)=>({t:base+index*50,operation:'move',units:1,weight:1}));
  const operations=[...cluster(1000),...cluster(31000),...cluster(61000),...cluster(91000)];
  const score=fluencyScore(operations,{startMs:0,endMs:120000},
    {T:8,mu0:15,q0:0.15,q1:0.65,c0:0.4,c1:0.9,smoothWindowSeconds:30});
  assert.equal(score.rhythm.windows,4);
  assert.equal(score.rhythm.cv,0);
  assert.ok(score.rhythm.gapCv>1);
  assert.equal(score.components.S_smooth,1);
  assert.equal(score.components.smoothBasis,'window_cv');
});

test('a window shorter than two bins earns no rhythm credit',()=>{
  const operations=[{t:0,operation:'move',units:1,weight:1},{t:5000,operation:'move',units:1,weight:1}];
  const score=fluencyScore(operations,{startMs:0,endMs:40000},
    {T:8,mu0:15,q0:0.15,q1:0.65,c0:0.4,c1:0.9,smoothWindowSeconds:30});
  assert.equal(score.rhythm.cv,null);
  assert.equal(score.components.smoothBasis,'insufficient_windows');
  assert.equal(score.components.S_smooth,0);
});

test('smoothWindowSeconds 0 keeps the gap-based term for diagnostics',()=>{
  const operations=[0,4000,8000].map(t=>({t,operation:'move',units:1,weight:1}));
  const score=fluencyScore(operations,{startMs:0,endMs:20000},
    {T:8,q0:0.15,q1:0.65,c0:0.4,c1:0.9,smoothWindowSeconds:0});
  assert.equal(score.components.smoothBasis,'gap_cv');
  assert.equal(score.rhythm.windows,null);
  assert.equal(score.rhythm.gaps,2);
});

test('a steady cadence saturates the rate term and passes both halves',()=>{
  const operations=Array.from({length:25},(_,index)=>({t:index*4000,operation:'move',units:1,weight:1}));
  const score=fluencyScore(operations,{startMs:0,endMs:100000},
    {T:8,mu0:15,q0:0.15,q1:0.65,c0:0.85,c1:1.6,weightDead:0.5,weightSmooth:0.5});
  assert.ok(near(score.rate.muPerMinute,15,1e-6));
  assert.ok(near(score.components.S_rate,1-Math.exp(-1),1e-3));
  assert.equal(score.components.S_dead,1);
  assert.equal(score.components.S_smooth,1);
  assert.ok(near(score.fluency,100*(1-Math.exp(-1)),1e-3));
});

test('one long idle stretch takes the dead term to zero',()=>{
  const operations=[{t:0,operation:'move',units:1,weight:1},{t:90000,operation:'move',units:1,weight:1}];
  const score=fluencyScore(operations,{startMs:0,endMs:100000},{T:8,mu0:15,q0:0.15,q1:0.65});
  assert.equal(score.dead.idleSeconds,100);
  assert.equal(score.dead.share,1);
  assert.equal(score.components.S_dead,0);
  assert.equal(score.fluency,0);
});

test('the head and tail of the window count as idle time',()=>{
  const operations=[{t:40000,operation:'move',units:1,weight:1}];
  const score=fluencyScore(operations,{startMs:0,endMs:100000},{T:8,q0:0.15,q1:0.65});
  assert.equal(score.dead.idleSeconds,100);
  assert.equal(score.components.S_dead,0);
  assert.equal(score.window,undefined);
});

test('longest gaps are reported for explaining a low score',()=>{
  const operations=[{t:0,operation:'move',units:1,weight:1},{t:10000,operation:'move',units:1,weight:1},
    {t:50000,operation:'move',units:1,weight:1},{t:52000,operation:'move',units:1,weight:1}];
  const score=fluencyScore(operations,{startMs:0,endMs:52000},{T:8});
  assert.deepEqual(score.longestGaps[0],{fromMs:10000,toMs:50000,gapSeconds:40});
});

test('fluency stays inside 0..100 for degenerate windows',()=>{
  const operations=[{t:1000,operation:'move',units:1,weight:1}];
  assert.equal(fluencyScore(operations,{startMs:0,endMs:0},{}).fluency,0);
  const huge=Array.from({length:500},(_,index)=>({t:index*100,operation:'move',units:1,weight:1}));
  const score=fluencyScore(huge,{startMs:0,endMs:60000},{mu0:1});
  assert.ok(score.fluency>=0&&score.fluency<=100);
});

test('configured anchors are the ones the score reads',()=>{
  const configured=current('extra.parameters.fluency',loadConfig());
  for(const key of ['T','mu0','q0','q1','c0','c1','alpha','spamSeconds','bucketSeconds','skipHeadSeconds',
    'positionQuantum','weightDead','weightSmooth','countAttack'])
    assert.equal(typeof configured[key],typeof DEFAULTS[key],key);
});

test('the scored window comes from the stage3 summary',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'extra-window-'));
  fs.mkdirSync(path.join(dir,'stage_3'),{recursive:true});
  fs.writeFileSync(path.join(dir,'stage_3','summary.json'),
    JSON.stringify({durationMs:120000,team:1,endReason:'preprocess_cut'}));
  const window=scoredWindow(dir);
  assert.equal(window.endMs,120000);
  assert.equal(window.team,1);
  assert.equal(window.endReason,'preprocess_cut');
  fs.rmSync(dir,{recursive:true,force:true});
});

test('a match scores end to end from its telemetry file',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'extra-match-'));
  fs.mkdirSync(path.join(dir,'prepared'),{recursive:true});
  fs.mkdirSync(path.join(dir,'stage_3'),{recursive:true});
  fs.writeFileSync(path.join(dir,'stage_3','summary.json'),JSON.stringify({durationMs:120000,team:0}));
  fs.writeFileSync(path.join(dir,'prepared','telemetry.jsonl'),[
    {kind:'meta',team:0,timeMs:0},
    {kind:'native',nativeId:'N-1',phase:'before',team:0,units:[1],operation:'move',action:'-1',
      x:100,y:200,timeMs:40000},
    {kind:'native',nativeId:'N-1',phase:'after',team:0,units:[1],operation:'move',action:'-1',
      x:100,y:200,results:[{applied:true}],timeMs:40000},
    {kind:'native',nativeId:'N-2',phase:'before',team:1,units:[],operation:'attack',action:'-1',
      x:10,y:20,timeMs:41000},
    {kind:'end',timeMs:120000},
  ].map(row=>JSON.stringify(row)).join('\n')+'\n');
  const score=await scoreMatch(dir);
  assert.equal(score.counts.nativeRows,3);
  assert.equal(score.counts.otherTeam,1);
  assert.equal(score.counts.kept,1);
  assert.equal(score.rate.operations,1);
  assert.equal(score.appliesToTotal,false);
  assert.equal(score.window.skipHeadSeconds,30);
  assert.ok(/not in total/.test(report(score)));
  fs.rmSync(dir,{recursive:true,force:true});
});
