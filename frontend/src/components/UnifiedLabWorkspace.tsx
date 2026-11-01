import { lazy, Suspense, useMemo, useState } from 'react';
import { Activity, Beaker, BrainCircuit, FlaskConical, Microscope, TrendingUp } from 'lucide-react';
import type { Experiment, ResearchTopic } from '../types';
import { useLanguage } from '../language';
import MethodWorkspace from './MethodWorkspace';

const AnalysisPanel = lazy(() => import('./AnalysisPanel'));
const DecisionPanel = lazy(() => import('./DecisionPanel'));
const OptimizationPanel = lazy(() => import('./OptimizationPanel'));
const CampaignPanel = lazy(() => import('./CampaignPanel'));

type Stage = 'record' | 'measure' | 'decision';
type DecisionView = 'decision' | 'optimization' | 'campaign';

export default function UnifiedLabWorkspace({ topic, experiments, onChanged, onExperimentsChanged }: {
  topic: ResearchTopic; experiments: Experiment[]; onChanged: () => void; onExperimentsChanged: () => void;
}) {
  const { language } = useLanguage();
  const ko = language === 'ko';
  const [stage, setStage] = useState<Stage>('record');
  const [decisionView, setDecisionView] = useState<DecisionView>('decision');
  const [experimentId, setExperimentId] = useState<number | null>(null);
  const availableExperiments = useMemo(() => experiments.filter(item => !item.demo), [experiments]);
  const selected = availableExperiments.find(item => item.id === experimentId) ?? availableExperiments[0] ?? null;
  const stages: { id: Stage; label: string; icon: typeof FlaskConical }[] = [
    { id: 'record', label: ko ? '실험·공정' : 'Experiment · Process', icon: FlaskConical },
    { id: 'measure', label: ko ? '측정·분석' : 'Measurement · Analysis', icon: Microscope },
    { id: 'decision', label: ko ? '판단·추천' : 'Decision · Recommendation', icon: BrainCircuit },
  ];
  return <section className="unified-workspace" aria-label={ko ? '통합 연구 작업공간' : 'Unified laboratory workspace'}>
    <header className="card unified-context">
      <div className="unified-context-top"><div><div className="eyebrow">{ko ? '선택한 연구 주제' : 'RESEARCH TOPIC'}</div><h2>{topic.name}</h2><p>{ko ? '실험을 고르면 공정, 측정, 판단, 추천 화면이 같은 실험 맥락을 이어받습니다.' : 'Choose an experiment to carry its context into process, measurement, decision, and recommendation views.'}</p></div>
        <label className="unified-experiment-picker">{ko ? '작업할 실험' : 'Active experiment'}<select value={selected?.id ?? ''} onChange={event => setExperimentId(Number(event.target.value) || null)}><option value="">{ko ? '실험 선택' : 'Select an experiment'}</option>{availableExperiments.map(item => <option key={item.id} value={item.id}>{item.code} · {item.name} · {item.date || (ko ? '날짜 미기록' : 'date not recorded')}</option>)}</select></label>
      </div>
      <div className="unified-context-stats">
        <span><b>{availableExperiments.length}</b>{ko ? '실험 기록' : 'experiment records'}</span>
        <span><b>{topic.methods.length}</b>{ko ? '공정 방법' : 'process methods'}</span>
        <span><b>{selected?.steps.length ?? 0}</b>{ko ? '선택 실험 단계' : 'steps in selected experiment'}</span>
        <span><b>{selected?.results.length ?? 0}</b>{ko ? '기록 결과' : 'recorded results'}</span>
      </div>
      {selected && <div className="unified-selected-record"><div><span className={`status ${selected.status}`}>{ko ? selected.status : selected.status.replaceAll('_', ' ')}</span><b>{selected.code} · {selected.name}</b><small>{selected.method_name || (ko ? '공정 미연결' : 'No process linked')} · {selected.date || (ko ? '날짜 미기록' : 'date not recorded')}</small></div><div className="unified-data-chips">{selected.results.slice(0, 5).map((result, index) => <span key={`${result.key}-${index}`}><b>{result.key.replaceAll('_', ' ')}</b> {String(result.value)}{result.unit ? ` ${result.unit}` : ''}<small>{ko ? '기록 결과' : 'recorded result'}</small></span>)}{!selected.results.length && <small>{ko ? '아직 결과가 없습니다. 실제 측정값이나 관찰 결과는 실험 기록에서 저장하세요.' : 'No outcomes yet. Save actual measurements or observations to this experiment.'}</small>}</div></div>}
    </header>
    <nav className="unified-stage-nav" aria-label={ko ? '연구 작업 단계' : 'Research workflow stages'}>{stages.map(({ id, label, icon: Icon }, index) => <button key={id} type="button" className={`unified-stage ${stage === id ? 'active' : ''}`} aria-current={stage === id ? 'step' : undefined} onClick={() => setStage(id)}><span>{index + 1}</span><Icon size={17}/>{label}</button>)}</nav>
    {stage === 'record' && <section className="unified-stage-panel"><div className="unified-stage-heading"><div><div className="eyebrow">01 · {ko ? '기록' : 'RECORD'}</div><h3>{ko ? '실험과 공정 조건' : 'Experiment and process conditions'}</h3><p>{ko ? '방법과 공정 버전을 관리하고, 날짜별 실행 기록과 조건을 이어서 입력합니다.' : 'Manage methods and process versions, then record dated runs and conditions.'}</p></div><span className="data-origin-label raw">{ko ? '실험 기록' : 'LAB RECORD'}</span></div><MethodWorkspace topic={topic} onChanged={onChanged} activeExperimentId={selected?.id}/></section>}
    {stage === 'measure' && <section className="unified-stage-panel"><div className="unified-stage-heading"><div><div className="eyebrow">02 · {ko ? '측정·분석' : 'MEASURE & ANALYZE'}</div><h3>{ko ? '선택한 실험의 측정과 분석' : 'Measurements and analysis for this experiment'}</h3><p>{ko ? '원본 측정 파일, 계산된 분석 결과, 검토 상태는 각각의 출처와 함께 표시됩니다. 주제 통합 분석은 해당 주제의 저장 데이터를 사용합니다.' : 'Raw files, computed analysis, and review status retain their own provenance. Topic synthesis uses saved data from this research topic.'}</p></div><span className="data-origin-label computed">{ko ? '계산 결과는 실측과 분리' : 'COMPUTED ≠ MEASURED'}</span></div>
      {selected ? <div className="unified-record-conditions"><b>{ko ? '현재 연결된 공정 조건' : 'Linked process conditions'}</b>{selected.steps.map(step => <div key={step.id}><strong>{step.order_index + 1}. {step.name}</strong><span>{step.variables.map(variable => `${variable.name.replaceAll('_', ' ')}: ${variable.value}${variable.unit ? ` ${variable.unit}` : ''}`).join(' · ') || (ko ? '기록된 조건 없음' : 'No recorded conditions')}</span></div>)}</div> : <div className="empty-hint">{ko ? '실험을 먼저 등록하면 이곳에서 측정과 분석 맥락을 확인할 수 있습니다.' : 'Register an experiment to see its measurement and analysis context here.'}</div>}
      <Suspense fallback={<div className="loading-panel">{ko ? '분석 작업공간을 여는 중…' : 'Opening analysis workspace…'}</div>}><AnalysisPanel key={`${topic.id}-${selected?.id ?? 'none'}`} experiments={experiments} topicId={topic.id} initialExperimentId={selected?.id} onExperimentCreated={onExperimentsChanged} onOpenMethods={() => setStage('record')}/></Suspense>
    </section>}
    {stage === 'decision' && <section className="unified-stage-panel"><div className="unified-stage-heading"><div><div className="eyebrow">03 · {ko ? '판단·추천' : 'DECIDE & PLAN'}</div><h3>{ko ? '근거를 확인하고 다음 조건을 검토' : 'Review evidence and next-condition candidates'}</h3><p>{ko ? '규칙, JEV, 모델 예측, 최적화 후보를 구분해 표시합니다. 추천은 연구자 검토 후에만 다음 실험으로 이어집니다.' : 'Rule decisions, JEV output, model predictions, and candidates are labeled separately. A researcher reviews each candidate before the next run.'}</p></div><span className="data-origin-label prediction">{ko ? '승인 전 예측' : 'PREDICTION · REVIEW REQUIRED'}</span></div>
      <div className="unified-subnav" role="tablist" aria-label={ko ? '판단 및 추천 도구' : 'Decision and recommendation tools'}>{([{id:'decision',label:ko?'AI 판단':'AI decision',icon:Activity},{id:'optimization',label:ko?'최적화':'Optimization',icon:TrendingUp},{id:'campaign',label:ko?'캠페인·검토':'Campaign · review',icon:Beaker}] as const).map(({id,label,icon:Icon})=><button type="button" role="tab" aria-selected={decisionView===id} className={decisionView===id?'active':''} key={id} onClick={()=>setDecisionView(id)}><Icon size={15}/>{label}</button>)}</div>
      {decisionView === 'decision' && <Suspense fallback={<div className="loading-panel">Loading decision view…</div>}><DecisionPanel key={`${topic.id}-${selected?.id ?? 'none'}`} topicId={topic.id} experiments={experiments} initialExperimentId={selected?.id}/></Suspense>}
      {decisionView === 'optimization' && <Suspense fallback={<div className="loading-panel">Loading optimizer…</div>}><OptimizationPanel key={`${topic.id}-${selected?.method_version_id ?? 'none'}`} topic={topic} initialMethodVersionId={selected?.method_version_id ?? undefined}/></Suspense>}
      {decisionView === 'campaign' && <Suspense fallback={<div className="loading-panel">Loading campaign…</div>}><CampaignPanel key={`${topic.id}-${selected?.id ?? 'none'}`} topicId={topic.id} experiments={experiments} initialExperimentId={selected?.id}/></Suspense>}
    </section>}
  </section>;
}
