import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'
const source=readFileSync(new URL('../desktop/plugin.js',import.meta.url),'utf8')
function api(){
 const imports={}
 for(const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g))for(const n of m[1].split(',').map(s=>s.trim()).filter(Boolean))imports[n]=n
 const code=source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g,'').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m,'').replace(/export default /g,'const pluginDefinition = ').replace(/^export\s+/gm,'')
 return new Function(...Object.keys(imports),code+'\nreturn {runInitialSetup,initialSetupEligible,cancelProfilePreparation,acknowledgeProfilePreparation}')( ...Object.values(imports))
}
const id=c=>c.repeat(64)
function ready(state='ready'){return {schema:1,state,files:state==='missing'?'missing':'complete',python:state==='ready'?'enabled':'not_enabled',base_supported:state!=='missing',split_supported:state!=='missing',explicit_opt_out:false,managed_selection:false,version:state==='missing'?null:'0.6.0',identity:id(state==='missing'?'b':'a'),reason_codes:[]}}
function fixture(){return {revision:0,readiness_context:{schema:1,base_identity:id('a'),source_profile:'default',release:{catalog_name:'model-router',version:'0.6.0',ref:'b'.repeat(40)}},profiles:['default','p1','p2'].map((name,i)=>({name,readiness:ready(i===2?'missing':'ready'),native_delegation:{backend:i===0?'model-router':'default'},initial_setup:{schema:1,default_backend:'model-router-auto',action:i===0?'complete':i===2?'install':'select_backend',eligible:i!==0,backend_unset:i!==0,digest:id(['d','e','f'][i]),intent_digest:id(['a','b','c'][i]),reason_codes:[]}}))}}
function environment(options={}){
 const module=api(),snapshot=fixture(),current=structuredClone(snapshot),writes=[],calls=[],plans=new Map(),values=new Map()
 const storage=options.storage||{get:(k,d=null)=>values.has(k)?structuredClone(values.get(k)):d,set:(k,v)=>values.set(k,structuredClone(v))}
 if(options.enable){snapshot.profiles[1].initial_setup.action='enable';snapshot.profiles[1].readiness=ready('disabled');current.profiles[1]=structuredClone(snapshot.profiles[1])}
 const routes=['default','p1','p2'].map(profile=>({mode:'local',connectionId:'local',profile,targetProfile:profile,primary:profile==='default'}))
 let live=true,planCounter=0
 const transport={profileRoutes:async()=>routes,requestProfile:async(route,method,args)=>{
  assert.equal(route.profile,args.profile);calls.push({method,args,profile:route.profile})
  if(method==='plugins.catalog.lookup')return {status:'found',entry:{name:'model-router',repo:'https://github.com/metamindedu/hermes-model-router',sha:'b'.repeat(40),version:options.staleVersion?'0.4.9':'0.6.0',subdir:''}}
  if(method==='plugins.manage'){
   writes.push({method,args,profile:route.profile})
   const row=current.profiles.find(x=>x.name===route.profile);row.readiness=ready();row.initial_setup.action='select_backend';row.initial_setup.digest=id('1')
   if(options.cancelAfterInstall)live=false
   return {ok:true}
  }
  const operation=args.argv[args.argv.indexOf('model-router')+1],body=JSON.parse(args.argv.at(-1))
  let result
  if(operation==='status') result=structuredClone(current)
  else if(operation==='initial-setup-preview'){
   assert.deepEqual(Object.keys(body).sort(),['expected_revision','expected_root_identity','updates'].sort())
   assert.equal(body.expected_root_identity,current.readiness_context.base_identity)
   const profile=body.updates[0].profile,plan_id=String(++planCounter).repeat(32)
   plans.set(plan_id,profile);result={plan_id,default_backend:'model-router-auto',changes:[{profile,field:'delegation.backend',before:null,after:'model-router-auto'}]}
   if(options.legacyPlan){delete result.default_backend;result.changes[0].after='model-router'}
   if(options.cancelDuringPreview)live=false
  } else if(operation==='apply'){
   writes.push({method,operation,body,profile:route.profile})
   if(options.unknownApply)throw new Error('unknown write')
   const profile=plans.get(body.plan_id),row=current.profiles.find(x=>x.name===profile)
   row.initial_setup.action='complete';row.initial_setup.eligible=false;row.initial_setup.backend_unset=false;row.native_delegation.backend='model-router-auto'
   result={status:'applied',plan_id:body.plan_id,applied:[{profile,key:'delegation.backend'}],remaining:[]}
  }else throw new Error(operation)
  return {code:0,output:'MODEL_ROUTER_JSON:'+JSON.stringify(result)}
 }}
 const run=selected=>module.runInitialSetup({transport,snapshot,selected,scopeKey:'owned',connectionId:'local',activeProfile:'default',storage,isCurrent:()=>live})
 return {module,snapshot,current,writes,calls,storage,run,values}
}
test('initial setup uses backend-only scope without installation when code is ready',async()=>{
 const e=environment(),r=await e.run(['p1'])
 assert.equal(r.unknown,false);assert.equal(r.changed,true);assert.equal(r.outcomes[0].state,'complete')
 assert.equal(e.writes.length,1);assert.equal(e.writes[0].operation,'apply')
 assert.equal(e.calls.some(x=>x.method==='plugins.catalog.lookup'),false)
 assert.equal(e.storage.get('profile-preparation-safety-v1').pending.settled,true)
})
test('initial setup installs exact target then selects backend through the source',async()=>{
 const e=environment(),r=await e.run(['p2'])
 assert.equal(r.outcomes[0].state,'complete');assert.equal(e.writes.length,2)
 assert.equal(e.writes[0].args.action,'install');assert.equal(e.writes[0].profile,'p2');assert.equal(e.writes[0].args.force,false)
 assert.equal(e.writes[1].profile,'default');assert.equal(e.current.profiles[2].native_delegation.backend,'model-router-auto')
})
test('initial setup enables a verified disabled target without reinstalling it',async()=>{
 const e=environment({enable:true}),r=await e.run(['p1'])
 assert.equal(r.outcomes[0].state,'complete');assert.equal(e.writes[0].args.action,'toggle');assert.equal(e.writes[0].profile,'p1')
})
test('initial setup refuses stale catalog version before native mutation',async()=>{
 const e=environment({staleVersion:true}),r=await e.run(['p2'])
 assert.equal(r.manualRequired,true);assert.equal(r.unknown,false);assert.deepEqual(e.writes,[])
})
test('initial setup cancelled after install does not select backend or continue',async()=>{
 const e=environment({cancelAfterInstall:true}),r=await e.run(['p2','p1'])
 assert.equal(r.cancelled,true);assert.equal(e.writes.length,1);assert.equal(e.writes[0].args.action,'install')
 assert.equal(r.outcomes[1].state,'not_started');assert.equal(e.current.profiles[2].native_delegation.backend,'default')
})
test('initial setup cancelled in preview cannot apply',async()=>{
 const e=environment({cancelDuringPreview:true}),r=await e.run(['p1'])
 assert.equal(r.cancelled,true);assert.deepEqual(e.writes,[])
})
test('initial setup unknown apply remains blocked across new module instances',async()=>{
 const e=environment({unknownApply:true}),r=await e.run(['p1'])
 assert.equal(r.unknown,true);assert.equal(e.storage.get('profile-preparation-safety-v1').pending.phase,'backend')
 const next=environment({storage:e.storage})
 await assert.rejects(()=>next.run(['p1']))
 assert.deepEqual(next.writes,[])
 assert.equal(next.module.acknowledgeProfilePreparation(e.storage,id('a'),'wrong-owner',true),false)
})
test('initial setup unavailable storage cannot issue mutation',async()=>{
 const e=environment({storage:{get:()=>null,set:()=>{throw new Error('denied')}}}),r=await e.run(['p1'])
 assert.equal(r.manualRequired,true);assert.deepEqual(e.writes,[])
})
test('initial setup unknown or protected DTO is not eligible',()=>{
 const e=environment(),row=e.snapshot.profiles[1],safe={pending:null,blocked:[]}
 assert.equal(e.module.initialSetupEligible(row,safe,id('a')),true)
 row.initial_setup.eligible=false;assert.equal(e.module.initialSetupEligible(row,safe,id('a')),false)
 assert.equal(e.module.initialSetupEligible({name:'p1'},safe,id('a')),false)
})

test('old setup DTO without the declared auto default refuses before any request',async()=>{
 const e=environment()
 for(const row of e.snapshot.profiles)delete row.initial_setup.default_backend
 await assert.rejects(()=>e.run(['p1']))
 assert.deepEqual(e.calls,[]);assert.deepEqual(e.writes,[])
})
test('old-default plan is never applied by the new setup UI',async()=>{
 const e=environment({legacyPlan:true}),r=await e.run(['p1'])
 assert.equal(r.manualRequired,true);assert.equal(r.unknown,false)
 assert.deepEqual(e.writes,[])
})
