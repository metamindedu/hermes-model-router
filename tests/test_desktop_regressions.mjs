import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
const source=fs.readFileSync(new URL('../desktop/plugin.js',import.meta.url),'utf8')

test('late reload after gateway switch does not replace draft or unlock state',async()=>{
 const start=source.indexOf('  const reloadStatus = async () => {')
 const end=source.indexOf('\n  }',start)+4
 const body=source.slice(start,end)
 let complete;const pending=new Promise(r=>complete=r)
 let profile='old';let changes=[]
 const fingerprint=(c,p,g)=>JSON.stringify([c,p,g])
 const host={state:{connectionId:{get:()=> 'local'},profile:{get:()=>profile},gateway:{get:()=> 'ready'}}}
 const scope=fingerprint('local','old','ready')
 const names=['scopeKey','generationRef','setPageError','statusQuery','scopeFingerprint','host','selectedProfile','setPreview','setReviewed','setModelTargets','setRoutingProfiles','setDraft','setSelectedProfile','needsReloadRef','setNeedsReload','setApplyOutcome','applyPendingRef','invalidatePlan']
 const set=name=>()=>changes.push(name)
 const fenceStart=source.indexOf('export function readNativeSaveFence')
 const fenceCode=source.slice(fenceStart,source.indexOf('\nfunction writeNativeSaveFence',fenceStart)).replace('export ','')
 const readFence=new Function('PREPARATION_ID_RE','PREPARATION_PROFILE_RE',fenceCode+'; return readNativeSaveFence;')(/^[a-f0-9]{64}$/, /^[a-z0-9][a-z0-9_-]{0,63}$/)
 const fn=new Function(...names,'refreshPendingRef','setupPendingRef','profilePreparationReloadBlocked','finishProfilePreparationReload','readNativeSaveFence','pluginContext','statusDataRef','nativeRecoveryConfirmed',body+'; return reloadStatus;')
 const refreshPendingRef={current:false}
 const reload=fn(scope,{current:1},()=>{}, {refetch:()=>pending},fingerprint,host,'old',set('preview'),set('reviewed'),set('targets'),set('routes'),set('draft'),set('profile'),{current:true},set('unlock'),set('outcome'),{current:false},()=>{},refreshPendingRef,{current:false},()=>false,()=>true,readFence,{storage:{get:()=>({})}},{current:{}},false)
 const running=reload();profile='new'
 complete({data:{profiles:[{name:'old',models:{main:'OLD'}}],current_profile:'old'}})
 await running
 assert.deepEqual(changes,[])
})

// The page transport plus the two pure helpers it relies on, evaluated outside the module.
function nativeCallSource(){
 const cut=(from,to)=>{const at=source.indexOf(from);assert.ok(at>=0,from);return source.slice(at,source.indexOf(to,at))}
 return [cut('function sameValue(','\nexport function selectedModelPreset'),cut('export const STATUS_PAGE_LIMIT','\n// The backend refuses a request body'),
  cut('export async function nativeBackendCall','\nfunction RouterPage')].join('\n').replaceAll('export ','')
}

test('the page reads a status larger than one CLI reply in pages and joins it',async()=>{
 const names=Array.from({length:11},(_,index)=>'profile-'+index)
 const filler='x'.repeat(4600)
 const row=name=>({name,models:{filler}})
 const argvs=[]
 const host={state:{profile:{get:()=> 'default'}},request:async(method,args)=>{
  const sent=JSON.parse(args.argv.at(-1)); argvs.push(sent)
  const wanted=sent.profiles||names
  const page={revision:3,readiness_context:{base_identity:'i'},profile_names:names,profiles:wanted.slice(0,5).map(row),pending_profiles:wanted.slice(5)}
  // Hermes cuts one reply at 48,000 characters.
  return {blocked:false,code:0,output:('MODEL_ROUTER_JSON:'+JSON.stringify(page)).slice(0,48000)}
 }}
 const call=new Function('host',nativeCallSource()+'; return nativeBackendCall;')(host)
 const status=await call('/status')
 assert.deepEqual(status.profiles.map(item=>item.name),names)
 assert.ok(JSON.stringify(status).length>48000,'the joined status is larger than a single reply could carry')
 assert.deepEqual(argvs,[{paged:true},{paged:true,profiles:names.slice(5)},{paged:true,profiles:names.slice(10)}])
 // An older backend refuses the paged body with exit code 2: the page asks once more the old way.
 const seen=[]
 const older={state:{profile:{get:()=> 'default'}},request:async(method,args)=>{
  const sent=args.argv.at(-1); seen.push(sent)
  return sent==='{}'?{blocked:false,code:0,output:'MODEL_ROUTER_JSON:{"revision":2,"profiles":[]}'}
   :{blocked:false,code:2,output:'MODEL_ROUTER_JSON:{"error":"ValueError","message":"The request is invalid."}'}
 }}
 const legacy=new Function('host',nativeCallSource()+'; return nativeBackendCall;')(older)
 assert.equal((await legacy('/status')).revision,2)
 assert.deepEqual(seen,['{"paged":true}','{}'])
 // Other operations are sent once, unchanged.
 seen.length=0
 await assert.rejects(()=>legacy('/preview',{body:{profile:'default'}}),/The request is invalid/)
 assert.deepEqual(seen,['{"profile":"default"}'])
})

test('native RPC timeout outlives the backend command instead of expiring at default 30s',async()=>{
 const start=source.indexOf('export async function nativeBackendCall')
 const end=source.indexOf('\nfunction RouterPage',start)
 const body=nativeCallSource()
 let recorded
 const host={state:{profile:{get:()=> 'default'}},request:async(method,args,timeoutMs)=>{recorded={method,args,timeoutMs};return {blocked:false,code:0,output:'MODEL_ROUTER_JSON:'+JSON.stringify({revision:1})}}}
 const call=new Function('host',body+'; return nativeBackendCall;')(host)
 await call('/status')
 assert.ok(recorded.timeoutMs > recorded.args.timeout*1000, 'outer RPC must outlive subprocess timeout and never silently use 30s default')
})

test('native backend uses explicit-profile argv and framed JSON, no shell',async()=>{
 const start=source.indexOf('export async function nativeBackendCall')
 const end=source.indexOf('\nfunction RouterPage',start)
 const body=nativeCallSource()
 let recorded
 const host={state:{profile:{get:()=> 'default'}},request:async(method,args)=>{recorded={method,args};return {blocked:false,code:0,output:'MODEL_ROUTER_JSON:{"revision":1}\n'}}}
 const call=new Function('host',body+'; return nativeBackendCall;')(host)
 assert.equal((await call('/status')).revision,1)
 assert.equal(recorded.method,'cli.exec')
 assert.deepEqual(recorded.args.argv,['--profile','default','model-router','status','--body','{"paged":true}'])
 assert.equal(recorded.args.profile,'default')
 await assert.rejects(()=>call('/arbitrary'))
})
