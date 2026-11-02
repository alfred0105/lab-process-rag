import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Activity, Beaker, GitCompare, Microscope, Network, Settings2 } from 'lucide-react';
import { Background, Controls, MiniMap, Position, ReactFlow, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api } from '../api/client';
import type { AnalysisRun, Experiment, ExperimentMethod, MethodVersion, ResearchTopic, Step } from '../types';
import { useLanguage } from '../language';
import MethodWorkspace from './MethodWorkspace';

const AnalysisPanel = lazy(() => import('./AnalysisPanel'));
const DecisionPanel = lazy(() => import('./DecisionPanel'));
const OptimizationPanel = lazy(() => import('./OptimizationPanel'));
const CampaignPanel = lazy(() => import('./CampaignPanel'));

type Area = 'process' | 'analysis' | 'decision' | 'optimization' | 'campaign';
type Layer = 'method' | 'run' | 'analysis';
type CompareResult = { same_variables: CompareItem[]; different_variables: CompareItem[]; missing_variables: CompareItem[]; unresolved_variables: CompareItem[]; comparison_context?: { comparison_status?: string; comparison_mode?: string; same_method_version?: boolean } };
type CompareItem = { key: string; name: string; step_name: string; step_order: number; experiment_a?: unknown; experiment_b?: unknown; unit_a?: string | null; unit_b?: string | null; unit?: string | null; reason?: string; comparison?: { comparable?: boolean; same?: boolean; reason?: string } };

