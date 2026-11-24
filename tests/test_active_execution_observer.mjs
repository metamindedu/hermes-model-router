import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import test from 'node:test'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
function atom(value) {
  const listeners = new Set()
  return { get: () => value, set(next) { value = next; for (const fn of [...listeners]) fn() },
    listen(fn) { listeners.add(fn); return () => listeners.delete(fn) }, count: () => listeners.size }
}
function api() {
  const imports = {}
  for (const match of source.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g)) for (const name of match[1].split(',').map(value=>value.trim()).filter(Boolean)) imports[name]=undefined
  imports.DesktopSDK={}
  const code=source.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]+['"]\s*;?/g,'').replace(/^import \* as DesktopSDK from '@hermes\/plugin-sdk'\s*$/m,'').replace(/export default /g,'const pluginDefinition = ').replace(/^export\s+/gm,'')
  return new Function(...Object.keys(imports),code+'\nreturn {createActiveExecutionObserver};')(...Object.values(imports))
}
const scope = () => ({connectionId:'local',profile:'claire',sessionId:'parent'})
const frame = (seq,status='completed') => ({session_id:'parent',replay_epoch:'epoch-1',seq,type:'subagent.complete',
  payload:{delegation_id:'call-wide',subagent_id:'sa-native-0',task_index:0,status,goal:'PRIVATE_REPLAY_GOAL',summary:'PRIVATE_REPLAY_SUMMARY',api_calls:2}})
const reply = (events, latest, recovery=false) => ({events,replay_epoch:'epoch-1',epoch:'epoch-1',latest_seq:latest,last_sequence:latest,count:events.length,snapshot_required:recovery,truncated:recovery,open_requests:[{text:'PRIVATE_NATIVE_PROMPT'}]})
function fixture() {
  const calls=[], prohibited=[], states=new Set()
  const state=Object.fromEntries(Object.entries({focusedSessionOwner:{connectionId:'local',profile:'claire'},focusedSessionId:'parent',connectionId:'local',profile:'claire',gateway:'open',activeSessionId:'parent'}).map(([name,value])=>[name,atom(value)]))
  let epoch=1
  const f={calls,prohibited,state,frames:[frame(1)],minimum:1}
  const gateway={connectionState:'open',sessionWire:'canonical',onState(fn){states.add(fn);fn(this.connectionState);return()=>states.delete(fn)},
    request(method,params,timeout,signal){calls.push({method,params,timeout,signal});return Promise.resolve().then(()=>f.serve(method,params,signal))}}
  f.gateway=gateway
  f.serve=(method,params)=>{
    assert.equal(params.profile,'claire');assert.equal(params.session_id,'parent')
    if(method==='plugin.model-router.execution.list') return {schema:1,origin_profile:'claire',conversation_id:'parent',rows:[{
      id:'call:0',execution_mode:'native',conversation_id:'parent',parent_session_id:'parent',task_index:0,
      subagent_id:'sa-native-0',delegation_id:'opaque-unit',async_unit_id:'opaque-unit',native_call_delegation_id:'call-wide',
      requested:{kind:'profile',profile:'specialist'},observed:{kind:'unknown'},status:'queued',child_session_id:'rotated-physical'}]}
    if(method==='subagent.list') return {subagents:[]}
    if(method==='plugin.model-router.profile_jobs.list') return {schema:1,origin_profile:'claire',parent_session_id:'parent',jobs:[]}
    if(method==='plugin.model-router.profile_jobs.describe') return {schema:1,supported:true,origin_profile:'claire',revision:'a'.repeat(64),policy:{schema:1,enabled:false,targets:[]},targets:[]}
    if(method==='session.events.since') {
      const latest=f.frames.at(-1)?.seq || 0
      if(params.replay_epoch!=='epoch-1' || params.last_sequence<f.minimum-1) return reply([],latest,true)
      return reply(f.frames.filter(value=>value.seq>params.last_sequence),latest)
    }
    throw Error('unexpected method')
  }
  const deny=name=>(...args)=>{prohibited.push(name);throw Error('forbidden observer dial/control')}
  f.host={state,getGateway:()=>f.gateway,profileRoutes:deny('profileRoutes'),requestProfile:deny('requestProfile'),request:deny('ambient request'),retainProfile:deny('retain'),ensureAgent:deny('ensure')}
  f.sdk={atom,gatewayActivationEpoch:()=>epoch,queryClient:{cancelQueries:async()=>{},removeQueries:()=>{}}}
  f.nextEpoch=()=>epoch++
  f.transportState=value=>{gateway.connectionState=value;for(const listener of [...states])listener(value)}
  f.observer=api().createActiveExecutionObserver(f.host,f.sdk)
  f.close=()=>f.observer.dispose()
  return f
}
const tick = () => new Promise(resolve=>setImmediate(resolve))

