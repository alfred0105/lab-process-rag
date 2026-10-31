import { useEffect, useMemo, useState } from 'react';
import type { Experiment } from '../types';
import { learnedDecisionApi } from '../api/client';
import { useLanguage } from '../language';

const ACTIONS=['REQUEST_INFORMATION','ANALYZE','SIMULATE','OPTIMIZE','REQUEST_REVIEW','ABSTAIN'] as const;
const ACTION_KO:Record<string,string>={REQUEST_INFORMATION:'추가 정보 요청',ANALYZE:'측정 데이터 분석',SIMULATE:'시뮬레이션',OPTIMIZE:'조건 최적화',REQUEST_REVIEW:'연구자 검토 요청',ABSTAIN:'판단 보류'};
const FEEDBACK_KO:Record<string,string>={ACCEPT:'추천 승인',CORRECT:'다른 행동으로 수정',REJECT:'추천 거부',UNSURE:'판단 보류'};
type Mode='sandbox'|'research';

export default function DecisionPanel({topicId,experiments}:{topicId:number;experiments:Experiment[]}){
  const {language}=useLanguage();const ko=language==='ko';
  const [mode,setMode]=useState<Mode>('sandbox');
  const [readiness,setReadiness]=useState<any>(null);const [cases,setCases]=useState<any[]>([]);const [datasets,setDatasets]=useState<any[]>([]);const [feedbackHistory,setFeedbackHistory]=useState<any[]>([]);
  const [active,setActive]=useState<any>(null);const [model,setModel]=useState<any>(null);const [comparison,setComparison]=useState<any>(null);
  const [result,setResult]=useState<any>(null);const [experimentId,setExperimentId]=useState<number>(experiments.find(x=>!x.demo)?.id??0);
  const [stage3Schema,setStage3Schema]=useState<any>(null);const [stage3Features,setStage3Features]=useState<any>(null);const [stage3Benchmark,setStage3Benchmark]=useState<any>(null);const [stage3Dataset,setStage3Dataset]=useState<any>(null);const [stage3Model,setStage3Model]=useState<any>(null);const [stage3Prediction,setStage3Prediction]=useState<any>(null);
  const [caseId,setCaseId]=useState<number>(0);const [datasetId,setDatasetId]=useState<number>(0);const [action,setAction]=useState<string>('');
  const [feedbackType,setFeedbackType]=useState<'ACCEPT'|'CORRECT'|'REJECT'|'UNSURE'>('ACCEPT');const [reviewer,setReviewer]=useState('');
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('');
  const t=(koText:string,enText:string)=>ko?koText:enText;
  const experimentsForTopic=useMemo(()=>experiments.filter(x=>!x.demo),[experiments]);
  const load=async()=>{
    try{
      const [ready,caseRows,datasetRows,activeRow,feedbackRows]=await Promise.all([
        learnedDecisionApi.readiness(topicId),learnedDecisionApi.cases(topicId,mode),learnedDecisionApi.datasets(topicId,mode),learnedDecisionApi.active(topicId,mode),learnedDecisionApi.feedbackHistory(topicId),
      ]);
      setReadiness(ready);setCases(caseRows);setDatasets(datasetRows);setActive(activeRow);setFeedbackHistory(feedbackRows);
      if(caseRows.length&&!caseRows.some(x=>x.case_id===caseId))setCaseId(caseRows[0].case_id);
      if(datasetRows.length&&!datasetRows.some(x=>x.dataset_version_id===datasetId))setDatasetId(datasetRows[0].dataset_version_id);
    }catch(e){setError(e instanceof Error?e.message:String(e))}
  };
  useEffect(()=>{void load()},[topicId,mode]);
  useEffect(()=>{learnedDecisionApi.stage3Schema().then(setStage3Schema).catch(e=>setError(e instanceof Error?e.message:String(e)))},[]);
  useEffect(()=>{if(!experimentsForTopic.some(x=>x.id===experimentId)&&experimentsForTopic.length)setExperimentId(experimentsForTopic[0].id)},[experimentsForTopic,experimentId]);
  const run=async(task:()=>Promise<any>,message?:string)=>{
    setBusy(true);setError('');setNotice('');
    try{const value=await task();if(value?.model_id&&value?.metrics){setModel(value);setComparison(null)}if(value?.decision_snapshot||value?.learned)setResult(value);if(value?.comparison_id)setComparison(value);setNotice(message??'');await load();return value}
    catch(e){setError(e instanceof Error?e.message:String(e));return null}finally{setBusy(false)}
  };
  const seed=()=>void run(()=>learnedDecisionApi.seedSandbox(topicId),t('합성 소프트웨어 테스트 케이스를 만들었습니다. 실제 연구 결정이 아닙니다.','Synthetic software fixtures created. These are not real research decisions.'));
  const buildDataset=()=>void run(async()=>{const value=await learnedDecisionApi.buildDataset({topic_id:topicId,mode});setDatasetId(value.dataset_version_id);return value},t('불변 데이터셋 버전을 만들었습니다.','Immutable dataset version created.'));
  const retrain=()=>void run(async()=>{
    const selected=datasets.find(x=>x.dataset_version_id===datasetId);
    if(!selected)throw new Error(t('먼저 데이터셋 버전을 만드세요.','Build a dataset version first.'));
    const parentId=active?.model?.model_id??null;
    return learnedDecisionApi.retrain({dataset_version_id:datasetId,parent_model_id:parentId,seed:7});
  },t('새 모델을 학습하고 고정 평가 데이터로 검증했습니다.','New model trained and evaluated on the frozen holdout.'));
  const compare=()=>void run(()=>learnedDecisionApi.compare(mode==='sandbox'
    ?{topic_id:topicId,model_id:model?.model_id??active?.model?.model_id,case_id:caseId}
    :{topic_id:topicId,model_id:model?.model_id??active?.model?.model_id,experiment_id:experimentId}),t('모델은 Shadow Mode로만 판단했습니다. 실험 과정은 실행하지 않았습니다.','Model ran in shadow mode only; no experiment workflow was executed.'));
  const saveFeedback=()=>void run(()=>{
    const snapshot=result?.decision_snapshot;
    if(!snapshot?.snapshot_id)throw new Error(t('먼저 실험 상태를 비교해 판단 스냅샷을 만드세요.','Compare a state first to create a decision snapshot.'));
    return learnedDecisionApi.feedback({snapshot_id:snapshot.snapshot_id,model_id:snapshot.model_id,
      feedback_type:feedbackType,final_reviewed_action:feedbackType==='CORRECT'||feedbackType==='REJECT'?(action||null):null,
      reviewer,review_reason:''});
  },t('피드백을 수정 이력과 함께 기록했습니다.','Feedback saved as an append-only revision.'));
  const compareModels=()=>void run(()=>learnedDecisionApi.compareModels({topic_id:topicId,
    champion_model_id:active?.model?.model_id,challenger_model_id:model?.model_id}),t('두 모델을 같은 고정 평가 데이터에서 비교했습니다.','Compared both models on the same frozen evaluation set.'));
  const activate=()=>void run(()=>learnedDecisionApi.activate({topic_id:topicId,model_id:model?.model_id,
    comparison_id:comparison?.comparison_id??null,reviewer,reason:t('평가 확인 후 연구자가 Shadow 모델로 선택함','Researcher selected as shadow model after reviewing the evaluation.')}),t('Shadow 모델을 변경했습니다. 실행 권한은 부여되지 않았습니다.','Shadow model changed. No execution permission was granted.'));
  const rollback=()=>void run(()=>learnedDecisionApi.rollback({topic_id:topicId,mode,reviewer,reason:t('이전 Shadow 모델로 복구','Restore previous shadow model.')}),t('이전 Shadow 모델로 복구했습니다.','Previous shadow model restored.'));
  const inspectV2=()=>void run(async()=>{const v=await learnedDecisionApi.stage3Features({topic_id:topicId,...(mode==='research'?{experiment_id:experimentId}:{case_id:caseId})});setStage3Features(v);return v});
  const buildV2=()=>void run(async()=>{const v=await learnedDecisionApi.stage3BuildDataset({topic_id:topicId,mode,holdout_strategy:'experiment'});setStage3Dataset(v);return v});
  const trainV2=()=>void run(async()=>{if(!stage3Dataset?.dataset_version_id)throw new Error(t('먼저 V2 데이터셋을 만드세요.','Build a V2 dataset first.'));const v=await learnedDecisionApi.stage3Retrain({dataset_version_id:stage3Dataset.dataset_version_id,seed:7,parent_model_id:null});setStage3Model(v);return v});
  const predictV2=()=>void run(async()=>{if(!stage3Model?.model_id)throw new Error(t('먼저 V2 모델을 학습하세요.','Train a V2 model first.'));const v=await learnedDecisionApi.stage3Predict(stage3Model.model_id,{topic_id:topicId,...(mode==='research'?{experiment_id:experimentId}:{case_id:caseId})});setStage3Prediction(v);return v});
  const benchmarkV2=()=>void run(async()=>{const v=await learnedDecisionApi.stage3Benchmark();setStage3Benchmark(v);return v},t('5개 고정 시드 벤치마크를 완료했습니다. 합성 소프트웨어 검증이며 실제 연구 성능이 아닙니다.','Five-seed benchmark completed. This is synthetic software validation, not real research performance.'));
  const metrics=model?.metrics;
  const selectedDataset=datasets.find(x=>x.dataset_version_id===datasetId);
  return <div className="decision-panel">
    <section className="card">
      <div className="card-head"><div><div className="card-title">{t('실험 판단 학습 관리','Decision feedback & model learning')}</div><div className="card-sub">{t('AI 추천은 검토용으로만 제공됩니다. 피드백은 불변 스냅샷에 연결되고, 재학습과 Shadow 모델 교체는 연구자가 직접 결정합니다.','Recommendations are advisory. Feedback is attached to immutable snapshots, and researchers explicitly request retraining and shadow-model changes.')}</div></div><span className="history-tag">SHADOW ONLY</span></div>
      <div className="decision-workflow"><span>{t('실험 상태','Experiment state')}</span><b>→</b><span>{t('AI 추천','AI suggestion')}</span><b>→</b><span>{t('연구자 피드백','Researcher feedback')}</span><b>→</b><span>{t('버전 모델 비교','Versioned model review')}</span></div>
      <div className="decision-controls"><label>{t('학습 자료 종류','Dataset mode')}<select value={mode} onChange={e=>{setMode(e.target.value as Mode);setResult(null);setModel(null);setComparison(null)}}><option value="sandbox">{t('합성 소프트웨어 테스트','Synthetic software sandbox')}</option><option value="research">{t('검토된 연구 기록','Reviewed research records')}</option></select></label>
        {mode==='sandbox'&&<button className="button secondary" disabled={busy} onClick={seed}>{t('합성 테스트 데이터 만들기','Create synthetic fixtures')}</button>}
        <button className="button secondary" disabled={busy} onClick={buildDataset}>{t('데이터 버전 만들기','Build dataset version')}</button>
        <button className="button primary" disabled={busy||!selectedDataset} onClick={retrain}>{busy?t('처리 중…','Working…'):t('새 모델 학습','Train new model')}</button></div>
      {readiness&&<div className="decision-readiness"><article><small>{t('검토된 연구자 레이블','Reviewed research labels')}</small><b>{readiness.research.reviewed_case_count} / {readiness.research.minimum_groups} {t('독립 사례','independent cases')}</b><span>{readiness.research.status}</span></article><article><small>{t('합성 테스트 케이스','Synthetic test cases')}</small><b>{readiness.sandbox.case_count}</b><span>{readiness.sandbox.status}</span></article><article><small>{t('피드백 기록','Feedback revisions')}</small><b>{readiness.feedback_revision_count}</b><span>{t('현재 학습 가능','Currently eligible')}: {readiness.eligible_feedback_count}</span></article><article><small>{t('학습 가능한 그룹','Eligible independent groups')}</small><b>{selectedDataset?.group_count??readiness.research.independent_group_count}</b><span>{selectedDataset?.dataset_hash?.slice(0,12)??'—'}</span></article></div>}
      {mode==='research'&&readiness?.research.status!=='READY'&&<p className="decision-caution">{t('검토된 연구 사례가 부족합니다. 연구 모드 학습은 현재 보류됩니다. Reviewer 이름은 인증된 신원이 아닙니다.','There are not enough reviewed research cases. Research training is blocked. Reviewer names are not authenticated identities.')}</p>}
      {selectedDataset&&<div className="decision-baselines"><b>{selectedDataset.dataset_version} · {selectedDataset.case_count} {t('사례','cases')}</b><span>SHA-256: {selectedDataset.dataset_hash}</span><span>{t('고정 평가 사례','Frozen evaluation cases')}: {selectedDataset.evaluation_case_count} · {selectedDataset.evaluation_hash}</span><span>{t('출처','Sources')}: {selectedDataset.source_summary?.label_sources?.join(', ')}</span><span>{t('행동별 레이블','Action labels')}: {Object.entries(selectedDataset.action_distribution??{}).filter(([,count])=>Number(count)>0).map(([name,count])=>`${ko?ACTION_KO[name]:name} ${count}`).join(' · ')||'—'}</span></div>}
      {error&&<p className="error">{error}</p>}{notice&&<p className="decision-notice">{notice}</p>}
    </section>

    <section className="card">
      <div className="card-head"><div><div className="card-title">{t('과학 상태 판단 V2','Scientific state decision V2')}</div><div className="card-sub">{stage3Schema?.schema_version??'scientific-decision-features-v2'} · {stage3Schema?.feature_count??'—'} {t('특징 · Shadow 전용','features · shadow only')}</div></div><span className="history-tag">V2</span></div>
      <p className="decision-caution">{t('이 모델은 기록된 상태를 구조화해 다음 행동을 제안합니다. 도구·시뮬레이션·실험을 자동 실행하지 않습니다.','This model structures recorded state and suggests a next action. It does not run tools, simulations or experiments.')}</p>
      <div className="decision-controls">
        <button className="button secondary" disabled={busy||(!experimentId&&mode==='research')||(!caseId&&mode==='sandbox')} onClick={inspectV2}>{t('현재 상태 확인','Inspect current state')}</button>
        <button className="button secondary" disabled={busy} onClick={buildV2}>{t('V2 데이터셋 만들기','Build V2 dataset')}</button>
        <button className="button primary" disabled={busy||!stage3Dataset?.dataset_version_id} onClick={trainV2}>{t('V2 모델 학습','Train V2 model')}</button>
        <button className="button secondary" disabled={busy||!stage3Model?.model_id||(!experimentId&&mode==='research')||(!caseId&&mode==='sandbox')} onClick={predictV2}>{t('V2 shadow 판단','Run V2 shadow decision')}</button>
        <button className="button outline" disabled={busy} onClick={benchmarkV2}>{t('5-seed 견고성 평가','Run five-seed robustness benchmark')}</button>
      </div>
      {stage3Features&&<div className="decision-baselines"><b>{t('상태 특징 추출 완료','State features extracted')} · {stage3Features.feature_count}</b><span>{t('누락 특징','Missing features')}: {stage3Features.metadata?.missing_feature_count} · {stage3Features.metadata?.unit_normalization?.status??'—'}</span><span>{t('ID는 추적에만 쓰고 모델 특징에는 넣지 않습니다.','IDs are retained for traceability and excluded from model features.')}</span></div>}
      {stage3Prediction&&<div className="decision-result-summary"><article><small>{t('V2 제안 행동','V2 suggested action')}</small><b>{ko?ACTION_KO[stage3Prediction.action]:stage3Prediction.action}</b><span>{stage3Prediction.ood_status} · {stage3Prediction.mode} · {stage3Prediction.safety_override_reason??t('연구자 검토 필요','Researcher review required')}</span></article><article><small>{t('버전 및 상태','Version & state')}</small><b>{stage3Prediction.model_version}</b><span>{stage3Prediction.feature_schema_version} · {t('실행되지 않음','not executed')}</span></article></div>}
      {stage3Benchmark&&<div className="decision-baselines"><b>{t('합성 소프트웨어 벤치마크','Synthetic software benchmark')} · {stage3Benchmark.seed_count} seeds</b><span>{t('V1 정확도 평균','V1 mean accuracy')}: {Number(stage3Benchmark.summary?.v1?.accuracy?.mean).toFixed(3)} · Macro F1 {Number(stage3Benchmark.summary?.v1?.macro_f1?.mean).toFixed(3)}</span><span>{t('V2 정확도 평균','V2 mean accuracy')}: {Number(stage3Benchmark.summary?.v2?.accuracy?.mean).toFixed(3)} · Macro F1 {Number(stage3Benchmark.summary?.v2?.macro_f1?.mean).toFixed(3)}</span><span>{t('상태','Status')}: {stage3Benchmark.benchmark_status} · {t('실제 과학 정확도 검증 아님','not a validation of scientific accuracy')}</span></div>}
      {stage3Model&&<div className="decision-baselines"><b>{stage3Model.model_version} · {stage3Model.status}</b><span>{t('파라미터','Parameters')}: {stage3Model.metrics?.model_parameter_count} · {t('평가 표본','Evaluation cases')}: {stage3Model.metrics?.sample_count}</span></div>}
    </section>

    {metrics&&<section className="card"><div className="card-head"><div><div className="card-title">{t('학습 모델 평가','Learned model evaluation')}</div><div className="card-sub">{model.model_version} · {model.mode.toUpperCase()} · {model.dataset_version} · {metrics.sample_count} {t('고정 평가 사례','frozen evaluation cases')}</div></div><span className="history-tag">{model.status}</span></div>
      <div className="decision-metrics"><Metric label={t('정확도','Accuracy')} value={metrics.accuracy}/><Metric label="Macro F1" value={metrics.macro_f1}/><Metric label="Brier" value={metrics.brier_score}/><Metric label="ECE · 10 bins" value={metrics.expected_calibration_error_10_bins}/><Metric label={t('보류 비율','Abstention rate')} value={metrics.abstention_rate??'—'}/><Metric label={t('모델 크기','Model size')} value={`${metrics.model_size_bytes} B`}/></div>
      <p className="decision-caution">{t('합성 점수는 실제 연구 성능이 아닙니다. 연구자 이름은 자체 입력값이며 인증된 전문가 레이블로 표시되지 않습니다.','Synthetic scores are not research performance. Reviewer names are self-entered and are not authenticated expert labels.')}</p>
      <div className="decision-controls"><label>{t('비데모 실험','Non-demo experiment')}<select value={experimentId} onChange={e=>setExperimentId(Number(e.target.value))}><option value="0">{t('실험 선택','Select experiment')}</option>{experimentsForTopic.map(x=><option key={x.id} value={x.id}>{x.code} · {x.name}</option>)}</select></label>
        {mode==='sandbox'&&<label>{t('합성 상태','Synthetic state')}<select value={caseId} onChange={e=>setCaseId(Number(e.target.value))}>{cases.filter(x=>x.label_source==='SYNTHETIC_SANDBOX').map(x=><option key={x.case_id} value={x.case_id}>#{x.case_id} · {x.label} · {x.group_id}</option>)}</select></label>}
        <button className="button primary" disabled={busy||!model||!(mode==='sandbox'?caseId:experimentId)} onClick={compare}>{t('현재 모델로 상태 판단','Run model on this state')}</button></div>
    </section>}

    {result&&<section className="card"><div className="card-head"><div><div className="card-title">{t('연구자 검토와 피드백','Researcher review & feedback')}</div><div className="card-sub">{t('결정 시점 상태를 고정 저장했습니다. 이후 측정 데이터가 추가돼도 이 스냅샷은 바뀌지 않습니다.','The state at decision time is stored immutably; later measurements cannot change this snapshot.')}</div></div><span className="history-tag">{result.model_mode} · {result.decision_snapshot?.snapshot_hash?.slice(0,12)}</span></div>
      <div className="decision-result-summary"><article><small>{t('학습 모델 추천','Learned recommendation')}</small><b>{ko?ACTION_KO[result.learned?.action]:result.learned?.action}</b><span>{t('점수','Score')}: {Number(result.learned?.confidence).toFixed(3)} · {result.learned?.ood_status}</span></article><article><small>{t('규칙 기준선','Rule baseline')}</small><b>{ko?ACTION_KO[result.rule_based?.action]:result.rule_based?.action}</b><span>{result.agreement?t('일치','Agreement'):t('불일치','Disagreement')} · {t('실행 안 함','Not executed')}</span></article></div>
      <div className="decision-probabilities">{Object.entries(result.learned?.action_probabilities??{}).map(([name,value])=><span key={name}>{ko?ACTION_KO[name]:name}<b>{(Number(value)*100).toFixed(1)}%</b></span>)}</div>
      <div className="decision-controls"><label>{t('피드백 종류','Feedback')}<select value={feedbackType} onChange={e=>setFeedbackType(e.target.value as typeof feedbackType)}>{(['ACCEPT','CORRECT','REJECT','UNSURE'] as const).map(x=><option key={x} value={x}>{ko?FEEDBACK_KO[x]:x}</option>)}</select></label>
        {(feedbackType==='CORRECT'||feedbackType==='REJECT')&&<label>{t('최종 판단 행동 (거부는 비워도 됨)','Final reviewed action (optional for reject)')}<select value={action} onChange={e=>setAction(e.target.value)}><option value="">{t('정답 미지정','No final label')}</option>{ACTIONS.map(x=><option key={x} value={x}>{ko?ACTION_KO[x]:x}</option>)}</select></label>}
        <label>{t('검토자 이름','Reviewer name')}<input value={reviewer} onChange={e=>setReviewer(e.target.value)}/></label>
        <button className="button secondary" disabled={busy||reviewer.trim().length<2||(feedbackType==='CORRECT'&&!action)} onClick={saveFeedback}>{t('피드백 저장','Save feedback')}</button></div>
      <small>{t('승인·수정·거부·보류 이력은 누적됩니다. 정답이 명확한 승인·수정과 최종 행동을 고른 거부만 학습 레이블이 될 수 있습니다.','Feedback revisions are append-only. Accept/correct and reject-with-final-action can become labels; unsure and label-free rejection cannot.')}</small>
      {feedbackHistory.length>0&&<div className="decision-feedback-history"><b>{t('최근 피드백 이력','Recent feedback history')}</b>{feedbackHistory.slice(0,5).map((item:any)=><span key={item.feedback_id}>#{item.feedback_id} · {item.feedback_type} v{item.revision} · {item.reviewer_identity_status} · {new Date(item.created_at).toLocaleString(ko?'ko-KR':'en-US')}</span>)}</div>}
    </section>}

    {datasets.length>0&&<section className="card"><div className="card-head"><div><div className="card-title">{t('Champion · Challenger 검토','Champion · Challenger review')}</div><div className="card-sub">{t('동일한 고정 평가 데이터만 사용합니다. 모드가 다른 모델은 비교하거나 승격할 수 없습니다.','Uses the same frozen evaluation set. Models from different modes cannot be compared or promoted together.')}</div></div></div>
      <div className="decision-readiness"><article><small>{t('현재 Shadow 모델','Active shadow model')}</small><b>{active?.model?.model_version??t('아직 없음','None')}</b><span>{active?.model?.model_id?`${active.model.model_id} · ${active.model.dataset_version}`:t('최초 모델은 평가 후 명시적으로 선택','First model requires explicit selection')}</span></article><article><small>{t('후보 모델','Challenger')}</small><b>{model?.model_version??'—'}</b><span>{model?.dataset_version??'—'}</span></article><article><small>{t('마지막 비교','Latest comparison')}</small><b>{comparison?.status??'—'}</b><span>{comparison?.reason??'—'}</span></article></div>
      <div className="decision-controls"><button className="button secondary" disabled={busy||!active?.model||!model||active.model.model_id===model.model_id} onClick={compareModels}>{t('같은 평가셋에서 비교','Compare on the frozen set')}</button>
        <button className="button primary" disabled={busy||!model||model.status==='SHADOW_ACTIVE'||(active?.model&&(!comparison||!['IMPROVED','COMPARABLE'].includes(comparison.status)))} onClick={activate}>{t('Shadow 모델로 적용','Set as shadow model')}</button>
        <button className="button outline" disabled={busy||!active?.model||!active?.activation_history?.some((x:any)=>x.previous_model_id)} onClick={rollback}>{t('이전 모델로 복구','Rollback to previous model')}</button></div>
      <p className="decision-caution">{t('모델 활성화는 Shadow 추천 모델만 바꿉니다. 실제 공정·도구·장비 실행을 시작하지 않습니다.','Activation changes only the shadow recommendation model. It never starts a process, tool or instrument.')}</p>
    </section>}
  </div>;
}

function Metric({label,value}:{label:string;value:number|string}){return <article><small>{label}</small><b>{typeof value==='number'?value.toFixed(3):value}</b></article>}