export default function UnifiedLabWorkspace({ topic, experiments, onChanged, onExperimentsChanged }: {
  topic: ResearchTopic; experiments: Experiment[]; onChanged: () => void; onExperimentsChanged: () => void;
}) {
  const { language, t } = useLanguage();
  const ko = language === 'ko';
  const [area, setArea] = useState<Area>('process');
  const [layer, setLayer] = useState<Layer>('run');
  const [methodId, setMethodId] = useState<number | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [compareId, setCompareId] = useState<number | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<number | string | null>(null);
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [compareError, setCompareError] = useState('');
  const [analysisRuns, setAnalysisRuns] = useState<AnalysisRun[]>([]);
  const [inspectorTab, setInspectorTab] = useState<'conditions' | 'source' | 'records'>('conditions');
  const [showEditor, setShowEditor] = useState(false);

  const method = topic.methods.find(item => item.id === methodId) ?? topic.methods[0] ?? null;
  const version = method?.versions.find(item => item.id === versionId) ?? latestVersion(method);
  const versionLineage = useMemo(() => getVersionLineage(method, version), [method, version?.id]);
  const methodRuns = useMemo(() => experiments.filter(run => run.method_version_id && method?.versions.some(item => item.id === run.method_version_id)), [experiments, method]);
  const versionRuns = useMemo(() => methodRuns.filter(run => run.method_version_id === version?.id && !run.demo), [methodRuns, version?.id]);
  const run = versionRuns.find(item => item.id === runId) ?? versionRuns[0] ?? null;
  const compareCandidates = methodRuns.filter(item => !item.demo && item.id !== run?.id);
  const compareRun = compareCandidates.find(item => item.id === compareId) ?? null;
  const processMap = version?.process_map ?? [];
  const processSteps = run?.steps ?? [];
  const selectedStep = processSteps.find(item => item.id === selectedStepId) ?? null;
  const selectedIndex = selectedStep ? selectedStep.order_index : typeof selectedStepId === 'string' && selectedStepId.startsWith('method-') ? Number(selectedStepId.slice(7)) : -1;
  const selectedMethodStep = selectedIndex >= 0 ? processMap[selectedIndex] : null;
  const mappedStep = selectedMethodStep && selectedStep && selectedMethodStep.name === selectedStep.name ? selectedStep : null;
  const selectedAnalysis = analysisRuns.filter(item => item.experiment_id === run?.id && mappedStep && item.process_step_id === mappedStep.id);
  const unassignedRunAnalysis = analysisRuns.filter(item => item.experiment_id === run?.id && item.process_step_id == null);
  const analysisByStep = useMemo(() => {
    const map = new Map<number, AnalysisRun[]>();
    if (!run) return map;
    for (const analysis of analysisRuns) {
      if (analysis.experiment_id !== run.id || analysis.process_step_id == null) continue;
      const list = map.get(analysis.process_step_id) ?? [];
      list.push(analysis);
      map.set(analysis.process_step_id, list);
    }
    return map;
  }, [analysisRuns, run]);

  useEffect(() => {
    if (!method) { setMethodId(null); setVersionId(null); setRunId(null); setSelectedStepId(null); return; }
    setMethodId(method.id);
    const current = method.versions.find(item => item.id === versionId) ?? latestVersion(method);
    setVersionId(current?.id ?? null);
  }, [topic.id, method?.id, versionId]); // keep explicit choices within the selected topic/method

  useEffect(() => {
    if (!version) { setRunId(null); setCompareId(null); setSelectedStepId(null); return; }
    setRunId(current => versionRuns.some(item => item.id === current) ? current : versionRuns[0]?.id ?? null);
    setCompareId(null);
    setSelectedStepId(null);
    setCompareResult(null);
    setCompareError('');
  }, [version?.id, versionRuns]);

  useEffect(() => {
    let current = true;
    setAnalysisRuns([]);
    api.analysisRuns(topic.id).then(items => { if (current) setAnalysisRuns(items.filter(item => !item.demo)); }).catch(() => { if (current) setAnalysisRuns([]); });
    return () => { current = false; };
  }, [topic.id]);

  useEffect(() => {
    let current = true;
    setCompareResult(null);
    setCompareError('');
    if (!run || !compareRun) return () => { current = false; };
    const sameVersion = run.method_version_id === compareRun.method_version_id;
    const comparisonMode = sameVersion ? 'same_version' : 'cross_version';
    api.compare(run.id, compareRun.id, comparisonMode).then(data => { if (current) setCompareResult(data as CompareResult); }).catch(error => { if (current) setCompareError(error instanceof Error ? error.message : String(error)); });
    return () => { current = false; };
  }, [run?.id, compareRun?.id]);

  const nodes = useMemo<Node[]>(() => processMap.map((stage, index) => {
    const actual = processSteps.find(item => item.order_index === index && item.name === stage.name) ?? null;
    const selected = (actual && actual.id === selectedStepId) || (!actual && selectedStepId === `method-${index}`);
    const differences = compareResult ? (compareResult.different_variables ?? []).filter(item => item.step_order === index).length + (compareResult.missing_variables ?? []).filter(item => item.step_order === index).length + (compareResult.unresolved_variables ?? []).filter(item => item.step_order === index).length : 0;
    const measurements = actual ? (analysisByStep.get(actual.id) ?? []).length : 0;
    const actualConditions = actual?.variables ?? [];
    const conditionLabel = actualConditions.length ? actualConditions.slice(0, 3).map(item => `${item.name.replaceAll('_', ' ')} ${item.value}${item.unit ? ` ${item.unit}` : ''}`).join(' · ') : (ko ? '실행 조건 기록 없음' : 'No run conditions recorded');
    return {
      id: actual ? String(actual.id) : `method-${index}`,
      position: { x: 70 + (index % 3) * 250, y: 70 + Math.floor(index / 3) * 178 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      className: `workstation-process-node${selected ? ' selected' : ''}${differences ? ' has-difference' : ''}`,
      data: { label: <div className="workstation-node-content"><div className="workstation-node-top"><span>{String(index + 1).padStart(2, '0')} · {t(stage.step_type || (ko ? '공정 단계' : 'PROCESS STEP'))}</span>{differences > 0 && <b className="node-change-badge">{ko ? '조건 변경' : 'CHANGED'}</b>}</div><strong>{t(stage.name)}</strong><small>{stage.description ? t(stage.description) : (ko ? '설명 없음' : 'No description')}</small>{layer !== 'method' && <span className="workstation-node-conditions">{conditionLabel}</span>}{layer === 'analysis' && <span className="workstation-node-analysis">{measurements ? `${measurements} ${ko ? '분석 기록' : 'analysis records'}` : (ko ? '연결 분석 없음' : 'No linked analysis')}</span>}</div>, stageIndex: index, actualStepId: actual?.id ?? null },
    };
  }), [processMap, processSteps, selectedStepId, compareResult, analysisByStep, layer, ko, t]);
  const edges = useMemo<Edge[]>(() => nodes.slice(1).map((node, index) => ({ id: `stage-${index}-${node.id}`, source: nodes[index].id, target: node.id, type: 'smoothstep', animated: false, style: { stroke: '#345362', strokeWidth: 2 } })), [nodes]);

  const performCompare = (nextId: number) => {
    setCompareId(nextId || null);
    setLayer('run');
  };
  const selectMethod = (nextId: number) => {
    const next = topic.methods.find(item => item.id === nextId);
    setMethodId(nextId || null);
    setVersionId(latestVersion(next)?.id ?? null);
    setRunId(null);
    setCompareId(null);
    setSelectedStepId(null);
  };

  const areas: { id: Area; label: string; icon: typeof Network }[] = [
    { id: 'process', label: ko ? '공정 흐름' : 'Process canvas', icon: Network },
    { id: 'analysis', label: ko ? '측정·분석' : 'Measurement & analysis', icon: Microscope },
    { id: 'decision', label: ko ? 'AI 판단' : 'AI decision', icon: Activity },
    { id: 'optimization', label: ko ? '최적화' : 'Optimization', icon: Settings2 },
    { id: 'campaign', label: ko ? '캠페인' : 'Campaign', icon: Beaker },
  ];

  return <div className="scientific-workstation">
    <div className="workstation-context-bar"><div><span className="workstation-kicker">{ko ? '연구 주제' : 'RESEARCH TOPIC'}</span><strong>{topic.name}</strong></div><div><span className="workstation-kicker">{ko ? '방법' : 'METHOD'}</span><select aria-label={ko ? '공정 방법 선택' : 'Select method'} value={method?.id ?? ''} onChange={event => selectMethod(Number(event.target.value))}><option value="">{ko ? '공정 방법 없음' : 'No method'}</option>{topic.methods.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div><div><span className="workstation-kicker">{ko ? '버전' : 'VERSION'}</span><select aria-label={ko ? '방법 버전 선택' : 'Select method version'} value={version?.id ?? ''} onChange={event => { setVersionId(Number(event.target.value) || null); setSelectedStepId(null); }}><option value="">—</option>{method?.versions.map(item => <option key={item.id} value={item.id}>v{item.version_label || item.version_number}{item.id === latestVersion(method)?.id ? ` · ${ko ? '현재' : 'current'}` : ''}</option>)}</select></div><div className="workstation-run-pick"><span className="workstation-kicker">{ko ? '선택 Run' : 'ACTIVE RUN'}</span><select aria-label={ko ? '실험 기록 선택' : 'Select experiment run'} value={run?.id ?? ''} onChange={event => { setRunId(Number(event.target.value) || null); setSelectedStepId(null); }}><option value="">{ko ? '실험 기록 없음' : 'No experiment run'}</option>{versionRuns.map(item => <option key={item.id} value={item.id}>{item.code} · {item.name} · {item.date || '—'}</option>)}</select></div><span className="local-status"><i/> {ko ? '로컬 작업공간' : 'LOCAL WORKSPACE'}</span></div>

    <div className="workstation-layout">
      <nav className="workstation-nav" aria-label={ko ? '작업공간 메뉴' : 'Workspace navigation'}>{areas.map(({ id, label, icon: Icon }) => <button key={id} type="button" className={area === id ? 'active' : ''} aria-current={area === id ? 'page' : undefined} onClick={() => setArea(id)}><Icon size={17}/><span>{label}</span>{id === 'analysis' && <small>{analysisRuns.length}</small>}</button>)}<div className="workstation-nav-divider"/><button type="button" className={showEditor ? 'active' : ''} onClick={() => { setArea('process'); setShowEditor(value => !value); }}><Settings2 size={17}/><span>{ko ? '공정 편집' : 'Edit process'}</span></button></nav>

      {area === 'process' ? <>
        <section className="workstation-canvas-panel" aria-label={ko ? '공정 캔버스' : 'Process canvas'}>
          <header className="canvas-toolbar"><div><span className="workstation-kicker">{ko ? '공정 캔버스' : 'PROCESS CANVAS'}</span><h2>{method?.name || (ko ? '공정 방법을 선택하세요' : 'Select a process method')}</h2><p>{version ? `v${version.version_label || version.version_number} · ${processMap.length} ${ko ? '단계' : 'stages'} · ${versionRuns.length} ${ko ? '실행' : 'runs'}` : (ko ? '선택한 연구 주제에 저장된 공정을 표시합니다.' : 'View methods saved under the selected research topic.')}{run ? ` · ${run.status}` : ''}</p></div><div className="canvas-actions"><label>{ko ? '표시 계층' : 'LAYER'}<select aria-label={ko ? '공정 그래프 계층' : 'Graph layer'} value={layer} onChange={event => setLayer(event.target.value as Layer)}><option value="method">{ko ? '방법 구조' : 'Method structure'}</option><option value="run">{ko ? '실행 조건' : 'Run conditions'}</option><option value="analysis">{ko ? '측정 연결' : 'Measurements'}</option></select></label><button type="button" className="workstation-secondary-button" onClick={() => setShowEditor(value => !value)}><Settings2 size={15}/>{ko ? '공정 편집' : 'Edit method'}</button></div></header>
          {versionLineage.length > 0 && <div className="version-lineage-bar"><span className="workstation-kicker">{ko ? '버전 계보' : 'VERSION LINEAGE'}</span><div>{versionLineage.map((item, index) => <span key={item.id} className={`version-lineage-chip${item.id === version?.id ? ' active' : ''}`}>{index > 0 && <i aria-hidden="true">↳</i>}v{item.version_label || item.version_number}{item.id === version?.id && <b>{ko ? '선택' : 'ACTIVE'}</b>}</span>)}</div></div>}
          <div className="canvas-filter-row"><label>{ko ? 'Run A' : 'RUN A'}<select aria-label="Run A" value={run?.id ?? ''} onChange={event => setRunId(Number(event.target.value) || null)}><option value="">—</option>{versionRuns.map(item => <option key={item.id} value={item.id}>{item.code} · {item.name}</option>)}</select></label><GitCompare size={16}/><label>{ko ? 'Run B 비교' : 'COMPARE RUN B'}<select aria-label={ko ? 'Run B 비교' : 'Compare run B'} value={compareRun?.id ?? ''} onChange={event => performCompare(Number(event.target.value))}><option value="">{ko ? '비교 안 함' : 'No comparison'}</option><optgroup label={ko ? '같은 버전 · 기본 비교' : 'Same version · default'}>{compareCandidates.filter(item => item.method_version_id === run?.method_version_id).map(item => <option key={item.id} value={item.id}>{item.code} · {item.name}</option>)}</optgroup><optgroup label={ko ? '다른 버전 · 명시적 비교' : 'Other versions · explicit comparison'}>{compareCandidates.filter(item => item.method_version_id !== run?.method_version_id).map(item => <option key={item.id} value={item.id}>{item.code} · {item.name} · v{item.method_version_label || item.method_version || '?'}</option>)}</optgroup></select></label><span className="comparison-mode-label">{compareRun ? (run?.method_version_id === compareRun.method_version_id ? (ko ? '같은 버전 비교' : 'SAME VERSION') : (ko ? '버전 간 비교 · 서버 검증' : 'CROSS VERSION · SERVER VALIDATED')) : (ko ? '같은 버전이 기본이며, 다른 버전은 명시적으로 선택' : 'Same version by default; cross-version comparison is explicit')}</span></div>
          {compareError && <div className="workstation-inline-error" role="status">{ko ? '비교를 완료하지 못했습니다' : 'Comparison unavailable'} · {compareError}</div>}
          {compareResult?.comparison_context?.comparison_status && compareResult.comparison_context.comparison_status !== 'comparable' && <div className="workstation-inline-error">{ko ? '서버가 비교 불가로 판정했습니다.' : 'The server marked these runs as not comparable.'}</div>}
          <div className="workstation-canvas"><ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.2, minZoom: 0.24, maxZoom: 1 }} nodesDraggable={false} nodesConnectable={false} elementsSelectable onNodeClick={(_, node) => { const data = node.data as { actualStepId: number | null; stageIndex: number }; setSelectedStepId(data.actualStepId ?? `method-${data.stageIndex}`); }} minZoom={0.18} maxZoom={1.5} proOptions={{ hideAttribution: true }}><Background color="#263b4b" gap={24} size={1}/><Controls showInteractive={false}/><MiniMap pannable zoomable nodeColor={node => node.className?.includes('has-difference') ? '#efc179' : '#42d6c3'} maskColor="rgba(8,15,23,.72)"/></ReactFlow>{!processMap.length && <div className="canvas-empty"><Network size={25}/><b>{ko ? '이 방법 버전에는 공정 단계가 없습니다' : 'This method version has no process stages'}</b><span>{ko ? '공정 편집에서 단계를 추가할 수 있습니다.' : 'Add stages in process editing.'}</span></div>}</div>
          <footer className="canvas-legend"><span><i className="legend-process"/>{ko ? '저장된 공정 단계' : 'Saved process stage'}</span><span><i className="legend-change"/>{ko ? '비교에서 차이가 확인된 단계' : 'Difference returned by comparison API'}</span><span><i className="legend-analysis"/>{ko ? '연결된 측정·분석' : 'Linked measurement analysis'}</span><small>{ko ? '선의 위치는 표시용이며 실제 단계 순서는 카드의 번호로 표시됩니다.' : 'Layout is visual; stage numbers indicate execution order.'}</small></footer>
          {compareResult && <div className="comparison-summary"><b>{ko ? '서버 비교 결과' : 'SERVER COMPARISON'}</b><span>{ko ? `변경 ${compareResult.different_variables?.length ?? 0}` : `Changed ${compareResult.different_variables?.length ?? 0}`}</span><span>{ko ? `동일 ${compareResult.same_variables?.length ?? 0}` : `Same ${compareResult.same_variables?.length ?? 0}`}</span><span>{ko ? `누락 ${compareResult.missing_variables?.length ?? 0}` : `Missing ${compareResult.missing_variables?.length ?? 0}`}</span><span>{ko ? `미해결 ${compareResult.unresolved_variables?.length ?? 0}` : `Unresolved ${compareResult.unresolved_variables?.length ?? 0}`}</span></div>}
          {showEditor && <div className="workstation-editor"><MethodWorkspace topic={topic} onChanged={onChanged} activeExperimentId={run?.id}/></div>}
        </section>
        <aside className="workstation-inspector" aria-label={ko ? '선택 항목 정보' : 'Selected item inspector'}>
          <div className="inspector-heading"><span className="workstation-kicker">{ko ? '선택 단계' : 'SELECTED STAGE'}</span><h2>{selectedMethodStep ? t(selectedMethodStep.name) : (ko ? '단계 선택' : 'Select a stage')}</h2><p>{selectedMethodStep ? t(selectedMethodStep.step_type || '') : (ko ? '공정 정보와 기록을 확인합니다.' : 'Inspect process details and records.')}</p></div>
          <div className="inspector-tabs" role="tablist"><button type="button" role="tab" aria-selected={inspectorTab === 'conditions'} onClick={() => setInspectorTab('conditions')}>{ko ? '조건' : 'Conditions'}</button><button type="button" role="tab" aria-selected={inspectorTab === 'source'} onClick={() => setInspectorTab('source')}>{ko ? '출처' : 'Source'}</button><button type="button" role="tab" aria-selected={inspectorTab === 'records'} onClick={() => setInspectorTab('records')}>{ko ? '기록' : 'Records'}</button></div>
          {inspectorTab === 'conditions' && <div className="inspector-body">{selectedMethodStep ? <><div className="inspector-section-label">{ko ? '방법에서 정의한 조건' : 'METHOD CONDITION DEFINITIONS'}</div>{version?.condition_definitions.filter(item => item.step_name === selectedMethodStep.name).map((item, index) => <div className="inspector-value-row" key={`${item.name}-${index}`}><span>{item.name.replaceAll('_', ' ')}</span><b>{item.unit || (ko ? '단위 미지정' : 'unit unspecified')}</b></div>)}{!version?.condition_definitions.some(item => item.step_name === selectedMethodStep.name) && <div className="inspector-empty">{ko ? '정의된 조건이 없습니다.' : 'No conditions defined.'}</div>}<div className="inspector-section-label with-gap">{ko ? '선택 Run에 기록된 값' : 'RECORDED VALUES IN SELECTED RUN'}</div>{mappedStep?.variables.map(item => <div className="inspector-value-row" key={item.id}><span>{item.name.replaceAll('_', ' ')}</span><b>{item.value}{item.unit ? ` ${item.unit}` : ''}</b></div>)}{!mappedStep?.variables.length && <div className="inspector-empty">{ko ? '이 단계에 기록된 실행 조건이 없습니다.' : 'No run conditions recorded for this stage.'}</div>}{compareResult && <ComparisonStepDetails index={selectedIndex} result={compareResult} ko={ko}/>}<div className="inspector-section-label with-gap">{ko ? '방법에 정의된 재료' : 'METHOD MATERIAL DEFINITIONS'}</div>{version?.material_definitions.map((item, index) => <div className="inspector-value-row" key={`method-material-${index}`}><span>{item.name} · {item.role}</span><b>{item.unit || '—'}</b></div>)}{!version?.material_definitions.length && <div className="inspector-empty">{ko ? '방법 재료 정의가 없습니다.' : 'No method material definitions.'}</div>}<div className="inspector-section-label with-gap">{ko ? 'Run에 기록된 재료 · 단계 미지정' : 'RUN MATERIALS · NOT STEP-ASSIGNED'}</div>{run?.materials.map(item => <div className="inspector-value-row" key={`run-material-${item.id}`}><span>{item.name}</span><b>{item.amount}{item.unit ? ` ${item.unit}` : ''}</b></div>)}{!run?.materials.length && <div className="inspector-empty">{ko ? 'Run에 기록된 재료가 없습니다.' : 'No materials recorded for this run.'}</div>}</> : <div className="inspector-empty">{ko ? '캔버스에서 공정 단계를 선택하세요.' : 'Select a process stage on the canvas.'}</div>}</div>}
          {inspectorTab === 'source' && <div className="inspector-body"><InfoRow label={ko ? '연구 주제' : 'Research topic'} value={topic.name}/><InfoRow label={ko ? '공정 방법' : 'Method'} value={method?.name || '—'}/><InfoRow label={ko ? '방법 버전' : 'Method version'} value={version ? `v${version.version_label || version.version_number}` : '—'}/><InfoRow label="Version ID" value={version ? String(version.id) : '—'}/><InfoRow label="Step ID" value={mappedStep ? String(mappedStep.id) : (ko ? '연결된 실행 단계 없음' : 'No mapped run step')}/><InfoRow label={ko ? '선택 실험' : 'Selected run'} value={run ? `${run.code} · ${run.name}` : (ko ? '실험 실행 기록 없음' : 'No experiment run')}/><InfoRow label={ko ? '부모 버전' : 'Parent version'} value={version?.parent_version_id ? `v${method?.versions.find(item => item.id === version.parent_version_id)?.version_label ?? method?.versions.find(item => item.id === version.parent_version_id)?.version_number ?? '?'}` : (ko ? '기준 버전' : 'Base version')}/></div>}
          {inspectorTab === 'records' && <div className="inspector-body">{mappedStep ? <><div className="inspector-section-label">{ko ? '관찰 및 중간 측정' : 'OBSERVATIONS & INTERMEDIATE MEASUREMENTS'}</div>{run?.step_logs?.filter(item => item.step_id === mappedStep.id).map(item => <article className="inspector-record" key={item.id}><small>{item.kind} · {item.occurred_at}</small><b>{item.label}: {item.value}{item.unit ? ` ${item.unit}` : ''}</b>{item.notes && <span>{item.notes}</span>}</article>)}{run?.stage_experiments?.filter(item => item.step_id === mappedStep.id).map(item => <article className="inspector-record" key={`stage-${item.id}`}><small>{item.performed_at} · {item.status}</small><b>{item.name}</b><span>{item.notes}</span></article>)}{!run?.step_logs?.some(item => item.step_id === mappedStep.id) && !run?.stage_experiments?.some(item => item.step_id === mappedStep.id) && <div className="inspector-empty">{ko ? '이 단계에 저장된 관찰이나 부분 실험이 없습니다.' : 'No saved observations or sub-experiments for this stage.'}</div>}<div className="inspector-section-label with-gap">{ko ? '주변 환경 기록' : 'ENVIRONMENT RECORDS'}</div>{run?.environment_records?.filter(item => item.step_id === mappedStep.id).map(item => <article className="inspector-record" key={`env-${item.id}`}><small>{item.phase} · {item.measured_at}</small><b>{[item.temperature_c != null && `${item.temperature_c} °C`, item.relative_humidity_percent != null && `${item.relative_humidity_percent}% RH`, item.pressure_kpa != null && `${item.pressure_kpa} kPa`].filter(Boolean).join(' · ') || (ko ? '환경값 없음' : 'No environment values')}</b>{item.notes && <span>{item.notes}</span>}</article>)}{!run?.environment_records?.some(item => item.step_id === mappedStep.id) && <div className="inspector-empty">{ko ? '이 단계에 환경 기록이 없습니다.' : 'No environment readings for this stage.'}</div>}<div className="inspector-section-label with-gap">{ko ? '단계 사진·파일' : 'STAGE ATTACHMENTS'}</div>{run?.attachments?.filter(item => item.step_id === mappedStep.id).map(item => <a className="inspector-attachment" key={item.id} href={item.image_url} target="_blank" rel="noreferrer"><img src={item.image_url} alt={item.caption || item.filename}/><span><b>{item.filename}</b><small>{item.caption || (ko ? '설명 없음' : 'No caption')}</small></span></a>)}{!run?.attachments?.some(item => item.step_id === mappedStep.id) && <div className="inspector-empty">{ko ? '이 단계에 첨부된 파일이 없습니다.' : 'No files attached to this stage.'}</div>}<div className="inspector-section-label with-gap">{ko ? '연결 분석' : 'LINKED ANALYSIS'}</div>{selectedAnalysis.map(item => <article className="inspector-record analysis" key={item.id}><small>{item.modality} · {item.review_status || item.analysis_status || '—'}</small><b>{item.filename}</b><span>{item.tool_id}</span></article>)}{!selectedAnalysis.length && <div className="inspector-empty">{ko ? '선택 단계에 연결된 분석이 없습니다.' : 'No analysis linked to this stage.'}</div>}</> : <div className="inspector-empty">{ko ? '캔버스에서 단계를 선택하면 해당 단계의 실행 기록만 표시됩니다.' : 'Select a stage to inspect its run records.'}</div>}{unassignedRunAnalysis.length > 0 && <><div className="inspector-section-label with-gap">{ko ? 'Run 수준 분석 · 단계 미지정' : 'RUN-LEVEL ANALYSIS · NO STEP ASSIGNED'}</div>{unassignedRunAnalysis.map(item => <article className="inspector-record analysis" key={`unassigned-${item.id}`}><small>{item.modality} · {item.review_status || item.analysis_status || '—'}</small><b>{item.filename}</b><span>{ko ? '특정 공정 단계의 결과로 간주하지 않습니다.' : 'Not attributed to a specific process step.'}</span></article>)}</>}</div>}
          <div className="inspector-footer"><span>{ko ? '수치와 기록은 저장된 데이터에서만 표시됩니다.' : 'Values and records come from saved data only.'}</span>{selectedStepId != null && <button type="button" onClick={() => setArea('analysis')}><Microscope size={14}/>{ko ? '분석 열기' : 'Open analysis'}</button>}</div>
        </aside>
      </> : <section className="workstation-detail-area"><header className="canvas-toolbar"><div><span className="workstation-kicker">{areas.find(item => item.id === area)?.label.toUpperCase()}</span><h2>{areas.find(item => item.id === area)?.label}</h2><p>{ko ? '선택한 주제와 Run 문맥을 유지해 기존 분석 모듈을 엽니다.' : 'Open the existing module with the selected topic and run context.'}</p></div><button className="workstation-secondary-button" type="button" onClick={() => setArea('process')}><Network size={15}/>{ko ? '공정 캔버스로' : 'Back to process'}</button></header>{area === 'analysis' && <Suspense fallback={<div className="loading-panel">Loading analysis…</div>}><AnalysisPanel key={`${topic.id}-${run?.id ?? 'none'}`} experiments={experiments} topicId={topic.id} initialExperimentId={run?.id} onExperimentCreated={onExperimentsChanged} onOpenMethods={() => { setArea('process'); setShowEditor(true); }}/></Suspense>}{area === 'decision' && <Suspense fallback={<div className="loading-panel">Loading decision…</div>}><DecisionPanel key={`${topic.id}-${run?.id ?? 'none'}`} topicId={topic.id} experiments={experiments} initialExperimentId={run?.id}/></Suspense>}{area === 'optimization' && <Suspense fallback={<div className="loading-panel">Loading optimization…</div>}><OptimizationPanel key={`${topic.id}-${version?.id ?? 'none'}`} topic={topic} initialMethodVersionId={version?.id}/></Suspense>}{area === 'campaign' && <Suspense fallback={<div className="loading-panel">Loading campaign…</div>}><CampaignPanel key={`${topic.id}-${run?.id ?? 'none'}`} topicId={topic.id} experiments={experiments} initialExperimentId={run?.id}/></Suspense>}</section>}
    </div>
  </div>;
}

