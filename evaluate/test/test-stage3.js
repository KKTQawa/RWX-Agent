'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {compile}=require('../evaluate_stage_3');
const {scoreEvents,loss,DEFAULTS}=require('../score_stage_3');

test('stage3 compiler applies collection gates and preserves the grinder funnel',()=>{
  const rows=[
    {kind:'meta',schema:1,team:0,source:'replay',timeMs:0},
    {kind:'stage3_meta',schema:1,timeMs:0,X:160},
    {kind:'stage3_ambush',phase:'hit',eventId:'A-1',unitId:1,type:'tank',fromMs:1000,
      DHp:20,DShield:0,N:1,maxHp:100,maxShield:0,cost:350,timeMs:1000},
    {kind:'stage3_ambush',phase:'close',eventId:'A-1',unitId:1,type:'tank',fromMs:1000,toMs:4000,
      durationMs:3000,DHp:20,DShield:0,N:1,maxHp:100,maxShield:0,cost:350,complete:true,timeMs:4000},
    {kind:'stage3_barrage',phase:'hit',eventId:'H-1',unitId:2,type:'turret',fromMs:2000,
      DHp:40,DShield:0,N:2,maxHp:500,maxShield:0,cost:1500,timeMs:3000},
    {kind:'stage3_barrage',phase:'close',eventId:'H-1',unitId:2,type:'turret',fromMs:2000,toMs:9000,
      DHp:40,DShield:0,N:2,maxHp:500,maxShield:0,cost:1500,complete:true,timeMs:9000},
    {kind:'stage3_builder_death',unitId:3,type:'builder',deathMs:8000,weight:1,damageKilled:true,
      transported:false,zoneId:null,ageMs:null,scoreable:false,seq:8,timeMs:8000},
    {kind:'stage3_zone',action:'create',zoneId:1,birthMs:5000,timeMs:5000},
    {kind:'end',reason:'replay_end',timeMs:10000},
  ];
  const result=compile(rows);
  assert.equal(result.summary.dropped.ambushShort,1);
  assert.deepEqual(result.events.map(e=>e.type),['STAGE3_BARRAGE','STAGE3_GRINDER']);
  assert.equal(result.events[0].N,2);
  assert.equal(result.events[1].reason,'OUTSIDE_ACTIVE_ZONE');
  assert.equal(result.summary.zones.created,1);
});

test('ambush severity uses damage, warning frequency, duration and value terms',()=>{
  const event={D_hp:50,D_sh:0,N:8,T_ms:30000,HP_max:100,Shield_max:0,cost:1000,died:false};
  const item=loss(event,DEFAULTS.ambush,DEFAULTS.alpha,DEFAULTS.beta,true);
  assert.equal(item.L,.45);
  assert.equal(item.W,1);
  assert.equal(item.w,1);
  assert.equal(item.Tf,1.5);
  assert.ok(Math.abs(item.s-.675)<1e-12);
});

test('stage3 scoring saturates two loss families and anchor-merges grinder deaths',()=>{
  const events=[
    {id:'A',type:'STAGE3_AMBUSH',scoreable:true,D_hp:50,D_sh:0,N:8,T_ms:30000,
      HP_max:100,Shield_max:0,cost:1000,died:false,unit:{id:1,type:'tank'}},
    {id:'H',type:'STAGE3_BARRAGE',scoreable:true,D_hp:500,D_sh:0,N:4,T_ms:0,
      HP_max:500,Shield_max:0,cost:1000,destroyed:true,unit:{id:2,type:'turret'}},
    {id:'G1',type:'STAGE3_GRINDER',scoreable:true,t_start:40000,zoneId:7,zoneBirthMs:0,weight:1},
    {id:'G2',type:'STAGE3_GRINDER',scoreable:true,t_start:45000,zoneId:7,zoneBirthMs:0,weight:10},
    {id:'G3',type:'STAGE3_GRINDER',scoreable:true,t_start:45001,zoneId:7,zoneBirthMs:0,weight:1},
  ];
  const score=scoreEvents(events,{durationMs:1200000});
  assert.equal(score.breakdown[0].S,.675);
  assert.equal(score.breakdown[1].S,1);
  assert.equal(score.breakdown[2].items.length,2); // 45.001s is outside the first 5s anchor window.
  assert.equal(score.breakdown[2].items[0].weight,11);
  assert.equal(score.breakdown[2].items[0].points,DEFAULTS.grinder.SingleMax);
  assert.equal(score.breakdown[2].items[1].points,DEFAULTS.grinder.SingleMax*.1);
  assert.equal(score.breakdown[2].cap,DEFAULTS.grinder.Cap);
  assert.equal(score.calibration.provisional,true);
  assert.ok(score.total>=0&&score.total<=100);
});

test('duration normalization is clipped for short and long matches',()=>{
  const base={id:'A',type:'STAGE3_AMBUSH',scoreable:true,D_hp:100,D_sh:0,N:8,T_ms:30000,
    HP_max:100,Shield_max:0,cost:1000,died:true,unit:{id:1,type:'tank'}};
  assert.equal(scoreEvents([base],{durationMs:1000}).breakdown[0].durationScale,.5);
  assert.equal(scoreEvents([base],{durationMs:9999999}).breakdown[0].durationScale,2);
});

