import React,{useState} from 'react'
import {createRoot} from 'react-dom/client'
import {QueryClient,QueryClientProvider} from '@tanstack/react-query'
import {host,Button,atom,gatewayActivationEpoch} from './fixture-operator-shim.jsx'
import {ExecutionPanel,createActiveExecutionObserver} from '../../desktop/plugin.js'
window.fixtureErrors=[]
window.fixtureConsole=[]
for(const level of ['error','warn']){
 const original=console[level]
 console[level]=(...args)=>{if(window.fixtureConsole.length<64)window.fixtureConsole.push({level,message:args.map(String).join(' ').slice(0,1000)});original.apply(console,args)}
}
window.addEventListener('error',event=>window.fixtureErrors.push(String(event.message)))
window.addEventListener('unhandledrejection',event=>window.fixtureErrors.push(String(event.reason)))
const target='specialist-research-fixture-with-long-profile-name'
const cwd='C:/fixture-only/long-workspace-for-responsive-ui-verification'
const identity={kind:'unknown',profile:null,slot:null,evidence:'unknown'}
const data={actions:[],modelCalls:0,leases:0,epoch:7,observerEpoch:1,nativeSequence:1,enabled:false,view:null,revision:'a'.repeat(64),nativeStatus:'running',nativeStartedAt:Date.now()/1000-75}
window.fixture=data
const jobs=Object.fromEntries(['A','B'].map(id=>[id,{id:'job-'+id,origin_profile:'coordinator',parent_session_id:'parent-'+id,target_profile:target,execution_mode:'gateway',
 status:'approval_wait',target_session_id:'tool-session-'+id,target_profile_id:'profile-home-'+id,target_instance_id:'instance-'+id,target_authority_epoch:7,target_cwd:cwd,
 admission_id:'admission-'+id,execution_generation:9,result_available:false,can_steer:false,can_approve:false,can_deny:false,can_clarify:false,observed:{kind:'profile',slot:null,profile:target,evidence:'runtime_reported'},
 pending_request:{kind:'approval',prompt_id:'approval-'+id,execution_generation:9,text:'격리 검수용 요청 요약입니다. 실제 파일·계정·명령은 사용하지 않습니다.',choices:['once','deny']}}]))
window.fixtureRoutes=()=>['A','B'].flatMap(id=>[
 {connectionId:id==='A'?'local':'fixture-host-B',mode:id==='A'?'local':'remote',profile:id==='A'?'coordinator':'coordinator-alias',targetProfile:'coordinator'},
 {connectionId:id==='A'?'local':'fixture-host-B',mode:id==='A'?'local':'remote',profile:'writer-alias',targetProfile:target}])
window.fixtureRPC=async(route,method,params)=>{
 const id=route.connectionId==='local'?'A':'B',job=jobs[id]
 data.actions.push({method,connection:route.connectionId,profile:route.profile,params})
 if(method==='runtime.describe')return {profile_id:job.target_profile_id,instance_id:job.target_instance_id,authority_epoch:data.epoch}
 if(method==='session.info')return {desktop_protocol:'hermes-gateway-v1',profile_id:job.target_profile_id,profile_name:target,source:'tool',cwd,client:{name:'model-router-profile-job'},system_prompt:'PRIVATE_TARGET_INVENTORY_MUST_NOT_APPEAR'}
 if(params.session_id!=='parent-'+id)throw Error('wrong synthetic owner')
 if(method==='session.events.since'){
  const epoch='fixture-replay-'+id,latest=data.nativeSequence,missing=params.replay_epoch!==epoch
  const events=missing||params.last_sequence>=latest?[]:[{seq:latest,replay_epoch:epoch,session_id:'parent-'+id,
   type:data.nativeStatus==='running'?'subagent.start':'subagent.complete',payload:{delegation_id:'deleg-'+id,subagent_id:'sa-'+id,task_index:0,status:data.nativeStatus,tool_count:7,api_calls:3,summary:'PRIVATE_REPLAY_CANARY'}}]
  return {events,replay_epoch:epoch,epoch,latest_seq:latest,last_sequence:latest,count:events.length,snapshot_required:missing,truncated:missing}
 }
 if(method.endsWith('execution.list'))return {schema:1,origin_profile:'coordinator',supported:true,rows:[
  {id:'native-'+id,execution_mode:'native',requested:{kind:'model',profile:null,purpose:'implementation',slot:'code-complex'},observed:{kind:'model',slot:'code-complex',profile:null,backend:'model-router',evidence:'runtime_reported',model:'fixture-slot-model-with-long-name-for-layout',provider:'fixture'},conversation_id:'parent-'+id,parent_session_id:'parent-'+id,status:data.nativeStatus,updated_at:Date.now()/1000,subagent_id:'sa-'+id,delegation_id:'deleg-'+id,task_index:0,
   child_session_id:'child-'+id,started_at:data.nativeStartedAt,activity_at:Date.now()/1000-4,last_tool:'read_file',tool_count:7,api_call_count:3,duration_seconds:data.nativeStatus==='running'?null:80},
  {id:'profile-'+id,execution_mode:'native',requested:{kind:'profile',profile:target},observed:identity,conversation_id:'parent-'+id,parent_session_id:'parent-'+id,task_index:1,status:'requested',updated_at:1},
  {id:'profile-completed-'+id,execution_mode:'native',requested:{kind:'profile',profile:target},observed:identity,conversation_id:'parent-'+id,parent_session_id:'parent-'+id,task_index:2,status:'completed',updated_at:Date.now()/1000,
   subagent_id:'sa-profile-'+id,delegation_id:'deleg-profile-'+id,child_session_id:'rotated-profile-child-'+id,started_at:data.nativeStartedAt,activity_at:Date.now()/1000-5,tool_count:null,api_call_count:null} ]}
 if(method==='subagent.list')return {subagents:data.nativeStatus==='running'?[{subagent_id:'sa-'+id,delegation_id:'deleg-'+id,child_session_id:'child-'+id,status:'running',tool_count:7,last_tool:'read_file',started_at:data.nativeStartedAt}]:[]}
 if(method.endsWith('profile_jobs.list'))return {schema:1,origin_profile:'coordinator',parent_session_id:params.session_id,completion_delivery:'explicit_result',jobs:[structuredClone(job)]}
 if(method.endsWith('profile_jobs.describe'))return {schema:1,origin_profile:'coordinator',supported:true,revision:data.revision,
  policy:{schema:1,enabled:data.enabled,targets:data.enabled?[target]:[]},grant_management:{transport:'host_cli',rpc_writable:false},response_management:{transport:'native_session',rpc_writable:false},
  operator_controls_supported:false,completion_delivery:'explicit_result',targets:[{profile:target,cwd,available:true}]}
 if(method.endsWith('profile_jobs.result'))return {schema:1,origin_profile:'coordinator',job:structuredClone(job),result:{text:'가짜 결과입니다. 모델·계정·Gateway를 실행하지 않았습니다.'}}
 if(method.endsWith('profile_jobs.control')&&['refresh','stop','steer'].includes(params.operation))return {schema:1,origin_profile:'coordinator',job:structuredClone(job)}
 throw Error('forbidden synthetic method: '+method)
}
window.fixtureRetain=async()=>{data.leases++;return ()=>{data.leases--}}
let renderView=()=>{}
window.fixtureOpen=async(sid,options)=>{data.actions.push({method:'native-open',sid,route:options.route});data.view={sid,route:options.route};renderView({...data.view})}
const client=new QueryClient({defaultOptions:{queries:{retry:false,refetchOnWindowFocus:false,structuralSharing:false}}})
window.fixtureQueryClient=client
const values=new Map(),storage={get:(key,fallback)=>values.has(key)?structuredClone(values.get(key)):fallback,set:(key,value)=>values.set(key,structuredClone(value))}
window.fixtureFocus=id=>{host.state.focusedSessionOwner.set({connectionId:id==='A'?'local':'fixture-host-B',profile:id==='A'?'coordinator':'coordinator-alias'});host.state.focusedSessionId.set('parent-'+id)}
window.fixtureGateway={connectionState:'open',sessionWire:'canonical',onState:fn=>{fn('open');return()=>{}},
 request:(method,params)=>window.fixtureRPC({connectionId:'local',profile:'coordinator',targetProfile:'coordinator',mode:'local'},method,params)}
