import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Archive, Camera, Clock3, CopyPlus, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../api/client';
import { useLanguage } from '../language';
import type { AnalysisRun, Experiment, ExperimentMethod, MethodCondition, MethodVersion, ResearchTopic, Step } from '../types';
import type { StageExperiment } from '../types';
type BranchDraft={methodId:number;methodName:string;methodDescription:string;version:MethodVersion;branchPointIndex:number;processMap:MethodVersion['process_map'];conditionDefinitions:MethodCondition[]};
const BRANCH_UNIT_OPTIONS=['s','min','h','day','cycles','°C','K','°F','%','µg','mg','g','kg','µL','mL','L','µmol','mmol','mol','µM','mM','M','rpm','Pa','kPa','bar','atm','V','mV','A','mA','W','mW','nm','µm','mm','cm','pH'];

export default function ProcessTimeline({ topic, onArchive, onChanged }: { topic: ResearchTopic; onArchive: () => void; onChanged: () => void }) {
  const { t, language } = useLanguage();
  const [runs, setRuns] = useState<Experiment[]>([]);
  const [analysisRuns, setAnalysisRuns] = useState<AnalysisRun[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<'process' | 'experiment' | 'date'>('process');
  const [experimentTab, setExperimentTab] = useState<'process' | 'results'>('process');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice,setNotice]=useState('');
  const [captions, setCaptions] = useState<Record<number, string>>({});
  const [editingSubexperiment, setEditingSubexperiment] = useState<StageExperiment | null>(null);
  const [showSubexperimentForm, setShowSubexperimentForm] = useState(false);
  const [branchDraft, setBranchDraft] = useState<BranchDraft|null>(null);
  const selected = runs.find((run) => run.id === selectedId) ?? null;
  const processGroups = useMemo(() => {
    const grouped = new Map<string, Experiment[]>();
    for (const run of runs) {
      const signature = JSON.stringify([...run.steps].sort((a, b) => a.order_index - b.order_index).map(step => [step.order_index, step.name, step.step_type]));
      const key = run.method_version_id != null ? `version:${run.method_version_id}` : `process:${run.method_name ?? ''}:${run.target}:${signature}`;
      grouped.set(key, [...(grouped.get(key) ?? []), run]);
    }
    const groups=[...grouped].map(([key, entries]) => {
      const ordered = [...entries].sort((a, b) => (a.date ?? '').localeCompare(b.date ?? '') || a.id - b.id);
      const results = [...new Set(ordered.flatMap(run => run.results.map(result => result.key)))];
      const steps = [...ordered[0].steps].sort((a, b) => a.order_index - b.order_index);
      const method=topic.methods.find(item=>item.versions.some(version=>version.id===ordered[0].method_version_id));
      const version=method?.versions.find(item=>item.id===ordered[0].method_version_id);
      return { key, name: ordered[0].method_name || ordered[0].target, target: ordered[0].target, version: ordered[0].method_version, versionLabel:ordered[0].method_version_label??version?.version_label??String(ordered[0].method_version??''), methodId:method?.id??null, methodDescription:method?.description??'', versionDefinition:version??null, entries: ordered, steps, results };
    });
    for(const method of topic.methods)for(const version of method.versions){
      const key=`version:${version.id}`;if(grouped.has(key))continue;
      const steps:Step[]=version.process_map.map((step,index)=>({id:-(index+1),name:step.name,step_type:step.step_type??'process',order_index:index,description:step.description,variables:[]}));
      groups.push({key,name:method.name,target:topic.name,version:version.version_number,versionLabel:version.version_label??String(version.version_number),methodId:method.id,methodDescription:method.description,versionDefinition:version,entries:[],steps,results:[]});
    }
    return groups.sort((a,b)=>a.name.localeCompare(b.name)||(a.version??0)-(b.version??0));
  }, [runs,topic]);
  const selectedProcessGroup = processGroups.find(group => group.entries.some(run => run.id === selected?.id));
  const dateGroups = useMemo(() => {
    const grouped = new Map<string, Experiment[]>();
    for (const run of runs) {
      const key = run.date || '';
      grouped.set(key, [...(grouped.get(key) ?? []), run]);
    }
    return [...grouped.entries()].sort(([a], [b]) => b.localeCompare(a));
  }, [runs]);
  const reload = async () => {
    try {
      const [items, measurements] = await Promise.all([api.experiments(topic.id), api.analysisRuns(topic.id)]);
      setRuns(items);
      setAnalysisRuns(measurements);
      setSelectedId((current) => items.some((run) => run.id === current) ? current : null);
    } catch (cause) { setError(String(cause)); }
  };
  useEffect(() => { void reload(); }, [topic.id]);
  const orderedSteps = useMemo(() => [...(selected?.steps ?? [])].sort((a, b) => a.order_index - b.order_index), [selected]);
  const runDuration = (minutes?: number | null) => {
    if (minutes == null) return t('Duration not recorded');
    const hours = Math.floor(minutes / 60); const remaining = minutes % 60;
    return [hours ? `${hours}${t('h')}` : '', remaining ? `${remaining}${t('min')}` : ''].filter(Boolean).join(' ') || `0 ${t('min')}`;
  };

  const addLog = async (event: FormEvent<HTMLFormElement>, stepId: number) => {
    event.preventDefault();
    if (!selected || busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError('');
    try {
      await api.addStepLog(selected.id, stepId, {
        kind: String(data.get('kind') || 'measurement'),
        label: String(data.get('label') || '').trim(),
        value: String(data.get('value') || '').trim(),
        unit: String(data.get('unit') || '').trim() || null,
        notes: String(data.get('notes') || '').trim(),
      });
      form.reset(); await reload(); onChanged();
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };

  const addImage = async (file: File | undefined, stepId: number) => {
    if (!selected || !file || busy) return;
    setBusy(true); setError('');
    try {
      await api.attachStepImage(selected.id, stepId, file, captions[stepId] ?? '');
      setCaptions((current) => ({ ...current, [stepId]: '' })); await reload(); onChanged();
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };

  const removeLog = async (logId: number) => {
    if (!selected || !window.confirm(t('Remove this process record?'))) return;
    try { await api.deleteStepLog(selected.id, logId); await reload(); onChanged(); }
    catch (cause) { setError(String(cause)); }
  };
  const removeImage = async (attachmentId: number) => {
    if (!selected || !window.confirm(t('Remove this image?'))) return;
    try { await api.deleteStepImage(selected.id, attachmentId); await reload(); onChanged(); }
    catch (cause) { setError(String(cause)); }
  };

  const parseStageValues = (text: FormDataEntryValue | null) => String(text ?? '').split('\n').map(line => line.trim()).filter(Boolean).map(line => {
    const [name = '', value = '', unit = ''] = line.split('|').map(part => part.trim());
    return { name, value, unit: unit || null };
  }).filter(item => item.name && item.value);
  const saveSubexperiment = async (event: FormEvent<HTMLFormElement>, stepId: number) => {
    event.preventDefault();
    if (!selected || busy) return;
    const form = event.currentTarget; const data = new FormData(form);
    const payload = { name: String(data.get('name') || '').trim(), performed_at: data.get('performed_at') ? new Date(`${data.get('performed_at')}T12:00:00`).toISOString() : new Date().toISOString(), status: String(data.get('status') || 'recorded'), conditions: parseStageValues(data.get('conditions')), results: parseStageValues(data.get('results')), notes: String(data.get('notes') || '').trim() };
    setBusy(true); setError('');
    try {
      if (editingSubexperiment) await api.updateSubexperiment(selected.id, stepId, editingSubexperiment.id, payload);
      else await api.addSubexperiment(selected.id, stepId, payload);
      setEditingSubexperiment(null); setShowSubexperimentForm(false); await reload(); onChanged();
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  const removeSubexperiment = async (item: StageExperiment) => {
    if (!window.confirm(t('Remove this partial experiment?'))) return;
    try { await api.deleteSubexperiment(item.experiment_id, item.step_id, item.id); await reload(); onChanged(); }
    catch (cause) { setError(String(cause)); }
  };
  const beginStageBranch=(group:typeof processGroups[number],stageIndex:number)=>{
    if(!group.methodId||!group.versionDefinition)return;
    setBranchDraft({methodId:group.methodId,methodName:group.name,methodDescription:group.methodDescription,version:group.versionDefinition,branchPointIndex:stageIndex,processMap:group.versionDefinition.process_map.map(item=>({...item})),conditionDefinitions:group.versionDefinition.condition_definitions.map(item=>({...item}))});
    setError('');
  };
  const updateBranchStep=(index:number,patch:Partial<MethodVersion['process_map'][number]>)=>setBranchDraft(current=>{
    if(!current)return current;const previous=current.processMap[index];const processMap=current.processMap.map((item,itemIndex)=>itemIndex===index?{...item,...patch}:item);
    const conditionDefinitions=patch.name!==undefined?current.conditionDefinitions.map(item=>item.step_name===previous.name?{...item,step_name:patch.name!}:item):current.conditionDefinitions;
    return {...current,processMap,conditionDefinitions};
  });
  const updateBranchCondition=(index:number,patch:Partial<MethodCondition>)=>setBranchDraft(current=>current?{...current,conditionDefinitions:current.conditionDefinitions.map((item,itemIndex)=>itemIndex===index?{...item,...patch}:item)}:current);
  const addBranchCondition=(stepName:string)=>setBranchDraft(current=>current?{...current,conditionDefinitions:[...current.conditionDefinitions,{step_name:stepName,name:t('New condition'),unit:'',value_type:'number',required:false}]}:current);
  const removeBranchCondition=(index:number)=>setBranchDraft(current=>current?{...current,conditionDefinitions:current.conditionDefinitions.filter((_,itemIndex)=>itemIndex!==index)}:current);
  const addBranchStep=()=>setBranchDraft(current=>current?{...current,processMap:[...current.processMap,{name:`${t('New process step')} ${current.processMap.length+1}`,description:'',step_type:'process'}]}:current);
  const removeBranchStep=(index:number)=>setBranchDraft(current=>{
    if(!current||current.processMap.length<=1)return current;const name=current.processMap[index].name;return {...current,processMap:current.processMap.filter((_,itemIndex)=>itemIndex!==index),conditionDefinitions:current.conditionDefinitions.filter(item=>item.step_name!==name),branchPointIndex:Math.max(0,current.branchPointIndex-(index<current.branchPointIndex?1:0))};
  });
  const moveBranchStep=(index:number,direction:-1|1)=>setBranchDraft(current=>{
    if(!current)return current;const target=index+direction;if(target<0||target>=current.processMap.length)return current;const processMap=[...current.processMap];[processMap[index],processMap[target]]=[processMap[target],processMap[index]];let branchPointIndex=current.branchPointIndex;if(index===branchPointIndex)branchPointIndex=target;else if(target===branchPointIndex)branchPointIndex=index;return {...current,processMap,branchPointIndex};
  });
  const saveStageBranch=async(event:FormEvent<HTMLFormElement>)=>{
    event.preventDefault();if(!branchDraft||busy)return;
    const processMap=branchDraft.processMap.map(item=>({...item,name:item.name.trim(),description:item.description.trim()}));
    if(processMap.some(item=>!item.name)){setError(t('Every process step needs a name.'));return;}
    const conditionDefinitions=branchDraft.conditionDefinitions.map(item=>({...item,name:item.name.trim(),unit:item.unit==='__custom__'?'':item.unit,step_name:processMap.find(step=>step.name===item.step_name)?.name??item.step_name}));
    if(conditionDefinitions.some(item=>!item.name)){setError(t('Every process condition needs a name.'));return;}
    setBusy(true);setError('');
    try{
      const updated=await api.createMethodVersion(branchDraft.methodId,{name:branchDraft.methodName,description:branchDraft.methodDescription,category:topic.methods.find(item=>item.id===branchDraft.methodId)?.category??'custom',parent_version_id:branchDraft.version.id,process_map:processMap,condition_definitions:conditionDefinitions,material_definitions:branchDraft.version.material_definitions});
      const created=updated.versions.at(-1);setBranchDraft(null);onChanged();await reload();
      if(created)setNotice(`${t('Created process branch')}: v${created.version_label??created.version_number} · ${t('Parent version')} v${branchDraft.version.version_label??branchDraft.version.version_number}${created.created_at?` · ${t('Branch date')}: ${new Date(created.created_at).toLocaleDateString(language==='ko'?'ko-KR':'en-US')}`:''}`);
    }catch(cause){setError(String(cause));}
    finally{setBusy(false);}
  };

  return <section className={`process-timeline-workspace ${experimentTab==='results'?'results-tab':'process-tab'}`}>
    <header className="timeline-toolbar"><div><div className="eyebrow">{t('PROCESS · SUB-EXPERIMENTS')}</div><h2>{t(experimentTab==='process'?'Experiment process':'Experiment results')}</h2><p>{t(experimentTab==='process'?'View process steps, branch dates, and the current process tree.':'View recorded outcomes by process and experiment date.')}</p></div>{experimentTab==='process'&&<button className="button primary small" onClick={onArchive}><Plus size={14}/>{t('Add process')}</button>}</header>
    {error && <div className="error timeline-error">{error}<button className="text-button" onClick={() => setError('')}>{t('Dismiss')}</button></div>}{notice&&<div className="process-branch-notice">{notice}<button className="text-button" onClick={()=>setNotice('')}>{t('Dismiss')}</button></div>}
    <div className="experiment-inner-tabs" role="tablist" aria-label={t('Experiment workspace sections')}><button type="button" role="tab" aria-selected={experimentTab==='process'} className={experimentTab==='process'?'active':''} onClick={()=>{setExperimentTab('process');setViewMode('process')}}>{t('Experiment process')}</button><button type="button" role="tab" aria-selected={experimentTab==='results'} className={experimentTab==='results'?'active':''} onClick={()=>{setExperimentTab('results');setViewMode('process')}}>{t('Experiment results')}</button></div>
    {!processGroups.length ? <div className="card timeline-empty"><h3>{t(experimentTab==='results'?'No result values have been recorded yet.':'No experiment runs yet')}</h3><p>{t('Create a method and record its first run to start using the process timeline.')}</p>{experimentTab==='process'&&<button className="button primary" onClick={onArchive}><Plus size={14}/>{t('Open archived screen')}</button>}</div> : <>
      <section className={`card timeline-run-list ${experimentTab==='results'?'results-only':'process-only'}`}><header className="timeline-run-list-head"><div><h3>{t(experimentTab==='process'?'Process versions':'Processes and sub-experiments')}</h3><p>{t(experimentTab==='process'?'Review each process tree, its branch point, and the current version.':'Each process is one group. Its individual experiments are arranged as dated rows so you can compare results over time.')}</p></div><span className="timeline-run-total">{processGroups.length} {t('processes')} · {runs.length} {t('experiments')}</span>{experimentTab==='results'&&<div className="timeline-view-toggle" role="group" aria-label={t('View grouping')}><button type="button" className={viewMode==='process'?'active':''} aria-pressed={viewMode==='process'} onClick={()=>setViewMode('process')}>{t('By process')}</button><button type="button" className={viewMode==='experiment'?'active':''} aria-pressed={viewMode==='experiment'} onClick={()=>setViewMode('experiment')}>{t('By experiment')}</button><button type="button" className={viewMode==='date'?'active':''} aria-pressed={viewMode==='date'} onClick={()=>setViewMode('date')}>{t('By date')}</button></div>}<button className="button outline small" onClick={() => void reload()}><RefreshCw size={13}/>{t('Refresh')}</button></header>
        {viewMode==='process'&&processGroups.map((group, groupIndex) => <details className="process-history-group" key={group.key} style={{marginLeft:`${versionDepth(group.versionDefinition,topic.methods.find(method=>method.id===group.methodId)?.versions??[])*22}px`}} open={experimentTab==='results' || groupIndex === 0 || !group.entries.length || group.entries.some(run => run.id === selected?.id)}><summary><span className="process-history-name"><b>{t('Process')} {groupIndex + 1} · {t(group.name)}{group.versionLabel ? ` v${group.versionLabel}` : ''}</b><small>{group.versionDefinition?.created_at ? `${t(group.versionDefinition.parent_version_id?'Branch date':'Version date')}: ${new Date(group.versionDefinition.created_at).toLocaleDateString(language==='ko'?'ko-KR':'en-US')}` : t(group.target)}{group.versionDefinition?.parent_version_id ? ` · ${t('Branched from')} v${topic.methods.find(method=>method.id===group.methodId)?.versions.find(version=>version.id===group.versionDefinition?.parent_version_id)?.version_label??topic.methods.find(method=>method.id===group.methodId)?.versions.find(version=>version.id===group.versionDefinition?.parent_version_id)?.version_number??'?'}` : ''}</small></span>{group.versionDefinition&&group.methodId&&latestMethodVersion(topic.methods.find(method=>method.id===group.methodId))?.id===group.versionDefinition.id&&<span className="process-current-badge">{t('Current main tree')}</span>}<span className="process-history-count">{group.entries.length} {t('experiments')}</span></summary>
          <div className="process-stage-list">{group.steps.map((stage, stageIndex) => {
            const stageVariables = [...new Set([...group.entries.flatMap(run => (run.steps.find(item => item.order_index === stage.order_index)?.variables ?? []).map(variable => variable.name)),...(group.versionDefinition?.condition_definitions.filter(item=>item.step_name===stage.name).map(item=>item.name)??[])])];
            const activeBranch=branchDraft&&branchDraft.version.id===group.versionDefinition?.id&&branchDraft.branchPointIndex===stageIndex?branchDraft:null;
            return <section className="process-stage" key={`${group.key}-stage-${stage.order_index}`}>
              <div className="process-stage-marker"><span>{stageIndex + 1}</span></div>
              <div className="process-stage-body"><header className="process-stage-head"><div><b>{stage.name}</b>{stage.description && <small>{stage.description}</small>}</div><div className="process-stage-head-actions"><span>{t('Stage')} {stageIndex + 1}</span>{group.methodId&&group.versionDefinition&&<button type="button" className="button outline small" onClick={()=>beginStageBranch(group,stageIndex)}><CopyPlus size={12}/>{t('Branch this stage')}</button>}</div></header>
                {activeBranch&&<form className="process-branch-editor process-branch-editor-expanded" onSubmit={event=>void saveStageBranch(event)}><div className="process-branch-title"><b>{t('Create a process version from')} v{activeBranch.version.version_label??activeBranch.version.version_number}</b><small>{t('Branch point')}: {activeBranch.processMap[activeBranch.branchPointIndex]?.name}. {t('Edit conditions in fields, add or remove steps, and change their order. Existing steps are copied into this draft.')}</small></div><div className="branch-stage-editor-list">{activeBranch.processMap.map((branchStep,branchIndex)=>{const conditionIndexes=activeBranch.conditionDefinitions.map((condition,index)=>({condition,index})).filter(item=>item.condition.step_name===branchStep.name);return <article className="branch-stage-editor" key={`branch-step-${branchIndex}`}><header><span>{branchIndex+1}</span><div className="branch-stage-actions"><button type="button" className="button outline small" disabled={branchIndex===0} onClick={()=>moveBranchStep(branchIndex,-1)}>{t('Move up')}</button><button type="button" className="button outline small" disabled={branchIndex===activeBranch.processMap.length-1} onClick={()=>moveBranchStep(branchIndex,1)}>{t('Move down')}</button><button type="button" className="button outline small danger-outline" disabled={activeBranch.processMap.length<=1} onClick={()=>removeBranchStep(branchIndex)}>{t('Remove step')}</button></div></header><div className="branch-stage-fields"><label>{t('Process step name')}<input value={branchStep.name} required onChange={event=>updateBranchStep(branchIndex,{name:event.target.value})}/></label><label>{t('Process description')}<input value={branchStep.description} onChange={event=>updateBranchStep(branchIndex,{description:event.target.value})}/></label></div><div className="branch-condition-list"><div className="branch-condition-heading"><b>{t('Process conditions')}</b><button type="button" className="text-button" onClick={()=>addBranchCondition(branchStep.name)}><Plus size={13}/>{t('Add condition')}</button></div>{conditionIndexes.map(({condition,index})=><div className="branch-condition-row" key={`condition-${index}`}><input aria-label={t('Condition name')} value={condition.name} onChange={event=>updateBranchCondition(index,{name:event.target.value})} placeholder={t('Condition name')}/><div className="branch-unit-control"><select aria-label={t('Unit')} value={condition.unit==='__custom__'||(condition.unit!==''&&!BRANCH_UNIT_OPTIONS.includes(condition.unit))?'__custom__':condition.unit||'__none__'} onChange={event=>updateBranchCondition(index,{unit:event.target.value==='__custom__'?'__custom__':event.target.value==='__none__'?'':event.target.value})}><option value="__none__">—</option><optgroup label={t('Time')}>{['s','min','h','day','cycles'].map(unit=><option value={unit} key={unit}>{unit}</option>)}</optgroup><optgroup label={t('Temperature')}>{['°C','K','°F'].map(unit=><option value={unit} key={unit}>{unit}</option>)}</optgroup><optgroup label={t('Mass')}>{['µg','mg','g','kg'].map(unit=><option value={unit} key={unit}>{unit}</option>)}</optgroup><optgroup label={t('Volume')}>{['µL','mL','L'].map(unit=><option value={unit} key={unit}>{unit}</option>)}</optgroup><optgroup label={t('Amount / concentration')}>{['µmol','mmol','mol','µM','mM','M'].map(unit=><option value={unit} key={unit}>{unit}</option>)}</optgroup><optgroup label={t('Process / pressure')}>{['%','rpm','Pa','kPa','bar','atm'].map(unit=><option value={unit} key={unit}>{unit}</option>)}</optgroup><optgroup label={t('Electrical / length')}>{['V','mV','A','mA','W','mW','nm','µm','mm','cm','pH'].map(unit=><option value={unit} key={unit}>{unit}</option>)}</optgroup><option value="__custom__">{t('Custom unit')}</option></select>{(condition.unit==='__custom__'||(condition.unit!==''&&!BRANCH_UNIT_OPTIONS.includes(condition.unit)))&&<input aria-label={t('Enter custom unit')} value={condition.unit==='__custom__'?'':condition.unit} onChange={event=>updateBranchCondition(index,{unit:event.target.value})} placeholder={t('e.g. samples / min')}/>}</div><select aria-label={t('Value type')} value={condition.value_type} onChange={event=>updateBranchCondition(index,{value_type:event.target.value as MethodCondition['value_type']})}><option value="number">{t('Number')}</option><option value="text">{t('Text')}</option><option value="boolean">{t('Yes / no')}</option></select><label className="branch-required"><input type="checkbox" checked={condition.required} onChange={event=>updateBranchCondition(index,{required:event.target.checked})}/>{t('Required')}</label><button type="button" className="icon-button" aria-label={t('Remove condition')} onClick={()=>removeBranchCondition(index)}><Trash2 size={14}/></button></div>)}{!conditionIndexes.length&&<small className="branch-no-conditions">{t('No conditions in this step yet.')}</small>}</div></article>})}</div><button type="button" className="button outline small branch-add-step" onClick={addBranchStep}><Plus size={14}/>{t('Add process step')}</button><div className="timeline-subexperiment-buttons"><button type="button" className="button outline small" onClick={()=>setBranchDraft(null)}>{t('Cancel')}</button><button className="button primary small" disabled={busy}>{busy?t('Saving…'):t('Save new version branch')}</button></div></form>}
                <div className="process-experiment-table-wrap"><table className="process-experiment-table process-stage-table"><thead><tr><th>{t('Date')}</th><th>{t('Sub-experiment')}</th><th>{t('Status')}</th>{stageVariables.map(name => <th key={name}>{name}</th>)}<th>{t('Intermediate values and observations')}</th><th>{t('Analysis files')}</th></tr></thead><tbody>{group.entries.map((run, runIndex) => {
                  const runStep = run.steps.find(item => item.order_index === stage.order_index) ?? run.steps.find(item => item.name === stage.name);
                  const analysis = analysisRuns.filter(item => item.experiment_id === run.id && item.process_step_id === runStep?.id);
                  const logs = (run.step_logs ?? []).filter(item => item.step_id === runStep?.id).sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
                  return <tr key={run.id} className={run.id === selected?.id ? 'selected' : undefined}>
                    <td className="process-experiment-date">{run.date || '—'}</td><td><button type="button" className="process-experiment-title" aria-label={`${t('Open experiment record')}: ${run.name}`} onClick={() => setSelectedId(run.id)}><b>{run.name}</b><small>{run.code} · {t('Experiment')} {run.method_run_number ?? runIndex + 1}</small></button></td><td><span className={`status ${run.status}`}>{t(run.status.replace('_', ' '))}</span></td>
                    {stageVariables.map(name => { const variable = runStep?.variables.find(item => item.name === name); return <td key={name}>{variable ? `${variable.value}${variable.unit ? ` ${variable.unit}` : ''}` : '—'}</td>; })}
                    <td className="process-intermediate-cell">{logs.length ? logs.map(log => <span key={log.id}><b>{log.label}</b>{log.value && ` · ${log.value} ${log.unit ?? ''}`}</span>) : '—'}</td><td><span className="process-analysis-count">{analysis.length ? `${analysis.length} · ${t('files')}` : '—'}</span></td>
                  </tr>;
                })}{!group.entries.length&&<tr><td colSpan={stageVariables.length+5}>{t('No experiment records in this version yet. Record a run to start its dated result table.')}</td></tr>}</tbody></table></div>
              </div>
            </section>;
          })}</div>
          {!!group.results.length && <details className="process-result-section" open><summary className="process-result-toggle"><h4>{t('Sub-experiment results')}</h4><span>{group.entries.length} {t('experiments')}</span></summary><div className="process-experiment-table-wrap"><table className="process-experiment-table process-result-table"><thead><tr><th>{t('Date')}</th><th>{t('Sub-experiment')}</th>{group.results.map(result => <th key={result}>{result}</th>)}</tr></thead><tbody>{group.entries.map((run, runIndex) => <tr key={run.id} className={run.id === selected?.id ? 'selected' : undefined}><td className="process-experiment-date">{run.date || '—'}</td><td><button type="button" className="process-experiment-title" onClick={() => setSelectedId(run.id)}><b>{run.name}</b><small>{run.code} · {t('Experiment')} {run.method_run_number ?? runIndex + 1}</small></button></td>{group.results.map(result => { const value = run.results.find(item => item.key === result); return <td key={result}>{value ? `${value.value}${value.unit ? ` ${value.unit}` : ''}` : '—'}</td>; })}</tr>)}</tbody></table></div></details>}
        </details>)}
        {viewMode==='experiment'&&<div className="timeline-run-card-groups">{processGroups.map(group=><section className="timeline-run-card-group" key={group.key}><header><b>{t(group.name)}{group.versionLabel?` v${group.versionLabel}`:''}</b><small>{group.target} · {group.entries.length} {t('experiments')}</small></header><div>{group.entries.map(run=><RunSelectionCard key={run.id} run={run} processName={t(group.name)} selected={run.id===selected?.id} onSelect={()=>setSelectedId(run.id)}/>)}</div></section>)}</div>}
        {viewMode==='date'&&<div className="timeline-date-groups">{dateGroups.map(([date,entries])=><section className="timeline-date-group" key={date||'undated'}><header><b>{date||t('Date not recorded')}</b><span>{entries.length} {t('experiments')}</span></header><div>{entries.map(run=>{const group=processGroups.find(item=>item.entries.some(entry=>entry.id===run.id));return <RunSelectionCard key={run.id} run={run} processName={`${t(group?.name??run.method_name??run.target)}${run.method_version_label?` v${run.method_version_label}`:''}`} selected={run.id===selected?.id} onSelect={()=>setSelectedId(run.id)}/>})}</div></section>)}</div>}{experimentTab==='results'&&!processGroups.some(group=>group.results.length)&&<div className="empty-hint">{t('No result values have been recorded yet.')}</div>}
      </section>
      {experimentTab==='results'&&selected && <>
        <section className="timeline-accordion-panel" role="region" id={`run-panel-${selected.id}`} aria-label={selected.name}><section className="card timeline-run-summary"><div className="timeline-summary-main"><div><span className={`status ${selected.status}`}>{t(selected.status.replace('_', ' '))}</span><h3>{selected.name}</h3><p>{selected.code} · {selected.target} · {selected.method_name ?? t('No reusable method')}</p></div><div className="timeline-summary-meta"><span>{t('Date')}<b>{selected.date || '—'}</b></span><span>{t('Duration')}<b>{runDuration(selected.duration_minutes)}</b></span><span>{t('Method version')}<b>{selected.method_version_label?`v${selected.method_version_label}`:selected.method_version?`v${selected.method_version}`:'—'}</b></span></div></div>
          {!!selected.results.length && <div className="timeline-final-results"><b>{t('Final results')}</b>{selected.results.map((result, index) => <span key={`${result.key}-${index}`}>{result.key}: {result.value} {result.unit ?? ''}</span>)}</div>}
          {!!selected.observations.length && <div className="timeline-summary-observations">{selected.observations.map((item, index) => <span key={`${item.category}-${index}`}>{item.description}</span>)}</div>}
        </section>
        {analysisRuns.some((item) => item.experiment_id === selected.id) && <section className="card timeline-analysis-links"><h3>{t('Measurement analyses linked to this experiment')}</h3>{analysisRuns.filter((item) => item.experiment_id === selected.id).map((item) => <article key={item.id}><div><b>{item.result_key || item.modality}</b><small>{item.modality.toUpperCase()} · {item.filename}{item.process_step_id ? ` · ${selected.steps.find((step) => step.id === item.process_step_id)?.name ?? ''}` : ''}</small>{item.demo && <em className="demo-measurement-label">{t('Synthetic demo measurement · not real instrument data')}</em>}</div><span className={`analysis-state ${item.analysis_status === 'completed' ? 'complete' : 'pending'}`}>{item.analysis_status === 'completed' ? t('Analysis complete') : t('Analysis pending')}</span>{item.analysis_status === 'completed' && <div className="timeline-analysis-output">{Object.entries(item.result ?? {}).filter(([key]) => !['notice', 'tool_id', 'modality', 'filename','demo_data','demo_notice'].includes(key)).slice(0, 6).map(([key, value]) => <span key={key}><b>{key.replaceAll('_', ' ')}</b> {typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>)}</div>}</article>)}</section>}
        {!orderedSteps.length ? <div className="empty-hint">{t('This run has no process steps to display.')}</div> : <div className="timeline-track">{orderedSteps.map((step, index) => {
          const logs = (selected.step_logs ?? []).filter((item) => item.step_id === step.id).sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
          const images = (selected.attachments ?? []).filter((item) => item.step_id === step.id);
          const env = (selected.environment_records ?? []).filter((item) => item.step_id === step.id);
          const stageRuns = (selectedProcessGroup?.entries ?? [selected]).map(run => ({
            run,
            step: run.steps.find(item => item.order_index === step.order_index) ?? run.steps.find(item => item.name === step.name),
          }));
          const partialRuns = stageRuns.flatMap(({ run, step: runStep }) => (run.stage_experiments ?? []).filter(item => item.step_id === runStep?.id).map(item => ({ ...item, run })));
          const partialConditionNames = [...new Set(partialRuns.flatMap(item => item.conditions.map(value => value.name)))];
          const partialResultNames = [...new Set(partialRuns.flatMap(item => item.results.map(value => value.name)))];
          const stageVariableNames = [...new Set(stageRuns.flatMap(({ step: runStep }) => runStep?.variables.map(variable => variable.name) ?? []))];
          return <article className="timeline-step card" key={step.id}>
            <div className="timeline-step-marker"><span>{index + 1}</span><small>{index === 0 ? t('Start') : index === orderedSteps.length - 1 ? t('Finish') : t('Step')}</small></div>
            <div className="timeline-step-content">
              <header className="timeline-step-head"><div><h3>{step.name}</h3>{step.description && <p>{step.description}</p>}</div><span className="timeline-step-count">{logs.length + images.length + step.variables.length + env.length + partialRuns.length} {t('records')}</span></header>
              <div className="timeline-step-grid">
                <section className="timeline-data-block timeline-stage-history"><h4>{t('Conditions and intermediate records')}</h4><div className="process-experiment-table-wrap"><table className="process-experiment-table process-stage-table"><thead><tr><th>{t('Date')}</th><th>{t('Sub-experiment')}</th><th>{t('Status')}</th>{stageVariableNames.map(name => <th key={name}>{name}</th>)}<th>{t('Intermediate values and observations')}</th></tr></thead><tbody>{stageRuns.map(({ run, step: runStep }, runIndex) => {
                  const runLogs = (run.step_logs ?? []).filter(item => item.step_id === runStep?.id).sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
                  return <tr key={run.id} className={run.id === selected.id ? 'selected' : undefined}>
                    <td className="process-experiment-date">{run.date || '—'}</td><td><button type="button" className="process-experiment-title" onClick={() => setSelectedId(run.id)}><b>{run.name}</b><small>{run.code} · {t('Experiment')} {run.method_run_number ?? runIndex + 1}</small></button></td><td><span className={`status ${run.status}`}>{t(run.status.replace('_', ' '))}</span></td>
                    {stageVariableNames.map(name => { const variable = runStep?.variables.find(item => item.name === name); return <td key={name}>{variable ? `${variable.value}${variable.unit ? ` ${variable.unit}` : ''}` : '—'}</td>; })}
                    <td className="process-intermediate-cell">{runLogs.length ? runLogs.map(item => <div className="process-intermediate-record" key={item.id}><b>{item.label}</b>{item.value && ` · ${item.value} ${item.unit ?? ''}`}{item.notes && <small>{item.notes}</small>}{run.id === selected.id && <button className="icon-button" title={t('Remove')} onClick={() => void removeLog(item.id)}><Trash2 size={13}/></button>}</div>) : '—'}</td>
                  </tr>;
                })}</tbody></table></div></section>
                <section className="timeline-data-block"><h4>{t('Environment')}</h4>{env.length ? env.map((item) => <div className="timeline-event-line" key={item.id}><Clock3 size={13}/><div><b>{t(item.phase)} · {new Date(item.measured_at).toLocaleString()}</b><span>{item.temperature_c != null && `${t('Ambient temperature')} ${item.temperature_c} °C`}{item.relative_humidity_percent != null && ` · ${t('Relative humidity')} ${item.relative_humidity_percent}%`}{item.pressure_kpa != null && ` · ${t('Ambient pressure')} ${item.pressure_kpa} kPa`}</span>{item.notes && <small>{item.notes}</small>}</div></div>) : <small>{t('No environment measurements recorded.')}</small>}</section>
              </div>
              <section className="timeline-data-block timeline-partial-experiments"><header className="timeline-partial-head"><div><h4>{t('Partial experiments in this stage')}</h4><small>{t('Split a stage into focused trials; each trial keeps its own date, conditions, and results.')}</small></div><button type="button" className="button outline small" onClick={() => { setEditingSubexperiment(null); setShowSubexperimentForm(true); }}><Plus size={13}/>{t('Add partial experiment')}</button></header>
                {partialRuns.length ? <div className="process-experiment-table-wrap"><table className="process-experiment-table process-stage-table"><thead><tr><th>{t('Date')}</th><th>{t('Parent experiment')}</th><th>{t('Partial experiment')}</th><th>{t('Status')}</th>{partialConditionNames.map(name => <th key={`c-${name}`}>{name}</th>)}{partialResultNames.map(name => <th key={`r-${name}`}>{name}</th>)}<th>{t('Notes')}</th><th>{t('Actions')}</th></tr></thead><tbody>{partialRuns.sort((a,b) => a.performed_at.localeCompare(b.performed_at)).map(item => <tr key={item.id}><td>{new Date(item.performed_at).toLocaleDateString()}</td><td>{item.run.name}</td><td><b>{item.name}</b></td><td><span className={`status ${item.status}`}>{t(item.status)}</span></td>{partialConditionNames.map(name => { const value=item.conditions.find(entry=>entry.name===name); return <td key={`c-${name}`}>{value ? `${value.value}${value.unit ? ` ${value.unit}` : ''}` : '—'}</td>; })}{partialResultNames.map(name => { const value=item.results.find(entry=>entry.name===name); return <td key={`r-${name}`}>{value ? `${value.value}${value.unit ? ` ${value.unit}` : ''}` : '—'}</td>; })}<td>{item.notes || '—'}</td><td><div className="timeline-partial-actions"><button type="button" className="text-button" onClick={() => setEditingSubexperiment(item)}>{t('Edit')}</button><button type="button" className="icon-button" title={t('Remove')} onClick={() => void removeSubexperiment(item)}><Trash2 size={13}/></button></div></td></tr>)}</tbody></table></div> : <p className="timeline-partial-empty">{t('No partial experiments recorded in this stage yet.')}</p>}
                {(editingSubexperiment || showSubexperimentForm) && <details className="timeline-add-details" open><summary><Plus size={14}/>{editingSubexperiment ? t('Edit partial experiment') : t('Record a partial experiment')}</summary><form key={`${step.id}-${editingSubexperiment?.id ?? 'new'}`} className="timeline-subexperiment-form" onSubmit={event => void saveSubexperiment(event, step.id)}><div className="timeline-subexperiment-fields"><label>{t('Partial experiment name')}<input name="name" required maxLength={200} defaultValue={editingSubexperiment?.name ?? ''} placeholder={t('e.g. Change precursor concentration')}/></label><label>{t('Date')}<input name="performed_at" type="date" defaultValue={editingSubexperiment?.performed_at.slice(0,10) ?? new Date().toISOString().slice(0,10)}/></label><label>{t('Status')}<select name="status" defaultValue={editingSubexperiment?.status ?? 'recorded'}><option value="recorded">{t('recorded')}</option><option value="success">{t('success')}</option><option value="failed">{t('failed')}</option><option value="inconclusive">{t('inconclusive')}</option></select></label></div><div className="timeline-subexperiment-fields"><label>{t('Conditions')}<textarea name="conditions" rows={3} defaultValue={editingSubexperiment?.conditions.map(value => `${value.name} | ${value.value} | ${value.unit ?? ''}`).join('\n') ?? ''} placeholder={t('One per line: variable | value | unit')}/></label><label>{t('Results')}<textarea name="results" rows={3} defaultValue={editingSubexperiment?.results.map(value => `${value.name} | ${value.value} | ${value.unit ?? ''}`).join('\n') ?? ''} placeholder={t('One per line: result | value | unit')}/></label><label>{t('Notes')}<textarea name="notes" rows={3} defaultValue={editingSubexperiment?.notes ?? ''} placeholder={t('Notes')}/></label></div><div className="timeline-subexperiment-buttons"><button className="button primary small" disabled={busy}>{busy ? t('Saving…') : editingSubexperiment ? t('Save changes') : t('Save partial experiment')}</button>{editingSubexperiment && <button type="button" className="button outline small" onClick={() => { setEditingSubexperiment(null); setShowSubexperimentForm(false); }}>{t('Cancel')}</button>}</div></form></details>}
              </section>
              {!!images.length && <section className="timeline-data-block"><h4>{t('Stage images')}</h4><div className="timeline-gallery">{images.map((image) => <figure key={image.id}><a href={image.image_url} target="_blank" rel="noreferrer"><img src={image.image_url} alt={image.caption || image.filename}/></a><figcaption>{image.caption || image.filename}<button className="icon-button" title={t('Remove')} onClick={() => void removeImage(image.id)}><Trash2 size={12}/></button></figcaption></figure>)}</div></section>}
              <details className="timeline-add-details"><summary><Plus size={14}/>{t('Add a measurement or observation')}</summary><form className="timeline-log-form" onSubmit={(event) => void addLog(event, step.id)}><select name="kind" aria-label={t('Record type')}><option value="measurement">{t('Measurement')}</option><option value="observation">{t('Observation')}</option><option value="result">{t('Intermediate result')}</option></select><input name="label" required placeholder={t('e.g. pH, color, particle size')}/><input name="value" placeholder={t('Value or description')}/><input name="unit" placeholder={t('Unit')}/><input name="notes" placeholder={t('Notes')}/><button className="button primary small" disabled={busy}><Plus size={13}/>{t('Save record')}</button></form></details>
              <details className="timeline-add-details"><summary><Camera size={14}/>{t('Attach a photo to this step')}</summary><div className="timeline-image-form"><input value={captions[step.id] ?? ''} onChange={(event) => setCaptions((current) => ({ ...current, [step.id]: event.target.value }))} placeholder={t('Photo caption or sample label')}/><label className="button outline small"><Camera size={13}/>{busy ? t('Saving…') : t('Choose image')}<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" hidden disabled={busy} onChange={(event) => { void addImage(event.target.files?.[0], step.id); event.currentTarget.value = ''; }}/></label><small>{t('JPEG, PNG, WebP, or GIF · up to 15 MiB')}</small></div></details>
            </div>
          </article>;
        })}</div>}
        </section>
      </>}
    </>}
  </section>;
}

function RunSelectionCard({run,processName,selected,onSelect}:{run:Experiment;processName:string;selected:boolean;onSelect:()=>void}){
  const{t}=useLanguage();
  return <button type="button" className={`timeline-run-select-card ${selected?'selected':''}`} aria-pressed={selected} onClick={onSelect}>
    <span className="timeline-run-select-head"><b>{run.code} · {t(run.name)}</b><span className={`status ${run.status}`}>{t(run.status.replace('_',' '))}</span></span>
    <small>{run.date||t('Date not recorded')} · {processName} · {t(run.target)}</small>
    {!!run.steps.length&&<span className="timeline-run-select-stages">{[...run.steps].sort((a,b)=>a.order_index-b.order_index).map((step,index)=><span key={`${step.id}-${index}`}>{index+1}. {t(step.name)}</span>)}</span>}
    {!!run.results.length&&<span className="timeline-run-select-results">{run.results.map((result,index)=><span key={`${result.key}-${index}`}><b>{t(result.key.replaceAll('_',' '))}</b> {result.value}{result.unit?` ${result.unit}`:''}</span>)}</span>}
  </button>;
}

function versionDepth(version:MethodVersion|null|undefined,versions:MethodVersion[]){let depth=0,current=version;const seen=new Set<number>();while(current?.parent_version_id&&depth<versions.length&&!seen.has(current.id)){seen.add(current.id);const parent=versions.find(item=>item.id===current?.parent_version_id);if(!parent)break;depth+=1;current=parent;}return depth}
function latestMethodVersion(method:ExperimentMethod|undefined){return method?.versions.reduce<MethodVersion|undefined>((latest,item)=>!latest||item.version_number>latest.version_number?item:latest,undefined)}
