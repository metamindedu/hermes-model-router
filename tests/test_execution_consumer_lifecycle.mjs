// Real contributed consumers + real React/Query; DOM, host and RPC are inert.
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import path from 'node:path'
import test from 'node:test'

const core=process.env.HERMES_DESKTOP_SOURCE_ROOT
const source=readFileSync(new URL('../desktop/plugin.js',import.meta.url),'utf8')
async function harness(){
 const require=createRequire(path.join(core,'apps/desktop/package.json'))
 const {JSDOM}=require('jsdom')
 const dom=new JSDOM('<!doctype html><div id="root"></div>',{url:'http://fixture.invalid/'})
 globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.IS_REACT_ACT_ENVIRONMENT=true
 const React=require('react'),{createRoot}=require('react-dom/client')
 const {jsx,jsxs}=require('react/jsx-runtime'),{QueryClient,QueryClientProvider,useQuery}=require('@tanstack/react-query')
 const atom=value=>{const listeners=new Set();return {get:()=>value,set(next){value=next;for(const fn of [...listeners])fn()},listen(fn){listeners.add(fn);return()=>listeners.delete(fn)},size:()=>listeners.size}}
 const client=new QueryClient({defaultOptions:{queries:{refetchOnWindowFocus:false,staleTime:60000}}})
 const state=Object.fromEntries(Object.entries({focusedSessionOwner:{connectionId:'local',profile:'observer'},focusedSessionId:'parent-0',connectionId:'local',profile:'observer',gateway:'open',activeSessionId:'parent-0'}).map(([key,value])=>[key,atom(value)]))
 const f={epoch:1,calls:[],forbidden:0,rows:32,hold:false,release:null,cleanups:[]},gatewayListeners=new Set()
 const gateway={connectionState:'open',sessionWire:'canonical',onState(fn){gatewayListeners.add(fn);fn('open');return()=>gatewayListeners.delete(fn)},async request(method,params){
  f.calls.push(method);assert.equal(params.profile,'observer');const parent=params.session_id
  if(method==='plugin.model-router.execution.list'){
   const result={schema:1,origin_profile:'observer',conversation_id:parent,rows:Array.from({length:f.rows},(_,i)=>({id:parent+':'+i,execution_mode:'native',conversation_id:parent,parent_session_id:parent,task_index:i,subagent_id:'sa-'+i,delegation_id:'unit-'+parent,async_unit_id:'unit-'+parent,native_call_delegation_id:'call-'+parent,status:'queued',requested:{kind:'model',profile:null,slot:'design'},observed:{kind:'unknown'}}))}
   return f.hold?new Promise(resolve=>{f.release=()=>resolve(result)}):result
  }
  if(method==='subagent.list')return {subagents:[]}
  if(method==='plugin.model-router.profile_jobs.list')return {schema:1,origin_profile:'observer',parent_session_id:parent,jobs:[]}
  if(method==='plugin.model-router.profile_jobs.describe')return {schema:1,supported:true,origin_profile:'observer',revision:'a'.repeat(64),policy:{schema:1,enabled:false,targets:[]},targets:[]}
  if(method==='session.events.since'){
   const epoch='epoch-'+parent,bootstrap=params.replay_epoch!==epoch
   const events=bootstrap||params.last_sequence>=1?[]:[{seq:1,session_id:parent,replay_epoch:epoch,type:'subagent.complete',payload:{delegation_id:'call-'+parent,subagent_id:'sa-0',task_index:0,status:'completed',summary:'PRIVATE_CONSUMER_CANARY'}}]
   return {replay_epoch:epoch,epoch,events,latest_seq:1,last_sequence:1,count:events.length,truncated:bootstrap,snapshot_required:bootstrap,open_requests:[{text:'PRIVATE_CONSUMER_CANARY'}]}
  }
  throw Error('unexpected observer method')
 }}
 const deny=()=>{f.forbidden++;throw Error('forbidden resolver/control')}
 const host={state,getGateway:()=>gateway,onEvent:()=>()=>{},profileRoutes:deny,requestProfile:deny,request:deny,retainProfile:deny}
 const sdk={atom,queryClient:client,gatewayActivationEpoch:()=>f.epoch,COMPOSER_AREAS:{top:'composer.top'}}
 const imports={}
 for(const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g))for(const name of m[1].split(',').map(value=>value.trim()).filter(Boolean))imports[name]=()=>null
 Object.assign(imports,{DesktopSDK:sdk,host,jsx,jsxs,useQuery,useValue:a=>React.useSyncExternalStore(a.listen,a.get,a.get),useState:React.useState,useRef:React.useRef,useEffect:React.useEffect})
 const code=source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g,'').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m,'').replace(/export default /g,'const pluginDefinition = ').replace(/^export\s+/gm,'')
 const api=new Function(...Object.keys(imports),code+'\nreturn {pluginDefinition};')(...Object.values(imports))
 const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms))
 f.act=fn=>React.act(fn);f.tick=()=>React.act(async()=>{await sleep(10)})
 f.queries=kind=>client.getQueryCache().getAll().filter(query=>query.queryKey[0]==='model-router'&&query.queryKey[1]===kind)
 f.mount=async()=>{
  const disposers=[],contributions=[]
  api.pluginDefinition.register({onDispose:fn=>disposers.push(fn),registerSettingsPage:()=>{},registerMany:items=>contributions.push(...items)})
  const root=createRoot(document.getElementById('root'))
  let closed=false
  const close=async()=>{if(closed)return;closed=true;await React.act(async()=>{for(const fn of disposers)fn();root.unmount()})}
  f.cleanups.push(close)
  await React.act(async()=>root.render(jsx(QueryClientProvider,{client,children:jsxs(React.Fragment,{children:[contributions.find(value=>value.id==='execution-composer').render(),]})})))
  return {close}
 }
 f.settle=async(parent,count=f.rows)=>{
  for(let i=0;i<100;i++){
   await f.tick()
   if(f.queries('execution-active').some(query=>query.state.data?.scope_key===JSON.stringify(['local','observer',parent])&&query.state.data?.rows?.length===count))return
  }
  throw Error('actual consumers did not settle')
 }
 f.client=client;f.state=state;f.visible=()=>document.querySelectorAll('[data-execution-row]').length
 f.listeners=()=>Object.values(state).reduce((count,value)=>count+value.size(),0)+gatewayListeners.size
 f.close=async()=>{if(f.release)f.release();for(const close of f.cleanups)await close();client.clear();dom.window.close()}
 return f
}

