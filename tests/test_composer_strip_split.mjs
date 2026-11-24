// Real contributed composer strips + real React/Query over an inert host: in a split view each composer
// shows its own chat. The primary composer needs the host-reported owner proof; the ambient socket
// never supplies one. Adapted from the independent review's probe.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import test from 'node:test'

const core=process.env.HERMES_DESKTOP_SOURCE_ROOT
const source=readFileSync(new URL('../desktop/plugin.js', import.meta.url),'utf8')

async function harness(opts={}){
 const require=createRequire(path.join(core,'apps/desktop/package.json'))
 const {JSDOM}=require('jsdom')
 const dom=new JSDOM('<!doctype html><div id="primary"></div><div id="tile"></div>',{url:'http://fixture.invalid/'})
 globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.IS_REACT_ACT_ENVIRONMENT=true
 const React=require('react'),{createRoot}=require('react-dom/client')
 const {jsx,jsxs}=require('react/jsx-runtime'),{QueryClient,QueryClientProvider,useQuery}=require('@tanstack/react-query')
 const atom=value=>{const listeners=new Set();return {get:()=>value,set(next){value=next;for(const fn of [...listeners])fn()},listen(fn){listeners.add(fn);return()=>listeners.delete(fn)}}}
 const client=new QueryClient({defaultOptions:{queries:{refetchOnWindowFocus:false,staleTime:60000}}})
 // Split view: primary pane = A (runtime ra), focused tile = B (runtime rb). Socket: local/claire.
 const state=Object.fromEntries(Object.entries({focusedSessionOwner:{connectionId:'local',profile:'claire'},focusedStoredSessionId:'B',focusedSessionId:'rb',
   connectionId:'local',profile:'claire',gateway:'open',activeSessionId:'ra',...(opts.state||{})}).map(([k,v])=>[k,atom(v)]))
 const f={calls:[],controlCalls:[],refuse:new Set(opts.refuse||[])}
 const transportListeners=new Set()
 const gateway={connectionState:'open',sessionWire:'canonical',onState(fn){transportListeners.add(fn);fn(this.connectionState);return()=>transportListeners.delete(fn)},async request(method,params){
  f.calls.push({method,session:params.session_id,profile:params.profile});const parent=params.session_id
  if(f.refuse.has(parent))throw Error('session_not_found')
  if(method==='plugin.model-router.execution.list')return {schema:1,origin_profile:'claire',conversation_id:parent,rows:[{id:parent+':0',execution_mode:'native',conversation_id:parent,parent_session_id:parent,task_index:0,subagent_id:'sa-'+parent,delegation_id:'unit-'+parent,async_unit_id:'unit-'+parent,native_call_delegation_id:'call-'+parent,status:'running',model:'MODEL-OF-'+parent,requested:{kind:'model',role:'heavy'},observed:{kind:'unknown'}}]}
  if(method==='subagent.list')return {subagents:[]}
  if(method==='plugin.model-router.profile_jobs.list'&&opts.noJobs)return {schema:1,origin_profile:'claire',parent_session_id:parent,jobs:[]}
  if(method==='plugin.model-router.profile_jobs.list')return {schema:1,origin_profile:'claire',parent_session_id:parent,jobs:[{id:'job-'+parent,origin_profile:'claire',parent_session_id:parent,target_profile:'wallace',execution_mode:'gateway',status:'running',admission_id:'adm-'+parent,can_steer:true}]}
  if(method==='plugin.model-router.profile_jobs.describe')return {schema:1,supported:true,origin_profile:'claire',revision:'a'.repeat(64),policy:{schema:1,enabled:false,targets:[]},targets:[]}
  if(method==='session.events.since'){const epoch='epoch-'+parent;return {replay_epoch:epoch,epoch,events:[],latest_seq:0,last_sequence:0,count:0,truncated:false,snapshot_required:false}}
  throw Error('unexpected observer method')
 }}
 const host={state,getGateway:()=>gateway,onEvent:()=>()=>{},
  profileRoutes:async()=>[{connectionId:'local',mode:'local',profile:'claire',targetProfile:'claire'}],
  requestProfile:async(route,method,params)=>{f.controlCalls.push({method,session:params.session_id,job:params.job_id,operation:params.operation});return {schema:1,origin_profile:'claire',status:'ok',job:{id:params.job_id,origin_profile:'claire'}}}}
 const Session=React.createContext({sessionId:null,storedSessionId:null})
 const created=[]
 const countedAtom=value=>{const listeners=new Set();const a={get:()=>value,set(next){value=next;for(const fn of [...listeners])fn()},listen(fn){listeners.add(fn);return()=>listeners.delete(fn)},count:()=>listeners.size};created.push(a);return a}
 const sdk={atom:countedAtom,queryClient:client,gatewayActivationEpoch:()=>1,COMPOSER_AREAS:{top:'composer.top'},useComposerSession:()=>React.useContext(Session)}
 const imports={}
 for(const m of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g))for(const name of m[1].split(',').map(v=>v.trim()).filter(Boolean))imports[name]=()=>null
 Object.assign(imports,{DesktopSDK:sdk,host,jsx,jsxs,useQuery,useValue:a=>React.useSyncExternalStore(a.listen,a.get,a.get),useState:React.useState,useRef:React.useRef,useEffect:React.useEffect,
  Button:p=>jsx('button',{onClick:p.onClick,disabled:p.disabled,children:p.children}),Input:p=>jsx('input',{value:p.value,onChange:p.onChange,disabled:p.disabled})})
 const code=source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g,'').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m,'').replace(/export default /g,'const pluginDefinition = ').replace(/^export\s+/gm,'')
 const api=new Function(...Object.keys(imports),code+'\nreturn {pluginDefinition};')(...Object.values(imports))
 const disposers=[],contributions=[]
 api.pluginDefinition.register({onDispose:fn=>disposers.push(fn),registerSettingsPage:()=>{},registerMany:items=>contributions.push(...items),storage:{get:(k,d)=>d,set(){}}})
 const strip=contributions.find(v=>v.id==='execution-composer')
 const roots={}
 const sleep=ms=>new Promise(r=>setTimeout(r,ms))
 f.mount=async(id,session)=>{roots[id]=createRoot(document.getElementById(id))
  await React.act(async()=>roots[id].render(jsx(QueryClientProvider,{client,children:jsx(Session.Provider,{value:session,children:strip.render()})})))}
 f.revisionListeners=()=>created.reduce((n,a)=>n+a.count(),0)
 f.unmount=async id=>{await React.act(async()=>roots[id].unmount());delete roots[id]}
 f.unmountNow=id=>{roots[id].unmount();delete roots[id]}
 f.update=async(id,session)=>{await React.act(async()=>roots[id].render(jsx(QueryClientProvider,{client,children:jsx(Session.Provider,{value:session,children:strip.render()})})))}
 f.tick=async(n=8)=>{for(let i=0;i<n;i++)await React.act(async()=>{await sleep(10)})}
 f.act=fn=>React.act(fn)
 f.text=id=>document.getElementById(id).textContent
 f.gate=id=>document.getElementById(id).querySelector('[data-model-router-focus-gate]')?.getAttribute('data-model-router-focus-gate')
 f.el=id=>document.getElementById(id)
 f.state=state
 f.transport=value=>{gateway.connectionState=value;for(const fn of [...transportListeners])fn(value)}
 f.pluginVersion=api.pluginDefinition.version
 f.close=async()=>{await React.act(async()=>{for(const fn of disposers)fn();for(const r of Object.values(roots))r.unmount()});client.clear();dom.window.close()}
 return f
}
const models=t=>[...new Set([...t.matchAll(/MODEL-OF-(\w+)/g)].map(m=>m[1]))]
const focusPrimary=f=>f.act(async()=>{f.state.focusedStoredSessionId.set('A');f.state.focusedSessionId.set('ra')})
const focusTile=f=>f.act(async()=>{f.state.focusedStoredSessionId.set('B');f.state.focusedSessionId.set('rb')})