test('approved observer reads only captured open origin, projects replay and never invokes routing/control', async()=>{
  const f=fixture()
  try {
    assert.equal(f.observer.eligible(scope()),true);assert.equal(f.calls.length,0)
    const result=await f.observer.read(scope())
    assert.equal(result.rows[0].status,'completed');assert.equal(result.rows[0].api_call_count,2)
    assert.equal(result.rows[0].requested.profile,'specialist');assert.equal(result.rows[0].observed.kind,'unknown')
    assert.equal(result.rows[0].child_session_id,'rotated-physical')
    assert.equal(f.observer.accepts(scope(),result),true)
    assert.equal(f.observer.accepts(scope(),{...result,observation_epoch:999}),false)
    assert.equal(f.observer.accepts(scope(),{...result,observation_lifetime:'old-observer'}),false)
    assert.equal(result.replay_coverage_gap,false);assert.doesNotMatch(JSON.stringify(result),/PRIVATE_REPLAY|PRIVATE_NATIVE_PROMPT|open_requests/)
    assert.deepEqual(f.calls.map(value=>value.method),['plugin.model-router.execution.list','subagent.list','plugin.model-router.profile_jobs.list','session.events.since','session.events.since'])
    for(const call of f.calls){assert.equal(call.timeout,10000);assert.ok(call.signal instanceof AbortSignal)}
    assert.deepEqual(f.prohibited,[])
  } finally {f.close()}
})
test('ineligible focus, owner, wire, mapping and socket states fail before any RPC', async()=>{
  for(const change of [f=>f.state.focusedSessionOwner.set(null),f=>f.state.focusedSessionId.set(null),
    f=>f.state.focusedSessionOwner.set({connectionId:'other',profile:'claire'}),f=>f.state.profile.set('other'),
    f=>f.state.gateway.set('connecting'),f=>f.state.gateway.set('error'),f=>f.gateway.sessionWire='legacy',
    f=>f.gateway.connectionState='closed',f=>f.gateway=null,
    f=>{f.state.connectionId.set('remote');f.state.focusedSessionOwner.set({connectionId:'remote',profile:'claire'})}]) {
    const f=fixture();try {change(f);assert.equal(f.observer.eligible(scope()),false);await assert.rejects(f.observer.read(scope()));assert.equal(f.calls.length,0);assert.deepEqual(f.prohibited,[])}finally{f.close()}
  }
  const f=fixture();try{
    f.state.connectionId.set('remote');f.state.focusedSessionOwner.set({connectionId:'remote',profile:'claire'})
    await assert.rejects(f.observer.read({...scope(),connectionId:'remote'}));assert.equal(f.calls.length,0)
  }finally{f.close()}
})
test('scope A-B-A rejects and aborts an already-started old read, not just final string mismatch', async()=>{
  const f=fixture(),serve=f.serve;let release
  f.serve=(method,params,signal)=>method==='plugin.model-router.execution.list'?new Promise(resolve=>{release=()=>resolve(serve(method,params,signal))}):serve(method,params,signal)
  try{
    const pending=f.observer.read(scope());await tick();assert.ok(release)
    f.state.focusedSessionId.set('other-parent');f.state.focusedSessionId.set('parent')
    assert.ok(f.calls.every(call=>call.signal.aborted));release()
    await assert.rejects(pending,/scope_changed/);assert.equal(f.calls.filter(call=>call.method==='session.events.since').length,0)
    assert.deepEqual(f.prohibited,[])
  }finally{f.close()}
})
test('activation epoch fences identical labels even without a lasting profile change', async()=>{
  const f=fixture(),serve=f.serve;let release
  f.serve=(method,params,signal)=>method==='plugin.model-router.execution.list'?new Promise(resolve=>{release=()=>resolve(serve(method,params,signal))}):serve(method,params,signal)
  try{const pending=f.observer.read(scope());await tick();f.nextEpoch();release();await assert.rejects(pending,/scope_changed/)}finally{f.close()}
})
test('same-instance reconnect and replacement instance invalidate late data', async()=>{
  for(const replace of [false,true]) {
    const f=fixture(),serve=f.serve;let release
    f.serve=(method,params,signal)=>method==='plugin.model-router.execution.list'?new Promise(resolve=>{release=()=>resolve(serve(method,params,signal))}):serve(method,params,signal)
    try{
      const pending=f.observer.read(scope());await tick()
      if(replace)f.gateway={...f.gateway};else{f.transportState('closed');f.transportState('open')}
      release();await assert.rejects(pending,/scope_changed/);assert.deepEqual(f.prohibited,[])
    }finally{f.close()}
  }
})
test('equivalent owner notifications do not discard valid work', async()=>{
  const f=fixture(),serve=f.serve;let release
  f.serve=(method,params,signal)=>method==='plugin.model-router.execution.list'?new Promise(resolve=>{release=()=>resolve(serve(method,params,signal))}):serve(method,params,signal)
  try{const pending=f.observer.read(scope());await tick();f.state.focusedSessionOwner.set({connectionId:'local',profile:'claire'});release();assert.equal((await pending).rows[0].status,'completed')}finally{f.close()}
})
test('one in-flight snapshot per scope/generation and sticky terminal across subsequent polls', async()=>{
  const f=fixture()
  try{
    const first=f.observer.read(scope()),second=f.observer.read(scope());assert.equal(first,second)
    const data=await first;assert.equal(data.rows[0].status,'completed')
    const again=await f.observer.read(scope());assert.equal(again.rows[0].status,'completed')
    assert.equal(f.calls.filter(call=>call.method==='session.events.since').length,3)
  }finally{f.close()}
})
test('replay gap tail recovery is bounded, keeps missing coverage and never resumes', async()=>{
  const f=fixture();f.frames=[frame(999),frame(1000)];f.minimum=999
  try{
    const result=await f.observer.read(scope())
    assert.equal(result.replay_coverage_gap,true);assert.equal(result.rows[0].status,'completed')
    assert.equal(f.calls.filter(value=>value.method==='session.events.since').length,6)
    assert.deepEqual(f.prohibited,[])
  }finally{f.close()}
})
test('failed replay is not retried through another route or a session control', async()=>{
  const f=fixture(),serve=f.serve
  f.serve=(method,params,signal)=>{if(method==='session.events.since')throw Error('PRIVATE_TRANSPORT_FAILURE');return serve(method,params,signal)}
  try{
    const data=await f.observer.read(scope());assert.equal(data.rows[0].status,'unknown');assert.equal(data.replay_coverage_gap,true)
    assert.doesNotMatch(JSON.stringify(data),/PRIVATE_TRANSPORT_FAILURE/);assert.deepEqual(f.prohibited,[])
  }finally{f.close()}
})
test('only authorized roster parent aliases, never child locators, qualify replay envelopes', async()=>{
  for(const parentProof of [true,false]){
    const f=fixture(),serve=f.serve
    f.serve=(method,params,signal)=>{
      assert.equal(params.session_id,'rotated-parent')
      // Inert backend models its explicit logical-parent alias admission.
      const result=serve(method,{...params,session_id:'parent'},signal)
      if(method==='plugin.model-router.execution.list' && !parentProof){
        result.rows[0].conversation_id='rotated-parent';result.rows[0].parent_session_id='rotated-parent';result.rows[0].child_session_id='parent'
      }
      return result
    }
    f.state.focusedSessionId.set('rotated-parent')
    try{
      const result=await f.observer.read({...scope(),sessionId:'rotated-parent'})
      assert.equal(result.rows[0].status,parentProof?'completed':'unknown')
      assert.equal(result.replay_coverage_gap,!parentProof)
      assert.ok(f.calls.every(value=>value.params.session_id==='rotated-parent'),'literal requested ID stays unchanged on wire')
    }finally{f.close()}
  }
})
test('policy inspection shares exact-origin guard; disposal prevents further reads', async()=>{
  const f=fixture()
  const data=await f.observer.policy(scope());assert.equal(data.policy.enabled,false)
  assert.deepEqual(f.calls.map(value=>value.method),['plugin.model-router.profile_jobs.describe'])
  f.close();await assert.rejects(f.observer.read(scope()));await assert.rejects(f.observer.policy(scope()))
  assert.equal(f.calls.length,1);assert.ok(Object.values(f.state).every(value=>value.count()===0));assert.deepEqual(f.prohibited,[])
})