test('real consumers retire obsolete DTOs on churn and disposal without clearing unrelated caches',{skip:!core},async()=>{
 const f=await harness()
 try{
  f.client.setQueryData(['unrelated-app-query'],{preserve:true})
  const instance=await f.mount();await f.settle('parent-0')
  for(let i=1;i<20;i++){
   await f.act(async()=>{f.state.focusedSessionId.set('parent-'+i);f.state.activeSessionId.set('parent-'+i)})
   await f.settle('parent-'+i)
   assert.ok(f.queries('execution-active').length<=1);assert.ok(f.queries('profile-jobs-policy-active').length<=1)
  }
  assert.equal(f.queries('execution-active').reduce((count,query)=>count+query.state.data.rows.length,0),32)
  const retained={snapshots:f.queries('execution-active').length,policies:f.queries('profile-jobs-policy-active').length,rows:32}
  // Only the composer strip remains (no layout pane), and it issues no profile-job policy reads.
  assert.equal(f.visible(),32);assert.equal(retained.policies,0);assert.doesNotMatch(JSON.stringify(f.client.getQueryCache().getAll().map(query=>query.state.data)),/PRIVATE_CONSUMER_CANARY/)
  await instance.close();await f.tick()
  assert.equal(f.queries('execution-active').length,0);assert.equal(f.queries('profile-jobs-policy-active').length,0)
  assert.equal(f.listeners(),0);assert.equal(f.forbidden,0)
  assert.deepEqual(f.client.getQueryData(['unrelated-app-query']),{preserve:true})
  console.log(JSON.stringify({proof:'owned_consumer_retention',churnScopes:20,retained,afterDispose:{snapshots:f.queries('execution-active').length,policies:f.queries('profile-jobs-policy-active').length,listeners:f.listeners()},unrelatedPreserved:true}))
 }finally{await f.close()}
})
test('rapid real plugin reload cannot reuse old lifetime DTOs, including invalidated/pending reads',{skip:!core},async()=>{
 const f=await harness()
 try{
  for(const invalidate of [false,true]){
   f.rows=32;f.hold=false
   const first=await f.mount();await f.settle('parent-0')
   const oldQuery=f.queries('execution-active')[0],oldKey=oldQuery.queryKey,oldData=oldQuery.state.data
   await first.close();f.epoch++;f.rows=0;f.hold=true;f.release=null
   // Retain a stale-cache copy deliberately, independent of cleanup correctness.
   f.client.setQueryData(oldKey,oldData)
   if(invalidate)await f.client.invalidateQueries()
   const second=await f.mount();await f.tick()
   assert.equal(f.visible(),0,'no pre-epoch cards while the fresh roster is pending')
   console.log(JSON.stringify({proof:'reload_freshness',nativeInvalidation:invalidate,staleVisibleArticles:f.visible(),newRosterPending:typeof f.release==='function'}))
   assert.equal(typeof f.release,'function','new observer must issue fresh own reads')
   assert.equal(f.forbidden,0)
   await f.act(async()=>{f.release();f.hold=false});await f.settle('parent-0',0)
   const current=f.queries('execution-active').find(query=>query.state.data?.rows.length===0)
   assert.notDeepEqual(current.queryKey,oldKey)
   assert.notEqual(current.state.data.observation_lifetime,oldData.observation_lifetime)
   assert.equal(current.state.data.observation_epoch,f.epoch)
   await second.close();f.client.removeQueries({queryKey:oldKey,exact:true})
  }
 }finally{await f.close()}
})