test('funds v2 only looks at the first windowFraction of the scored window',()=>{
  // 100 s of economy at a constant 100/s; funds start low, then hoard hard in the last fifth.
  const economy=Array.from({length:101},(_,second)=>({second,funds:second<60?0:second<80?4000:90000,
    incomePerSecond:100}));
  const events=[];
  const summary={durationMs:100000,complete:true};
  const full=scoreEvents(events,summary,{funds:{windowFraction:1}},economy,{windowMs:100000});
  const fourFifths=scoreEvents(events,summary,{funds:{windowFraction:0.8}},economy,{windowMs:100000});
  const fullFunds=full.breakdown.find(row=>row.family==='STAGE3_FUNDS');
  const slicedFunds=fourFifths.breakdown.find(row=>row.family==='STAGE3_FUNDS');
  assert.equal(fullFunds.diagnostics.windowFraction,1);
  assert.equal(slicedFunds.diagnostics.windowFraction,0.8);
  assert.equal(slicedFunds.diagnostics.scoredSeconds,80);
  // The late hoarding burst is outside the retained window, so it cannot be scored anymore.
  assert.ok(slicedFunds.deduction<=fullFunds.deduction);
  assert.ok(slicedFunds.diagnostics.maximumDurationSeconds<=fullFunds.diagnostics.maximumDurationSeconds);
});

test('funds v2 reads the median and income windows from the ledger',()=>{
  const sample=(funds,second,incomePerSecond=10)=>({second,funds,incomePerSecond});
  const fundsOf=score=>score.breakdown.find(row=>row.family==='STAGE3_FUNDS');

  // A one-second spike is a real interval with a 1-sample median and invisible with a 5-sample one.
  const spike=[0,0,0,1000,0,0,0,0,0,0].map((funds,second)=>sample(funds,second,1));
  const wide=fundsOf(scoreEvents([],{durationMs:10000,complete:true},
    {funds:{windowFraction:1,warmupSeconds:0,medianWindowSeconds:5}},spike));
  const narrow=fundsOf(scoreEvents([],{durationMs:10000,complete:true},
    {funds:{windowFraction:1,excludeEdgeIntervals:false,warmupSeconds:0,medianWindowSeconds:1}},spike));
  assert.equal(wide.items.length,0,'a 5-sample median smooths the spike away');
  assert.ok(narrow.items.length>0,'a 1-sample median keeps it');

  // Income drops from 10/s to 1/s at second 20. The 30 s average keeps theta above the balance, so
  // nothing is flagged; the 1 s window drops theta to 30 and the 100 credit balance is hoarding.
  const drop=[...Array.from({length:20},(_,i)=>sample(100,i,10)),
    ...Array.from({length:5},(_,i)=>sample(100,20+i,1)),
    ...Array.from({length:6},(_,i)=>sample(0,25+i,1))];
  const long=fundsOf(scoreEvents([],{durationMs:31000,complete:true},
    {funds:{windowFraction:1,incomeWindowSeconds:30,warmupSeconds:0,medianWindowSeconds:1}},drop));
  const short=fundsOf(scoreEvents([],{durationMs:31000,complete:true},
    {funds:{windowFraction:1,incomeWindowSeconds:1,warmupSeconds:0,medianWindowSeconds:1}},drop));
  assert.equal(long.items.length,0,'theta stays above the balance while the 30 s average is high');
  assert.ok(short.items.length>0,'with a 1 s window theta collapses and the balance counts as hoarding');
});

test('funds v2 does not open an interval during the warm-up',()=>{
  const sample=(funds,second)=>({second,funds,incomePerSecond:56});
  // 4000 credits held while income is still being averaged: theta ~= 1688, so without a warm-up the
  // opening balance alone opens an interval. With a 30 s warm-up the balance drops first.
  const rows=[...Array.from({length:20},(_,i)=>sample(4000,i)),
    ...Array.from({length:20},(_,i)=>sample(0,20+i))];
  const fundsOf=score=>score.breakdown.find(row=>row.family==='STAGE3_FUNDS');
  const open=fundsOf(scoreEvents([],{durationMs:40000,complete:true},
    {funds:{windowFraction:1,warmupSeconds:0,excludeEdgeIntervals:false,medianWindowSeconds:1}},rows));
  const warm=fundsOf(scoreEvents([],{durationMs:40000,complete:true},
    {funds:{windowFraction:1,warmupSeconds:30,excludeEdgeIntervals:false,medianWindowSeconds:1}},rows));
  assert.equal(open.items.length,1,'without a warm-up the opening balance opens an interval');
  assert.equal(open.items[0].t_start,0);
  assert.equal(warm.items.length,0,'the balance is gone before the warm-up ends');
  // A player who stays over theta past the warm-up is scored from second 30, not from second 0.
  const long=[...Array.from({length:100},(_,i)=>sample(4000,i))];
  const late=fundsOf(scoreEvents([],{durationMs:100000,complete:true},
    {funds:{windowFraction:1,warmupSeconds:30,excludeEdgeIntervals:false,medianWindowSeconds:1}},long));
  assert.equal(late.items.length,1);
  assert.equal(late.items[0].t_start,30000);
  assert.ok(late.items[0].durationSeconds<=70&&late.items[0].durationSeconds>=69);
});