function latestVersion(method: ExperimentMethod | null | undefined): MethodVersion | null {
  return method?.versions.reduce<MethodVersion | null>((latest, item) => !latest || item.version_number > latest.version_number ? item : latest, null) ?? null;
}

function getVersionLineage(method: ExperimentMethod | null, selected: MethodVersion | null): MethodVersion[] {
  if (!method || !selected) return [];
  const chain: MethodVersion[] = [];
  const seen = new Set<number>();
  let current: MethodVersion | undefined = selected;
  while (current && !seen.has(current.id) && chain.length <= method.versions.length) {
    seen.add(current.id);
    chain.unshift(current);
    current = current.parent_version_id ? method.versions.find(item => item.id === current?.parent_version_id) : undefined;
  }
  return chain;
}

function InfoRow({ label, value }: { label: string; value: string }) { return <div className="inspector-info-row"><span>{label}</span><b>{value}</b></div>; }

function ComparisonStepDetails({ index, result, ko }: { index: number; result: CompareResult; ko: boolean }) {
  if (index < 0) return null;
  const changed = result.different_variables.filter(item => item.step_order === index);
  const same = result.same_variables.filter(item => item.step_order === index);
  const missing = result.missing_variables.filter(item => item.step_order === index);
  const unresolved = result.unresolved_variables.filter(item => item.step_order === index);
  if (!changed.length && !same.length && !missing.length && !unresolved.length) return <div className="inspector-empty compare-note">{ko ? '이 단계에 비교 가능한 조건이 없습니다.' : 'No comparable conditions for this stage.'}</div>;
  return <div className="inspector-comparison"><div className="inspector-section-label with-gap">{ko ? 'Run 비교 · 서버 판정' : 'RUN COMPARISON · SERVER RESULT'}</div>{[...changed.map(item => ({ item, state: 'changed' })), ...missing.map(item => ({ item, state: 'missing' })), ...unresolved.map(item => ({ item, state: 'unresolved' })), ...same.map(item => ({ item, state: 'same' }))].map(({ item, state }, index) => <article className={`compare-variable ${state}`} key={`${item.key}-${state}-${index}`}><strong>{item.name.replaceAll('_', ' ')}</strong><span>{formatMaybe(item.experiment_a)}{item.unit_a ? ` ${item.unit_a}` : ''} <i>→</i> {formatMaybe(item.experiment_b)}{item.unit_b || item.unit ? ` ${item.unit_b || item.unit}` : ''}</span><small>{state === 'changed' ? (ko ? '다름' : 'Different') : state === 'same' ? (ko ? '동일' : 'Same') : state === 'missing' ? (ko ? '값 누락' : 'Missing value') : (item.reason || item.comparison?.reason || (ko ? '비교 미해결' : 'Unresolved'))}</small></article>)}</div>;
}

function formatMaybe(value: unknown) { return value == null ? '—' : Array.isArray(value) ? value.filter(Boolean).join(' ') : String(value); }