const observer=createActiveExecutionObserver(host,{atom,gatewayActivationEpoch,queryClient:client})
function App(){
 const [view,setView]=useState(null);renderView=setView
 return <QueryClientProvider client={client}><main style={{maxWidth:'70rem',padding:'12px',margin:'0 auto',minWidth:0,height:'100vh',overflowY:'auto',overscrollBehavior:'contain'}}>
  <header style={{padding:'12px 0',display:'flex',gap:8,flexWrap:'wrap',alignItems:'center'}}>
   <h1 style={{fontSize:18,margin:0,width:'100%'}}>격리 검수 · 실행 현황</h1>
   <p style={{fontSize:12,margin:0,width:'100%'}}>실제 Native UI 컴포넌트 · 모든 데이터·연결은 가짜 · 실사용 설정·모델 호출 없음</p>
   <Button size="sm" onClick={()=>window.fixtureFocus('A')}>검수 연결 A</Button><Button size="sm" onClick={()=>window.fixtureFocus('B')}>검수 연결 B</Button>
   <Button size="sm" onClick={()=>{data.enabled=!data.enabled;data.revision=data.enabled?'b'.repeat(64):'c'.repeat(64);client.invalidateQueries()}}>검수 데이터만 권한 ON/OFF</Button>
   <Button size="sm" onClick={()=>{data.epoch++;client.invalidateQueries()}}>검수 대상 epoch 변경</Button>
   <Button size="sm" onClick={()=>{for(const job of Object.values(jobs)){job.status='completed';job.pending_request=null;job.result_available=true}client.invalidateQueries()}}>검수 작업 완료</Button>
   {['running','completed','failed'].map(status=><Button key={status} size="sm" onClick={()=>{data.nativeStatus=status;data.nativeSequence++;client.invalidateQueries()}}>{({'running':'네이티브 실행 중','completed':'네이티브 완료','failed':'네이티브 실패'})[status]}</Button>)}
  </header>
  {view?<section role="status" style={{padding:12,border:'1px solid var(--ui-stroke-secondary)',overflowWrap:'anywhere'}}><h2>검수용 대상 대화 · 실제 Native 화면은 아님</h2><p>{view.route.connectionId} / {view.route.profile} / {view.sid}</p><p>플러그인이 정확한 대상 열기를 요청했습니다. 실제 승인·답변·작업 제출은 수행하지 않았습니다.</p><Button size="sm" onClick={()=>{data.view=null;setView(null)}}>검수 대상 화면 닫기</Button></section>:null}
  <details><summary>입력창 보조정보 · 동일한 포커스 대화</summary><ExecutionPanel compact observer={observer} ctx={{storage}}/></details>
  <ExecutionPanel observer={observer} ctx={{storage}}/>
 </main></QueryClientProvider>
}
createRoot(document.getElementById('root')).render(<App/>)
