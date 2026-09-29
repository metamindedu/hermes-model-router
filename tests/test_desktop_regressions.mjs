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
 const fn=new Function(...names,body+'; return reloadStatus;')
 const reload=fn(scope,{current:1},()=>{}, {refetch:()=>pending},fingerprint,host,'old',set('preview'),set('reviewed'),set('targets'),set('routes'),set('draft'),set('profile'),{current:true},set('unlock'),set('outcome'),{current:false},()=>{})
 const running=reload();profile='new'
 complete({data:{profiles:[{name:'old',models:{main:'OLD'}}],current_profile:'old'}})
 await running
 assert.deepEqual(changes,[])
})

test('native backend uses explicit-profile argv and framed JSON, no shell',async()=>{
 const start=source.indexOf('export async function nativeBackendCall')
 const end=source.indexOf('\nfunction RouterPage',start)
 const body=source.slice(start,end).replace('export ','')
 let recorded
 const host={state:{profile:{get:()=> 'default'}},request:async(method,args)=>{recorded={method,args};return {blocked:false,code:0,output:'MODEL_ROUTER_JSON:{"revision":1}\n'}}}
 const call=new Function('host',body+'; return nativeBackendCall;')(host)
 assert.equal((await call('/status')).revision,1)
 assert.equal(recorded.method,'cli.exec')
 assert.deepEqual(recorded.args.argv,['--profile','default','model-router','status','--body','{}'])
 assert.equal(recorded.args.profile,'default')
 await assert.rejects(()=>call('/arbitrary'))
})