test('split view: after the primary was focused once, each composer shows its own chat', {skip:!core}, async()=>{
  const f=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra'}})
  try{
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await f.tick()
    assert.deepEqual(models(f.text('primary')),['ra']);assert.equal(f.gate('tile'),'hidden')
    await focusTile(f);await f.tick()
    assert.deepEqual(models(f.text('primary')),['ra'],'primary keeps its own chat while the tile is focused')
    assert.deepEqual(models(f.text('tile')),['rb'],'the focused tile shows its own chat')
    assert.ok(f.calls.every(c=>c.profile==='claire'))
    // Primary-mode job lines explain where controls are instead of offering silent buttons.
    const details=f.el('primary').querySelector('details[data-model-router-execution="compact"]')
    await f.act(async()=>{details.open=true;details.dispatchEvent(new window.Event('toggle',{bubbles:false}))});await f.tick(2)
    const buttons=[...f.el('primary').querySelectorAll('button')].map(b=>b.textContent)
    assert.ok(!buttons.includes('상태 확인') && !buttons.includes('중지 요청'),'no job control buttons on a primary-mode strip')
    assert.match(f.text('primary'),/작업 제어는 이 대화를 포커스하면 사용할 수 있습니다/)
    // The primary navigates: its old proof is void, so it hides rather than guess.
    await f.act(async()=>{f.state.activeSessionId.set('rn')});await f.tick()
    assert.deepEqual(models(f.text('primary')),[]);assert.deepEqual(models(f.text('tile')),['rb'])
  }finally{await f.close()}
})

