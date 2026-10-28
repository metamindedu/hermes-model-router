import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'
const source=readFileSync(new URL('../desktop/plugin.js',import.meta.url),'utf8')
function api(){
 const names=[]
 for(const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g))for(const n of m[1].split(',').map(s=>s.trim()).filter(Boolean))names.push(n)
 const code=source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g,'').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m,'').replace(/export default /g,'const pluginDefinition = ').replace(/^export\s+/gm,'')
 return new Function('DesktopSDK',...names,code+'\nreturn {profileRoleView,editProfileRoleDescription,buildNativeDelegationBatchBody,createRoleProposalController}')( {},...names.map(n=>n))
}
const id=x=>x.repeat(64)
const intro=(text='웹앱 구현',state='available')=>({schema:1,state,default_description:text,default_source:state==='available'?'profile_metadata':'none',description_auto:false,digest:id('b')})
test('native intro is display-only, overrides remain exact including whitespace',()=>{
 const a=api();assert.deepEqual(a.profileRoleView({role_intro:intro()},{description:''}).source,'profile_metadata')
 assert.equal(a.profileRoleView({role_intro:intro()},{description:' custom '}).description,' custom ')
 assert.equal(a.profileRoleView({role_intro:intro()},{description:' '}).source,'override')
 assert.equal(a.profileRoleView({role_intro:intro('','missing')},{description:''}).source,'unknown')
 assert.equal(a.profileRoleView({}, {description:''}).description,'')
})
test('editing role only records a local draft intent and never copies native intro',()=>{
 const a=api(),draft={backend:'model-router-auto',allowProfileAccess:false,profile_routes:{profiles:[{name:'p1',description:''}],default:null},descriptionEdits:{}}
 const changed=a.editProfileRoleDescription(draft,'p1','new');assert.equal(draft.profile_routes.profiles[0].description,'')
 assert.equal(changed.profile_routes.profiles[0].description,'new');assert.equal(changed.descriptionEdits.p1,true)
 const cleared=a.editProfileRoleDescription(changed,'p1','');assert.equal(cleared.profile_routes.profiles[0].description,'');assert.equal(cleared.allowProfileAccess,false)
})
function context(){return{schema:1,owner:{profile:'owner',base_identity:id('a')},target_profile:'target',capability:{available:true,reason_code:null},source:{digest:id('b'),native_description:'evidence',soul_role_excerpt:'',enabled_skill_names:[],omitted_sources:[],truncated:false},payer:{profile:'owner',basis:'owner_saved_main',provider:'fixture',model:'saved',fallback_policy:[],native_recovery:'host_managed',route_digest:id('c'),estimate_usd:null},limits:{input_bytes:8192,max_output_tokens:512,request_timeout_seconds:30}}}
function env(){
 const a=api();let live={connectionId:'local',ownerProfile:'owner',scopeKey:'local|owner',baseIdentity:id('a'),template:'template',draft:'initial',blocked:false},view=null,used=[],calls=[],next=null
 const routes=[{mode:'local',connectionId:'local',profile:'owner',targetProfile:'owner',primary:true}]
 const transport={profileRoutes:async()=>routes,requestProfile:async(route,method,args)=>{
  calls.push({route,method,args});assert.equal(route.profile,'owner');assert.equal(args.profile,'owner');assert.equal(args.argv[1],'owner')
  if(next)return next(route,method,args)
  const op=args.argv[3];let d=context()
  if(op==='role-proposal')d={schema:1,status:'proposed',owner:d.owner,target_profile:'target',source_digest:id('b'),route_digest:id('c'),proposal:{description:'proposed role'},stale:false,model_attribution:{provider_verified:false},usage:{}}
  return{code:0,output:'MODEL_ROUTER_JSON:'+JSON.stringify(d)}
 }}
 const c=a.createRoleProposalController({transport,readState:()=>live,onUpdate:v=>{view=v},onUse:(name,text)=>used.push({name,text})})
 return{c,calls,used,routes,get view(){return view},change:v=>{live={...live,...v}},reply:fn=>{next=fn}}
}
test('context costs no generation; explicit generate and accept are draft-only and owner-pinned',async()=>{
 const e=env();await e.c.open('target');assert.equal(e.calls.length,1);assert.equal(e.view.phase,'review');assert.deepEqual(e.used,[])
 await e.c.generate();assert.equal(e.calls.length,2);assert.equal(e.view.phase,'proposed');assert.deepEqual(e.used,[])
 const sent=JSON.parse(e.calls[1].args.argv.at(-1));assert.deepEqual(sent.consent,{send_reviewed_sources:true,use_owner_native_policy:true});assert.equal(sent.owner_profile,'owner');assert.equal(sent.target_profile,'target')
 await e.c.use();assert.deepEqual(e.used,[{name:'target',text:'proposed role'}]);assert.equal(e.calls.length,3);assert.equal(e.calls[2].args.argv[3],'role-proposal-context')
 assert.equal(e.calls.some(c=>c.args.argv.includes('apply')),false)
})
test('manual edit and leave/return invalidate old results, cancel never retries',async()=>{
 const e=env();await e.c.open('target');e.change({draft:'edited'});await e.c.generate();assert.equal(e.calls.length,1);assert.deepEqual(e.used,[])
 const f=env();await f.c.open('target');f.c.cancel();await f.c.generate();assert.equal(f.calls.length,1);assert.deepEqual(f.used,[])
 const g=env();await g.c.open('target');g.c.invalidate();g.change({scopeKey:'different'});g.c.invalidate();g.change({scopeKey:'local|owner'});await g.c.generate();assert.equal(g.calls.length,1)
})
test('duplicate native sentinel and ambiguous owner refuse safely',async()=>{
 const e=env();e.reply(()=>({code:0,output:'MODEL_ROUTER_JSON:'+JSON.stringify(context())+'\nMODEL_ROUTER_JSON:'+JSON.stringify(context())}));await e.c.open('target');assert.equal(e.view.phase,'error');assert.deepEqual(e.used,[])
 const f=env();f.routes.push({...f.routes[0]});await f.c.open('target');assert.equal(f.calls.length,0);assert.equal(f.view.phase,'error')
})
test('disposed or cancelled callback cannot apply and duplicate generate is single-issued',async()=>{
 const e=env();await e.c.open('target');let resolve;e.reply(()=>new Promise(r=>{resolve=r}));const pending=e.c.generate();await Promise.resolve();await Promise.resolve();const second=e.c.generate();await second;assert.equal(e.calls.length,2)
 e.c.dispose();resolve({code:0,output:'MODEL_ROUTER_JSON:'+JSON.stringify({schema:1,status:'proposed',owner:context().owner,target_profile:'target',source_digest:id('b'),route_digest:id('c'),proposal:{description:'late'},stale:false})});await pending;assert.deepEqual(e.used,[])
})
test('source or payer change before Use cannot overwrite draft',async()=>{
 const e=env();await e.c.open('target');await e.c.generate();e.reply(()=>({code:0,output:'MODEL_ROUTER_JSON:'+JSON.stringify({...context(),source:{...context().source,digest:id('d')}})}));await e.c.use();assert.deepEqual(e.used,[]);assert.equal(e.view.phase,'error')
})
