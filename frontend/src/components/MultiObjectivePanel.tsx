import { useEffect, useMemo, useState } from 'react';
import { optimizationApi, type OptimizationDatasetOptions } from '../api/client';
import type { ResearchTopic } from '../types';

type Mode='sandbox'|'research';
type Point={x:number;y:number;kind:'pareto'|'dominated'|'candidate';label:string;candidate?:any};

export default function MultiObjectivePanel({topic}:{topic:ResearchTopic}){
  const [mode,setMode]=useState<Mode>('sandbox');
  const [methodId,setMethodId]=useState(topic.methods?.[0]?.versions?.[0]?.id??0);
  const [options,setOptions]=useState<OptimizationDatasetOptions|null>(null);
  const [features,setFeatures]=useState<string[]>([]);
  const [objectives,setObjectives]=useState<string[]>(['','']);
  const [directions,setDirections]=useState<('minimize'|'maximize')[]>(['minimize','minimize']);
  const [stepId,setStepId]=useState<number|null>(null);
  const [objectiveStepId,setObjectiveStepId]=useState<number|null>(null);
  const [pairing,setPairing]=useState<'same_step'|'downstream_explicit'>('same_step');
  const [downstreamConfirmed,setDownstreamConfirmed]=useState(false);
  const [relationLabel,setRelationLabel]=useState('');
  const [bounds,setBounds]=useState(['0,1','0,1']);
  const [reference,setReference]=useState('1.1,10.1');
  const [scales,setScales]=useState('1,1');
  const [batchSize,setBatchSize]=useState(2);
  const [searchBudget,setSearchBudget]=useState(160);
  const [samples,setSamples]=useState(64);
  const [model,setModel]=useState<any>(null);
  const [pareto,setPareto]=useState<any>(null);
  const [recommendation,setRecommendation]=useState<any>(null);
  const [benchmark,setBenchmark]=useState<any>(null);
  const [benchmarkBusy,setBenchmarkBusy]=useState(false);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const versions=useMemo(()=>topic.methods?.flatMap(method=>method.versions.map(version=>({id:version.id,label:`${method.name} · v${version.version_label??version.version_number}`})))??[],[topic]);

  useEffect(()=>{setMethodId(topic.methods?.[0]?.versions?.[0]?.id??0);setModel(null);setPareto(null);setRecommendation(null);setOptions(null)},[topic.id,topic.methods]);
  useEffect(()=>{
    if(mode!=='research'||!methodId){setOptions(null);return}
    let active=true;
    optimizationApi.datasetOptions(topic.id,methodId).then(result=>{if(!active)return;setOptions(result);setFeatures(v=>v.filter(id=>result.features.some(x=>x.parameter_id===id)));setObjectives(v=>v.map(id=>result.outcomes.some(x=>x.parameter_id===id)?id:''))}).catch(e=>{if(active)setError(String(e))});
    return()=>{active=false};
  },[mode,methodId,topic.id]);

  const pointData:Point[]=useMemo(()=>{
    const data:Point[]=[];
    (pareto?.observed_points??[]).forEach((p:any,i:number)=>data.push({x:p.objective_values[0],y:p.objective_values[1],kind:p.is_pareto?'pareto':'dominated',label:p.is_pareto?`관측 Pareto ${i+1}`:`관측 ${i+1}`}));
    (recommendation?.candidates??[]).forEach((c:any)=>data.push({x:c.predicted_objectives[0].mean,y:c.predicted_objectives[1].mean,kind:'candidate',label:c.candidate_id,candidate:c}));
    return data;
  },[pareto,recommendation]);

  const run=async()=>{
    setError('');setBusy(true);setModel(null);setPareto(null);setRecommendation(null);
    try{
      const inputIds=mode==='sandbox'?['x1','x2']:features;
      const objectiveIds=mode==='sandbox'?['f1','f2']:objectives;
      if(mode==='research'&&(!methodId||inputIds.length<1||objectiveIds.some(x=>!x)||objectiveIds[0]===objectiveIds[1]))throw new Error('공정 버전, 입력 조건, 서로 다른 측정 결과 두 개를 선택하세요.');
      if(mode==='research'&&pairing==='downstream_explicit'&&(!downstreamConfirmed||!relationLabel.trim()||!stepId||!objectiveStepId))throw new Error('후속 공정 연결을 확인하고 입력 단계와 결과 단계를 선택한 뒤 관계를 설명하세요.');
      const ranges=mode==='sandbox'?[[0,1],[0,1]]:bounds.map(v=>v.split(',').map(x=>x.trim()===''?Number.NaN:Number(x)));
      const limits=mode==='sandbox'?[[0,1],[0,1]]:ranges;
      if(limits.length!==inputIds.length||limits.some(x=>x.length!==2||!x.every(Number.isFinite)||x[0]>=x[1]))throw new Error('각 입력 조건의 범위를 최소값,최대값 형식으로 입력하세요.');
      const parsePair=(value:string)=>value.split(',').map(x=>x.trim()===''?Number.NaN:Number(x));
      const ref=parsePair(reference),scale=parsePair(scales);
      if(ref.length!==2||!ref.every(Number.isFinite)||scale.length!==2||scale.some(x=>!Number.isFinite(x)||x<=0))throw new Error('목적별 Hypervolume 기준점과 양수 스케일을 입력하세요.');
      const trained=await optimizationApi.mooTrain({topic_id:topic.id,mode,feature_ids:inputIds,objective_ids:objectiveIds,objective_directions:directions,method_version_id:mode==='research'?methodId:null,process_step_id:mode==='research'?stepId:null,objective_process_step_id:mode==='research'?(pairing==='same_step'?stepId:objectiveStepId):null,pairing_policy:pairing,downstream_link_confirmed:downstreamConfirmed,downstream_relation_label:relationLabel.trim()||undefined,sandbox_samples:48,seed:7});
      setModel(trained);
      const front=await optimizationApi.mooPareto(trained.model_id,topic.id,ref,scale);setPareto(front);
      const suggested=await optimizationApi.mooRecommend(trained.model_id,{topic_id:topic.id,bounds:limits,bounds_units:mode==='research'?inputIds.map(id=>options?.features.find(f=>f.parameter_id===id)?.unit??'dimensionless'):['dimensionless','dimensionless'],reference_point:ref,objective_scales:scale,batch_size:batchSize,search_budget:searchBudget,monte_carlo_samples:samples,seed:7,min_candidate_distance:mode==='sandbox'?.04:.02});
      setRecommendation(suggested);
      // Re-fetch saved recommendation to verify its durable record is readable.
      const saved=await optimizationApi.mooGetRecommendation(suggested.recommendation_id,topic.id);
      setRecommendation(saved);
    }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  };
  const runBenchmark=async()=>{setError('');setBenchmarkBusy(true);try{setBenchmark(await optimizationApi.mooCompareBenchmark(7,10))}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBenchmarkBusy(false)}};
  const xValues=pointData.map(p=>p.x),yValues=pointData.map(p=>p.y);
  const range=(values:number[])=>{if(!values.length)return[0,1];const lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.12,Math.abs(hi||1)*.06,1e-9);return[lo-pad,hi+pad]};
  const xr=range([...xValues,...(pareto?.reference_point??[]).slice(0,1)]),yr=range([...yValues,...(pareto?.reference_point??[]).slice(1,2)]);
  const cx=(v:number)=>42+(v-xr[0])/(xr[1]-xr[0])*520;
  const cy=(v:number)=>18+(1-(v-yr[0])/(yr[1]-yr[0]))*250;

  return <section className="card moo-panel">
    <div className="card-head"><div><div className="card-title">다목적 최적화 · Pareto 추천</div><div className="card-sub">두 물성을 동시에 다루고, 상충 관계를 보이는 후보 묶음을 제안합니다.</div></div><span className="badge">gpbo-moo-stage3-1</span></div>
    <div className="optimization-mode"><button className={mode==='sandbox'?'active':''} onClick={()=>{setMode('sandbox');setModel(null);setReference('1.1,10.1');setScales('1,1');setBounds(['0,1','0,1'])}}>샌드박스</button><button className={mode==='research'?'active':''} onClick={()=>{setMode('research');setModel(null);setReference('');setScales('');setBounds([])}}>승인된 연구 데이터</button></div>
    {mode==='research'?<>
      <div className="optimization-fields">
        <label>공정 버전<select value={methodId} onChange={e=>setMethodId(Number(e.target.value))}><option value={0}>선택</option>{versions.map(v=><option key={v.id} value={v.id}>{v.label}</option>)}</select></label>
        <label>관측 연결 방식<select value={pairing} onChange={e=>{const next=e.target.value as 'same_step'|'downstream_explicit';setPairing(next);if(next==='same_step')setObjectiveStepId(stepId);setDownstreamConfirmed(false)}}><option value="same_step">같은 공정 단계</option><option value="downstream_explicit">입력 단계 → 후속 측정 단계</option></select></label>
        <label>입력 조건 단계<select value={stepId??''} onChange={e=>{const value=e.target.value?Number(e.target.value):null;setStepId(value);if(pairing==='same_step')setObjectiveStepId(value)}}><option value="">전체 (기록된 동일 단계 기준)</option>{options?.process_steps.map(s=><option key={s.id} value={s.id}>{s.order_index+1}. {s.name}</option>)}</select></label>
        {pairing==='downstream_explicit'&&<><label>목표 측정 단계<select value={objectiveStepId??''} onChange={e=>setObjectiveStepId(e.target.value?Number(e.target.value):null)}><option value="">후속 단계 선택</option>{options?.process_steps.map(s=><option key={s.id} value={s.id}>{s.order_index+1}. {s.name}</option>)}</select></label><label>조건과 결과의 관계 설명<input value={relationLabel} onChange={e=>setRelationLabel(e.target.value)} placeholder="예: 성장 온도와 최종 길이의 연결"/></label><label className="moo-confirm"><input type="checkbox" checked={downstreamConfirmed} onChange={e=>setDownstreamConfirmed(e.target.checked)}/> 이 후속 측정이 선택한 입력 조건의 결과임을 확인합니다.</label></>}
        <fieldset className="optimization-feature-select"><legend>입력 공정 조건</legend>{options?.features.map(f=><label key={f.parameter_id}><input type="checkbox" checked={features.includes(f.parameter_id)} onChange={()=>setFeatures(x=>x.includes(f.parameter_id)?x.filter(v=>v!==f.parameter_id):[...x,f.parameter_id])}/><span>{f.parameter_id}</span><small>{f.unit}</small></label>)}</fieldset>
        {[0,1].map(i=><label key={i}>목표 물성 {i+1}<select value={objectives[i]} onChange={e=>setObjectives(v=>v.map((x,j)=>j===i?e.target.value:x))}><option value="">승인된 측정 결과 선택</option>{options?.outcomes.map(o=><option key={o.parameter_id} value={o.parameter_id}>{o.parameter_id} · {o.unit}</option>)}</select><select value={directions[i]} onChange={e=>setDirections(v=>v.map((x,j)=>j===i?e.target.value as 'minimize'|'maximize':x))}><option value="minimize">최소화</option><option value="maximize">최대화</option></select></label>)}
      </div>
      <div className="optimization-fields">{features.map((id,i)=><label key={id}>{id} 범위 · {options?.features.find(f=>f.parameter_id===id)?.unit??'단위'} (최소,최대)<input value={bounds[i]??'0,1'} onChange={e=>setBounds(v=>{const n=[...v];n[i]=e.target.value;return n})}/></label>)}</div>
    </>:<div className="optimization-note"><b>ZDT1 · 2개 목적</b><span>수학적 합성 데이터로만 검증합니다. 연구 관측 데이터는 생성하거나 변경하지 않습니다.</span><small>x1, x2 ∈ [0, 1] · f1, f2 최소화</small><button className="button" disabled={benchmarkBusy} onClick={()=>void runBenchmark()}>{benchmarkBusy?'다목적 비교 계산 중…':'다목적 알고리즘 비교 실행 · 5개 시드'}</button></div>}
    <div className="optimization-fields moo-budget">
      <label>목적별 방향<input readOnly value={directions.map(x=>x==='minimize'?'최소화':'최대화').join(' · ')}/></label>
      <label>Hypervolume 기준점 (목적1,목적2){mode==='research'&&<small>{objectives.map(id=>options?.outcomes.find(o=>o.parameter_id===id)?.unit??'').join(' · ')} · 관측 Front보다 열등한 기준을 직접 입력</small>}<input value={reference} onChange={e=>setReference(e.target.value)} placeholder={mode==='research'?'예: 0.000001, 0.00001':'1.1, 10.1'}/></label>
      <label>정규화 스케일 (목적1,목적2)<input value={scales} onChange={e=>setScales(e.target.value)} placeholder={mode==='research'?'물성별 양의 스케일':'1, 1'}/></label>
      <label>한 번에 제안할 후보<input type="number" min="1" max="4" value={batchSize} onChange={e=>setBatchSize(Math.max(1,Math.min(4,Number(e.target.value))))}/></label>
      <label>후보 탐색량<input type="number" min="32" max="2000" value={searchBudget} onChange={e=>setSearchBudget(Math.max(32,Math.min(2000,Number(e.target.value))))}/></label>
      <label>Monte Carlo 표본<input type="number" min="32" max="4096" step="32" value={samples} onChange={e=>setSamples(Math.max(32,Math.min(4096,Number(e.target.value))))}/></label>
    </div>
    <button className="button primary" disabled={busy||!topic.id} onClick={()=>void run()}>{busy?'두 GP 학습 및 Pareto 후보 계산 중…':'두 목적 GP 학습 후 후보 묶음 추천'}</button>
    {error&&<div className="error">{error}</div>}
    {model&&<div className="moo-result">
      <div className="optimization-metrics"><Metric label="독립 GP" value={2}/><Metric label="완전한 데이터 행" value={model.config.dataset_count}/><Metric label="Pareto 관측점" value={pareto?.pareto_values?.length}/><Metric label="현재 Hypervolume" value={pareto?.hypervolume}/><Metric label="추천 Batch HV 개선" value={recommendation?.config?.total_expected_batch_hv_improvement??recommendation?.total_expected_batch_hv_improvement}/></div>
      <div className="moo-plot-wrap"><div><b>2차원 Pareto 지도</b><small>두 목적의 전체 관측과 Pareto 경계, 그리고 아직 측정되지 않은 추천 예측값을 함께 표시합니다.</small></div><svg className="moo-plot" viewBox="0 0 590 300" role="img" aria-label="Pareto scatter plot"><line x1="42" y1="268" x2="562" y2="268"/><line x1="42" y1="18" x2="42" y2="268"/><text x="45" y="292">{pareto?.objective_definitions?.[0]?.id} · {pareto?.objective_definitions?.[0]?.unit}</text><text x="4" y="16">{pareto?.objective_definitions?.[1]?.id} · {pareto?.objective_definitions?.[1]?.unit}</text>{pointData.map((p,i)=><g key={`${p.kind}-${i}`}><circle cx={cx(p.x)} cy={cy(p.y)} r={p.kind==='candidate'?8:6} className={p.kind==='pareto'?'moo-observed':p.kind==='dominated'?'moo-dominated':'moo-predicted'}/><title>{`${p.label}: ${p.x.toPrecision(4)}, ${p.y.toPrecision(4)}`}</title></g>)}{pareto?.reference_point&&<g><rect x={cx(pareto.reference_point[0])-5} y={cy(pareto.reference_point[1])-5} width="10" height="10" className="moo-reference"/><title>Hypervolume 기준점</title></g>}</svg><div className="moo-legend"><span><i className="moo-dominated"/>기존 관측</span><span><i className="moo-observed"/>Pareto 최적 관측</span><span><i className="moo-predicted"/>추천 예측값</span><span><i className="moo-reference"/>기준점</span></div></div>
      {recommendation?.candidates?.length>0&&<div className="table-wrap"><table><thead><tr><th>후보</th><th>입력 조건</th><th>목적 1 예측</th><th>목적 2 예측</th><th>한계 개선량</th><th>MC 표준오차</th><th>제약</th><th>검토 상태</th></tr></thead><tbody>{recommendation.candidates.map((c:any,i:number)=><tr key={c.candidate_id??i}><td>{c.candidate_id??`C${i+1}`}</td><td>{(c.parameters??[]).map((v:number)=>v.toPrecision(4)).join(' · ')}</td>{(c.predicted_objectives??[]).map((o:any)=><td key={o.id}>{o.mean.toPrecision(4)} ± {o.predictive_std.toPrecision(3)}</td>)}<td>{c.marginal_expected_hv_improvement.toPrecision(4)}</td><td>± {c.marginal_ehvi_mc_standard_error.toPrecision(3)}</td><td>{c.feasible?'충족':'위반'}</td><td>{c.approval_status==='PENDING_RESEARCHER_REVIEW'?'연구자 검토 대기':c.approval_status}</td></tr>)}</tbody></table></div>}
      <small>Batch 기대 Hypervolume 개선: {Number(recommendation?.config?.total_expected_batch_hv_improvement??recommendation?.total_expected_batch_hv_improvement??0).toPrecision(4)} ± {Number(recommendation?.config?.total_expected_batch_hv_improvement_mc_standard_error??recommendation?.total_expected_batch_hv_improvement_mc_standard_error??0).toPrecision(3)} (Monte Carlo 표준오차)</small>
      <p className="optimization-safety">목적별 독립 GP라 목적 간 출력 상관성은 학습하지 않습니다. 예측 후보는 측정 결과가 아니며, Hypervolume 개선량은 성공 확률이 아닙니다. 실제 실험 실행은 연결되지 않았고 연구자 검토가 필요합니다. 추천 ID: {recommendation?.recommendation_id??'—'}</p>
    </div>}
    {benchmark&&<div className="moo-benchmark"><b>샌드박스 알고리즘 비교</b><small>{benchmark.seeds}개 시드 · 정책마다 총 {benchmark.evaluation_budget}회 목적값 쌍 평가 · 전체 {benchmark.runtime_seconds.toFixed(2)}초 · 프로세스 최대 RSS {(benchmark.peak_rss_bytes_process_high_water/1048576).toFixed(1)} MiB · {benchmark.environment?.os} {benchmark.environment?.architecture} / Python {benchmark.environment?.python}</small>{Object.entries(benchmark.benchmarks).map(([name,data]:[string,any])=><div key={name}><h4>{name}</h4><table><thead><tr><th>방법</th><th>평균 Hypervolume</th><th>기준면 잔차</th><th>Pareto 수</th><th>중복률</th><th>후보 거리</th><th>중앙 실행시간</th></tr></thead><tbody>{Object.entries(data.policies).map(([policy,values]:[string,any])=><tr key={policy}><td>{policy}</td><td>{values.mean_hypervolume.toPrecision(5)}</td><td>{values.mean_hypervolume_regret_to_reference.toPrecision(5)}</td><td>{values.median_pareto_front_size}</td><td>{(values.duplicate_candidate_rate*100).toFixed(1)}%</td><td>{values.batch_diversity_mean_distance.toPrecision(4)}</td><td>{values.median_runtime_seconds.toFixed(3)} s</td></tr>)}</tbody></table><small>Reference: {data.reference_front_source} · {JSON.stringify(data.reference_point)}</small></div>)}<p className="optimization-safety">{benchmark.notice} · RSS는 서버 프로세스 전체의 최고 메모리 값이며 이 benchmark가 추가로 사용한 메모리만 뜻하지 않습니다.</p></div>}
  </section>;
}

function Metric({label,value}:{label:string;value:number|undefined}){return <div className="optimization-metric"><small>{label}</small><b>{typeof value==='number'?value.toPrecision(5):'—'}</b></div>}