test('split view without an owner proof: the primary stays hidden and is never read', {skip:!core}, async()=>{
  const f=await harness()
  try{
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await f.tick()
    assert.deepEqual(models(f.text('primary')),[]);assert.deepEqual(models(f.text('tile')),['rb'])
    assert.equal(f.calls.filter(c=>c.session==='ra').length,0)
    assert.doesNotMatch(f.text('primary'),/읽을 수 없습니다/)
  }finally{await f.close()}
})

test('split view: a primary owned by another profile is never read through the active socket', {skip:!core}, async()=>{
  const f=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra',focusedSessionOwner:{connectionId:'local',profile:'wallace'}}})
  try{
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await f.tick()
    await focusTile(f);await f.act(async()=>{f.state.focusedSessionOwner.set({connectionId:'local',profile:'claire'})});await f.tick()
    assert.deepEqual(models(f.text('primary')),[]);assert.deepEqual(models(f.text('tile')),['rb'])
    assert.equal(f.calls.filter(c=>c.session==='ra').length,0)
  }finally{await f.close()}
})

test('documented flow: opened under tile focus, then selected once in the sidebar, then the tile again', {skip:!core}, async()=>{
  const f=await harness()
  try{
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await f.tick()
    assert.deepEqual(models(f.text('primary')),[],'no proof yet')
    await focusPrimary(f);await f.tick();await focusTile(f);await f.tick()
    assert.deepEqual(models(f.text('primary')),['ra']);assert.deepEqual(models(f.text('tile')),['rb'])
  }finally{await f.close()}
})

test('a late-resolving owner is recorded; a retracted owner withdraws the proof', {skip:!core}, async()=>{
  const late=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra',focusedSessionOwner:null}})
  try{
    await late.mount('primary',{sessionId:'ra',storedSessionId:'A'});await late.mount('tile',{sessionId:'rb',storedSessionId:'B'});await late.tick()
    await late.act(async()=>{late.state.focusedSessionOwner.set({connectionId:'local',profile:'claire'})});await late.tick()
    await focusTile(late);await late.tick()
    assert.deepEqual(models(late.text('primary')),['ra'],'owner resolved after the ids → recorded')
  }finally{await late.close()}
  const retract=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra'}})
  try{
    await retract.mount('primary',{sessionId:'ra',storedSessionId:'A'});await retract.mount('tile',{sessionId:'rb',storedSessionId:'B'});await retract.tick()
    await retract.act(async()=>{retract.state.focusedSessionOwner.set(null)});await retract.tick()
    await focusTile(retract);await retract.act(async()=>{retract.state.focusedSessionOwner.set({connectionId:'local',profile:'claire'})});await retract.tick()
    const before=retract.calls.filter(c=>c.session==='ra').length;await retract.tick()
    assert.deepEqual(models(retract.text('primary')),[],'the host withdrew the owner → no read under the old proof')
    assert.equal(retract.calls.filter(c=>c.session==='ra').length,before)
  }finally{await retract.close()}
})

test('a transport reset while the primary stays focused re-records the proof', {skip:!core}, async()=>{
  const f=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra'}})
  try{
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await f.tick()
    await f.act(async()=>{f.transport('closed')});await f.tick(2);await f.act(async()=>{f.transport('open')});await f.tick()
    await focusTile(f);await f.tick()
    assert.deepEqual(models(f.text('primary')),['ra'])
  }finally{await f.close()}
  const connecting=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra',gateway:'connecting'}})
  try{
    await connecting.mount('primary',{sessionId:'ra',storedSessionId:'A'});await connecting.mount('tile',{sessionId:'rb',storedSessionId:'B'});await connecting.tick()
    await connecting.act(async()=>{connecting.state.gateway.set('open')});await connecting.tick()
    await focusTile(connecting);await connecting.tick()
    assert.deepEqual(models(connecting.text('primary')),['ra'],'focused while connecting → recorded once open')
  }finally{await connecting.close()}
})