test('actual native canonical client/channel sends only observer reads on its already-open socket', {skip:!process.env.HERMES_DESKTOP_SOURCE_ROOT}, async()=>{
  // Native client/protocol/channel run unchanged. Only the WS server, host
  // state/registry and backend response data are inert fixture boundaries.
  const core=process.env.HERMES_DESKTOP_SOURCE_ROOT
  const require=createRequire(path.join(core,'apps/desktop/package.json'))
  const {buildSync}=require('esbuild'),{WebSocketServer}=require('ws')
  const bundle=buildSync({stdin:{contents:`export {HermesGateway} from ${JSON.stringify(path.join(core,'apps/desktop/src/api/client.ts'))}; export {buildRegistryProfileRoutes} from ${JSON.stringify(path.join(core,'apps/desktop/electron/plugin-profile-routes.ts'))};`,resolveDir:core,loader:'ts'},
    bundle:true,write:false,platform:'node',format:'cjs',target:'node22',
    alias:{'@hermes/shared':path.join(core,'apps/shared/src/index.ts')},
    nodePaths:[process.env.NODE_PATH || path.join(core,'apps/desktop/node_modules')],
    tsconfigRaw:{compilerOptions:{baseUrl:path.join(core,'apps/desktop'),paths:{'@/*':['src/*']}}}})
  const module={exports:{}}
  new Function('require','module','exports',bundle.outputFiles[0].text)(require,module,module.exports)
  const {HermesGateway,buildRegistryProfileRoutes}=module.exports
  assert.deepEqual(buildRegistryProfileRoutes({agents:[{connectionId:'local',profile:'claire'}],sources:[{id:'local',kind:'local'}]}),
    [{connectionId:'local',mode:'local',profile:'claire',targetProfile:'claire'}])
  assert.match(readFileSync(path.join(core,'apps/desktop/electron/connection-registry.ts'),'utf8'),/LOCAL_CONNECTION_ID = 'local'/)
  const server=new WebSocketServer({host:'127.0.0.1',port:0})
  await new Promise(resolve=>server.once('listening',resolve))
  const f=fixture(),wire=[],prompts=[];let sockets=0,observer
  const native=new HermesGateway()
  const off=native.onRequest(request=>{prompts.push(request.method);return true})
  server.on('connection',peer=>{
    sockets++
    peer.on('message',bytes=>{
      const request=JSON.parse(bytes.toString());wire.push(request)
      if(!request.method)return
      if(request.method==='client.capabilities') {
        // Normal connection handshake from fixture setup, before the observer.
        peer.send(JSON.stringify({jsonrpc:'2.0',id:request.id,result:{server_requests:true,declines_not_shown:true}}));return
      }
      const result=f.serve(request.method,request.params)
      if(request.method==='session.events.since') result.open_requests=[{id:'fixture-approval',method:'approval',params:{description:'PRIVATE_NATIVE_PROMPT'}}]
      peer.send(JSON.stringify({jsonrpc:'2.0',id:request.id,result}))
    })
  })
  try{
    // Fixture setup, not the observer, owns this one initial connection.
    await native.connect(`ws://127.0.0.1:${server.address().port}/api/ws?native_dial=fixture&ticket=fixture-only`)
    assert.equal(native.sessionWire,'canonical');assert.equal(native.connectionState,'open')
    f.close();f.gateway=native
    observer=api().createActiveExecutionObserver(f.host,f.sdk)
    const data=await observer.read(scope())
    assert.equal(data.rows[0].status,'completed');assert.equal(sockets,1)
    assert.ok(prompts.length>0 && prompts.every(value=>value==='approval'),'normal native prompt recovery remains intact')
    assert.doesNotMatch(JSON.stringify(data),/PRIVATE_REPLAY|PRIVATE_NATIVE_PROMPT|open_requests/)
    assert.equal(wire.filter(value=>value.method==='client.capabilities').length,1,'one setup handshake, not an observer dial')
    const reads=wire.filter(value=>value.method!=='client.capabilities')
    assert.deepEqual(reads.map(value=>value.method),['plugin.model-router.execution.list','subagent.list','plugin.model-router.profile_jobs.list','session.events.since','session.events.since'])
    assert.ok(reads.every(value=>value.params.session_id==='parent' && value.params.profile==='claire'))
    assert.deepEqual(f.prohibited,[])
  }finally{
    observer?.dispose();off();native.close();f.close()
    for(const peer of server.clients)peer.terminate()
    await new Promise(resolve=>server.close(resolve))
  }
})
// Split view: primary runtime 'parent' (stored 'parent-stored'); a tile 'tile-runtime' later takes focus.
function withPrimaryProof(f,{owner={connectionId:'local',profile:'claire'}}={}){
  f.state.focusedStoredSessionId=f.state.focusedStoredSessionId||atom('parent-stored')
  f.state.focusedStoredSessionId.set('parent-stored');f.state.focusedSessionOwner.set(owner)
  const noted=f.observer.notePrimary({runtime:'parent',stored:'parent-stored'})
  f.state.focusedStoredSessionId.set('tile-stored');f.state.focusedSessionId.set('tile-runtime')
  f.state.focusedSessionOwner.set({connectionId:'local',profile:'claire'})
  return noted
}
function proofFixture(){const f=fixture();f.state.focusedStoredSessionId=atom('parent-stored');f.close();f.observer=api().createActiveExecutionObserver(f.host,f.sdk);f.close=()=>f.observer.dispose();return f}
test('primary own-session read needs the host-reported owner proof, never the ambient socket', async()=>{
  // No proof: a tile holds focus from the start, so the primary is never admitted.
  const none=proofFixture()
  try{none.state.focusedStoredSessionId.set('tile-stored');none.state.focusedSessionId.set('tile-runtime')
    assert.equal(none.observer.primaryScope(),null);assert.equal(none.observer.eligible(scope()),false);await assert.rejects(none.observer.read(scope()));assert.equal(none.calls.length,0)
  }finally{none.close()}
  const f=proofFixture()
  try{
    assert.equal(withPrimaryProof(f),true)
    assert.deepEqual(f.observer.primaryScope(),scope())
    assert.equal(f.observer.eligible(scope()),true)
    const result=await f.observer.read(scope());assert.equal(result.rows[0].status,'completed');assert.equal(f.observer.accepts(scope(),result),true)
    assert.ok(f.calls.every(call=>call.params.session_id==='parent' && call.params.profile==='claire'))
    assert.equal(f.observer.eligible({...scope(),sessionId:'some-other-tile'}),false,'an unfocused non-primary session is never admitted')
    assert.deepEqual(f.prohibited,[])
  }finally{f.close()}
})
test('primary proof refusals use the proven labels: other owner, unresolved owner, navigation, transport reset', async()=>{
  // Owner proven as another profile (all-profiles navigation): the active claire socket never reads it.
  const other=proofFixture()
  try{assert.equal(withPrimaryProof(other,{owner:{connectionId:'local',profile:'wallace'}}),true)
    const proven={...scope(),profile:'wallace'};assert.deepEqual(other.observer.primaryScope(),proven)
    assert.equal(other.observer.eligible(proven),false);assert.equal(other.observer.eligible(scope()),false);await assert.rejects(other.observer.read(proven));assert.equal(other.calls.length,0)
  }finally{other.close()}
  const remote=proofFixture()
  try{assert.equal(withPrimaryProof(remote,{owner:{connectionId:'remote',profile:'claire'}}),true)
    const proven={...scope(),connectionId:'remote'};assert.equal(remote.observer.eligible(proven),false);assert.equal(remote.observer.eligible(scope()),false);assert.equal(remote.calls.length,0)
  }finally{remote.close()}
  const unresolved=proofFixture()
  try{assert.equal(withPrimaryProof(unresolved,{owner:null}),false);assert.equal(unresolved.observer.primaryScope(),null);assert.equal(unresolved.observer.eligible(scope()),false)}finally{unresolved.close()}
  for(const change of [f=>{f.state.activeSessionId.set('navigated');f.state.activeSessionId.set('parent')},f=>f.nextEpoch(),
    f=>{f.transportState('closed');f.transportState('open')},f=>{f.gateway={...f.gateway}}]) {
    const g=proofFixture()
    try{withPrimaryProof(g);assert.equal(g.observer.eligible(scope()),true);change(g)
      assert.equal(g.observer.primaryScope(),null,'proof dropped');assert.equal(g.observer.eligible(scope()),false);await assert.rejects(g.observer.read(scope()))
    }finally{g.close()}
  }
  // A note while ANOTHER chat is focused (tile owner unresolved) never withdraws the primary's proof.
  const tileUnresolved=proofFixture()
  try{withPrimaryProof(tileUnresolved);tileUnresolved.state.focusedSessionOwner.set(null)
    assert.equal(tileUnresolved.observer.notePrimary({runtime:'parent',stored:'parent-stored'}),false)
    assert.equal(tileUnresolved.observer.notePrimary({runtime:'foreign',stored:'foreign-stored'}),false)
    tileUnresolved.state.focusedSessionOwner.set({connectionId:'local',profile:'claire'})
    assert.deepEqual(tileUnresolved.observer.primaryScope(),scope(),'proof kept')
  }finally{tileUnresolved.close()}
  // notePrimary settles an unobserved transport change before answering.
  const silent=proofFixture()
  try{silent.state.focusedStoredSessionId.set('parent-stored')
    silent.nextEpoch()
    assert.equal(silent.observer.notePrimary({runtime:'parent',stored:'parent-stored'}),true)
    silent.state.focusedStoredSessionId.set('tile-stored');silent.state.focusedSessionId.set('tile-runtime')
    assert.deepEqual(silent.observer.primaryScope(),scope(),'a true return leaves a usable proof')
  }finally{silent.close()}
  const focused=proofFixture()
  try{withPrimaryProof(focused);focused.state.focusedSessionId.set('parent');focused.state.focusedStoredSessionId.set('parent-stored')
    focused.state.focusedSessionOwner.set(null);assert.equal(focused.observer.eligible(scope()),false,'primary focused with unresolved owner still fails closed')
  }finally{focused.close()}
})
test('primary A-B-A and focus moves invalidate an in-flight primary read', async()=>{
  for(const move of [f=>{f.state.activeSessionId.set('other-primary');f.state.activeSessionId.set('parent')},
    f=>{f.state.focusedSessionId.set('other-tile');f.state.focusedSessionId.set('tile-runtime')}]) {
    const f=proofFixture(),serve=f.serve;let release
    f.serve=(method,params,signal)=>method==='plugin.model-router.execution.list'?new Promise(resolve=>{release=()=>resolve(serve(method,params,signal))}):serve(method,params,signal)
    try{
      withPrimaryProof(f);const pending=f.observer.read(scope());await tick();assert.ok(release)
      move(f);assert.ok(f.calls.every(call=>call.signal.aborted));release()
      await assert.rejects(pending,/scope_changed/)
    }finally{f.close()}
  }
})