test('primary-mode strip: one job note, no job guide; plugin version matches plugin.yaml', {skip:!core}, async()=>{
  const f=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra'}})
  try{
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await f.tick()
    await focusTile(f);await f.tick()
    for(const id of ['primary','tile']){
      const details=f.el(id).querySelector('details[data-model-router-execution="compact"]')
      await f.act(async()=>{details.open=true;details.dispatchEvent(new window.Event('toggle',{bubbles:false}))});await f.tick(2)
    }
    assert.equal(f.el('primary').querySelectorAll('[data-model-router-job-note]').length,1)
    assert.doesNotMatch(f.text('primary'),/전체 프로필 작업 · 허용 범위와 운영자 안내/,'no profile-job guide on a primary-mode strip')
    assert.match(f.text('tile'),/전체 프로필 작업 · 허용 범위와 운영자 안내/,'the focused tile keeps its guide')
    assert.equal(f.el('tile').querySelectorAll('[data-model-router-job-note]').length,0)
  }finally{await f.close()}
  const yaml=readFileSync(new URL('../plugin.yaml', import.meta.url),'utf8').match(/^version:\s*(\S+)/m)[1]
  assert.equal(f.pluginVersion,yaml)
})

test('a stored id that resolves after mount, with no host atom change, still records the proof', {skip:!core}, async()=>{
  const f=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra'}})
  try{
    // The slot maps runtime to stored id late: first the runtime id stands in for it.
    await f.mount('primary',{sessionId:'ra',storedSessionId:'ra'});await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await f.tick()
    await f.update('primary',{sessionId:'ra',storedSessionId:'A'});await f.tick()
    await focusTile(f);await f.tick()
    assert.deepEqual(models(f.text('primary')),['ra'])
  }finally{await f.close()}
})

test('the primary job note appears only when the strip has a gateway job line', {skip:!core}, async()=>{
  const f=await harness({noJobs:true,state:{focusedStoredSessionId:'A',focusedSessionId:'ra'}})
  try{
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await f.tick()
    await focusTile(f);await f.tick()
    const details=f.el('primary').querySelector('details[data-model-router-execution="compact"]')
    await f.act(async()=>{details.open=true;details.dispatchEvent(new window.Event('toggle',{bubbles:false}))});await f.tick(2)
    assert.deepEqual(models(f.text('primary')),['ra'])
    assert.equal(f.el('primary').querySelectorAll('[data-model-router-job-note]').length,0)
  }finally{await f.close()}
})

test('the gate drops its revision listener on unmount and stays quiet afterwards', {skip:!core}, async()=>{
  const f=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra'}})
  try{
    const before=f.revisionListeners()
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.tick()
    assert.ok(f.revisionListeners()>before,'the focused primary gate listens for revisions')
    await f.unmount('primary');await f.tick()
    assert.equal(f.revisionListeners(),before,'listener removed on unmount')
    // A transport reset after unmount cannot leave a proof behind for a composer that is gone.
    await f.act(async()=>{f.transport('closed')});await f.act(async()=>{f.transport('open')});await f.tick()
    await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await focusTile(f);await f.tick()
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.tick()
    assert.deepEqual(models(f.text('primary')),[],'no proof was recorded after the gate unmounted')
  }finally{await f.close()}
})

test('a re-note queued just before unmount is dropped', {skip:!core}, async()=>{
  const f=await harness({state:{focusedStoredSessionId:'A',focusedSessionId:'ra'}})
  try{
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.tick()
    // The reset clears the proof and queues a deferred re-note; the gate unmounts before it runs.
    await f.act(async()=>{f.transport('closed');f.transport('open');f.unmountNow('primary')});await f.tick()
    await f.mount('tile',{sessionId:'rb',storedSessionId:'B'});await focusTile(f);await f.tick()
    await f.mount('primary',{sessionId:'ra',storedSessionId:'A'});await f.tick()
    assert.deepEqual(models(f.text('primary')),[],'the dropped re-note recorded nothing')
  }finally{await f.close()}
})
