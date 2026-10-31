import { useEffect, useMemo, useState } from 'react';
import { optimizationApi, type OptimizationCandidate, type OptimizationDatasetOptions, type OptimizationModel } from '../api/client';
import type { ResearchTopic } from '../types';
import { useLanguage } from '../language';

type Bound={min:string;max:string;unit:string};
type ConstraintDraft={id:string;kind:'linear_inequality'|'linear_equality'|'variable_relation';parameterId:string;otherParameterId:string;sense:'le'|'ge';threshold:string;tolerance:string;unit:string};
const unitChoices=(unit:string)=>{
  const equivalents:Record<string,string[]>={kelvin:['kelvin','degC'],meter:['meter','micrometer','nanometer'],'meter ** 3':['meter ** 3','liter','milliliter'],'kilogram':['kilogram','gram'],'second':['second','minute','hour'],'dimensionless':['dimensionless']};
  return equivalents[unit]??[unit];
};

export default function OptimizationPanel({topic}:{topic:ResearchTopic}){
  const {t}=useLanguage();
  const [mode,setMode]=useState<'sandbox'|'research'>('sandbox');
  const [sandboxKind,setSandboxKind]=useState<'branin'|'noisy'|'constrained'>('branin');
  const [methodVersionId,setMethodVersionId]=useState<number>(topic.methods?.[0]?.versions?.[0]?.id??0);
  const [options,setOptions]=useState<OptimizationDatasetOptions|null>(null);
  const [featureIds,setFeatureIds]=useState<string[]>([]);
  const [targetId,setTargetId]=useState('');
  const [featureStepId,setFeatureStepId]=useState<number|null>(null);
  const [targetStepId,setTargetStepId]=useState<number|null>(null);
  const [pairingPolicy,setPairingPolicy]=useState<'same_step'|'downstream_explicit'>('same_step');
  const [linkConfirmed,setLinkConfirmed]=useState(false);
  const [relationLabel,setRelationLabel]=useState('');
  const [replicatePolicy,setReplicatePolicy]=useState<'preserve'|'inverse_variance_mean'>('preserve');
  const [bounds,setBounds]=useState<Record<string,Bound>>({});
  const [constraints,setConstraints]=useState<ConstraintDraft[]>([]);
  const [acquisition,setAcquisition]=useState<'ei'|'pi'|'ucb'|'noisy_ei'>('ei');
  const [maximize,setMaximize]=useState(false);
  const [kernel,setKernel]=useState<'matern'|'rbf'>('matern');
  const [candidateCount,setCandidateCount]=useState(5);
  const [searchBudget,setSearchBudget]=useState(3000);
  const [model,setModel]=useState<OptimizationModel|null>(null);
  const [candidates,setCandidates]=useState<OptimizationCandidate[]>([]);
  const [benchmark,setBenchmark]=useState<any>(null);
  const [stage2Benchmark,setStage2Benchmark]=useState<any>(null);
  const [datasetSummary,setDatasetSummary]=useState<any>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const versions=useMemo(()=>topic.methods?.flatMap(method=>method.versions.map(version=>({id:version.id,label:`${method.name} · v${version.version_label??version.version_number}`})))??[],[topic]);

  useEffect(()=>{
    setMethodVersionId(topic.methods?.[0]?.versions?.[0]?.id??0);setOptions(null);setModel(null);setCandidates([]);setDatasetSummary(null);
  },[topic.id,topic.methods]);
  useEffect(()=>{
    if(mode!=='research'||!topic.id||!methodVersionId){setOptions(null);return}
    let active=true;
    optimizationApi.datasetOptions(topic.id,methodVersionId).then(value=>{
      if(!active)return;
      setOptions(value);
      setFeatureIds(current=>current.filter(id=>value.features.some(option=>option.parameter_id===id)));
      setTargetId(current=>value.outcomes.some(option=>option.parameter_id===current)?current:'');
      setFeatureStepId(current=>current??value.process_steps[0]?.id??null);
      setTargetStepId(current=>current??value.process_steps[0]?.id??null);
    }).catch(reason=>{if(active)setError(reason instanceof Error?reason.message:String(reason))});
    return()=>{active=false};
  },[mode,topic.id,methodVersionId]);

  useEffect(()=>{
    setBounds(current=>{
      const next={...current};
      for(const id of featureIds){const source=options?.features.find(item=>item.parameter_id===id);if(source&&!next[id])next[id]={min:'',max:'',unit:source.unit}}
      return Object.fromEntries(Object.entries(next).filter(([id])=>featureIds.includes(id)));
    });
  },[featureIds,options]);

  const toggleFeature=(id:string)=>setFeatureIds(current=>current.includes(id)?current.filter(value=>value!==id):[...current,id]);
  const updateBound=(id:string,key:keyof Bound,value:string)=>setBounds(current=>({...current,[id]:{...(current[id]??{min:'',max:'',unit:''}),[key]:value}}));
  const addConstraint=()=>{
    const first=featureIds[0]??'';
    setConstraints(current=>[...current,{id:crypto.randomUUID(),kind:'linear_inequality',parameterId:first,otherParameterId:featureIds[1]??first,sense:'le',threshold:'',tolerance:'0',unit:bounds[first]?.unit??''}]);
  };
  const updateConstraint=(id:string,patch:Partial<ConstraintDraft>)=>setConstraints(current=>current.map(item=>item.id===id?{...item,...patch}:item));
  const versionsForResearch=mode==='research'&&methodVersionId>0;

  const buildConstraintPayload=()=>constraints.map(item=>{
    if(item.kind==='variable_relation')return {constraint_id:item.id,type:item.kind,left_parameter_id:item.parameterId,right_parameter_id:item.otherParameterId,relation:item.sense};
    const threshold=Number(item.threshold);
    if(!Number.isFinite(threshold))throw new Error(t('Enter a finite threshold for every constraint.'));
    if(item.kind==='linear_equality')return {constraint_id:item.id,type:item.kind,parameter_ids:[item.parameterId],coefficients:[1],coefficient_units:['dimensionless'],threshold,unit:item.unit,tolerance:Number(item.tolerance||0)};
    return {constraint_id:item.id,type:item.kind,parameter_ids:[item.parameterId],coefficients:[1],coefficient_units:['dimensionless'],threshold,unit:item.unit,sense:item.sense};
  });

  const run=async()=>{
    setBusy(true);setError('');setCandidates([]);setBenchmark(null);setStage2Benchmark(null);setDatasetSummary(null);
    try{
      if(mode==='sandbox'&&sandboxKind!=='branin'){
        setStage2Benchmark(await optimizationApi.stage2Benchmark(topic.id,sandboxKind,12,5,0.08,7));
        return;
      }
      if(mode==='research'){
        if(!versionsForResearch||featureIds.length===0||!targetId)throw new Error(t('Choose a method version, input variables, and measured outcome.'));
        const rangePairs=featureIds.map(id=>{
          const bound=bounds[id];
          if(!bound||bound.min===''||bound.max===''||!Number.isFinite(Number(bound.min))||!Number.isFinite(Number(bound.max))||Number(bound.min)>=Number(bound.max))
            throw new Error(`${id}: ${t('Enter a finite increasing range.')}`);
          return [Number(bound.min),Number(bound.max)];
        });
        if(pairingPolicy==='downstream_explicit'&&(!featureStepId||!targetStepId||!linkConfirmed||!relationLabel.trim()))
          throw new Error(t('Confirm the selected downstream relationship and describe it.'));
        const preview=await fetchDatasetPreview();
        setDatasetSummary(preview);
        const trained=await optimizationApi.train({topic_id:topic.id,mode,feature_ids:featureIds,target_id:targetId,method_version_id:methodVersionId,
          process_step_id:featureStepId,target_process_step_id:targetStepId,pairing_policy:pairingPolicy,
          downstream_link_confirmed:linkConfirmed,downstream_relation_label:relationLabel.trim()||undefined,replicate_policy:replicatePolicy,kernel,seed:7});
        setModel(trained);
        const payload=buildConstraintPayload();
        const recommendation=await optimizationApi.recommend(trained.model_id,{topic_id:topic.id,acquisition,bounds:rangePairs,
          bounds_units:featureIds.map(id=>bounds[id].unit),maximize,candidate_count:candidateCount,search_samples:searchBudget,seed:7,
          constraints:payload,prediction_type:'latent',noisy_ei_samples:256});
        setCandidates(recommendation.candidates);
      }else{
        const trained=await optimizationApi.train({topic_id:topic.id,mode,feature_ids:['x1','x2'],target_id:'branin',kernel,seed:7});
        setModel(trained);
        const recommendation=await optimizationApi.recommend(trained.model_id,{topic_id:topic.id,acquisition,bounds:[[-5,10],[0,15]],bounds_units:['dimensionless','dimensionless'],
          maximize:false,candidate_count:candidateCount,search_samples:searchBudget,seed:7,prediction_type:'latent',noisy_ei_samples:256});
        setCandidates(recommendation.candidates);
        setBenchmark(await optimizationApi.benchmark(topic.id,20,7));
      }
    }catch(reason){setError(reason instanceof Error?reason.message:String(reason))}finally{setBusy(false)}
  };

  async function fetchDatasetPreview(){
    const query=new URLSearchParams({topic_id:String(topic.id),method_version_id:String(methodVersionId),feature_ids:featureIds.join(','),target_id:targetId,
      pairing_policy:pairingPolicy,replicate_policy:replicatePolicy});
    if(featureStepId)query.set('process_step_id',String(featureStepId));
    if(targetStepId)query.set('target_process_step_id',String(targetStepId));
    if(linkConfirmed)query.set('downstream_link_confirmed','true');
    if(relationLabel.trim())query.set('downstream_relation_label',relationLabel.trim());
    const response=await fetch(`/api/optimization/dataset?${query.toString()}`);
    const result=await response.json();
    if(!response.ok)throw new Error(result?.detail?.message??JSON.stringify(result.detail??result));
    return result;
  }

  const updateStepPair=(value:number|null)=>{setFeatureStepId(value);if(pairingPolicy==='same_step')setTargetStepId(value)};
  const changePairing=(value:'same_step'|'downstream_explicit')=>{
    setPairingPolicy(value);setLinkConfirmed(false);setRelationLabel('');
    if(value==='same_step')setTargetStepId(featureStepId);
  };
  const features=options?.features??[];const outcomes=options?.outcomes??[];const processSteps=options?.process_steps??[];

  return <div className="optimization-workspace">
    <section className="card optimization-setup">
      <div className="card-head"><div><div className="card-title">{t('Gaussian process optimization')}</div><div className="card-sub">{t('Fit a probabilistic model and rank next conditions within explicit bounds.')}</div></div><span className="badge">{mode==='sandbox'?t('SANDBOX'):t('RESEARCH DATA')}</span></div>
      <div className="optimization-mode"><button className={mode==='sandbox'?'active':''} onClick={()=>{setMode('sandbox');setModel(null);setCandidates([])}}>{t('Synthetic sandbox')}</button><button className={mode==='research'?'active':''} onClick={()=>{setMode('research');setModel(null);setCandidates([])}}>{t('Approved research data')}</button></div>
      {mode==='sandbox'?<div className="optimization-fields optimization-sandbox-controls">
        <label>{t('Sandbox benchmark')}<select value={sandboxKind} onChange={event=>setSandboxKind(event.target.value as typeof sandboxKind)}><option value="branin">Branin · {t('noise-free')}</option><option value="noisy">{t('Noisy objective · Standard EI vs Noisy EI')}</option><option value="constrained">{t('Constrained Branin · feasible search')}</option></select></label>
        <div className="optimization-note"><b>{sandboxKind==='branin'?'Branin':sandboxKind==='noisy'?t('Noisy objective'):t('Constrained Branin')}</b><span>{t('Uses isolated synthetic mathematical functions. Sandbox records never enter research observations.')}</span><small>{sandboxKind==='branin'?'x1: −5…10 · x2: 0…15':sandboxKind==='noisy'?'5 seeds · shared initial design · reported measurement noise':'Branin · feasible condition: x1 + x2 ≤ 9'}</small></div>
      </div>:<>
        <div className="optimization-fields">
          <label>{t('Method version')}<select value={methodVersionId} onChange={event=>{setMethodVersionId(Number(event.target.value));setOptions(null);setDatasetSummary(null)}}><option value={0}>{t('Choose a method version')}</option>{versions.map(version=><option key={version.id} value={version.id}>{version.label}</option>)}</select></label>
          <label>{t('Measured outcome')}<select value={targetId} onChange={event=>setTargetId(event.target.value)} disabled={!options}><option value="">{t('Choose approved measured outcome')}</option>{outcomes.map(item=><option key={`${item.parameter_id}:${item.unit}`} value={item.parameter_id}>{item.parameter_id} · {item.unit} · {item.experiment_count} {t('experiments')}</option>)}</select></label>
          <fieldset className="optimization-feature-select"><legend>{t('Input process variables')}</legend>{features.length?features.map(item=><label key={`${item.parameter_id}:${item.unit}`}><input type="checkbox" checked={featureIds.includes(item.parameter_id)} onChange={()=>toggleFeature(item.parameter_id)}/><span>{item.parameter_id}</span><small>{item.unit} · {item.experiment_count} {t('experiments')}</small></label>):<small>{options?t('No approved input variables found for this method version.'):t('Choose a method version to load approved variables.')}</small>}</fieldset>
        </div>
        <div className="optimization-fields optimization-pairing">
          <label>{t('Feature process step')}<select value={featureStepId??''} onChange={event=>updateStepPair(event.target.value?Number(event.target.value):null)}><option value="">{t('No specific process step')}</option>{processSteps.map(step=><option key={`${step.id}:${step.order_index}`} value={step.id}>{step.order_index+1}. {step.name} · {step.experiment_count} {t('experiments')}</option>)}</select></label>
          <label>{t('Outcome process step')}<select value={targetStepId??''} disabled={pairingPolicy==='same_step'} onChange={event=>setTargetStepId(event.target.value?Number(event.target.value):null)}><option value="">{t('No specific process step')}</option>{processSteps.map(step=><option key={`${step.id}:${step.order_index}`} value={step.id}>{step.order_index+1}. {step.name} · {step.experiment_count} {t('experiments')}</option>)}</select></label>
          <label>{t('Observation pairing')}<select value={pairingPolicy} onChange={event=>changePairing(event.target.value as typeof pairingPolicy)}><option value="same_step">{t('Same process step')}</option><option value="downstream_explicit">{t('Explicit downstream outcome')}</option></select></label>
          <label>{t('Replicate handling')}<select value={replicatePolicy} onChange={event=>setReplicatePolicy(event.target.value as typeof replicatePolicy)}><option value="preserve">{t('Keep each replicate')}</option><option value="inverse_variance_mean">{t('Inverse-variance mean (known uncertainty only)')}</option></select></label>
        </div>
        {pairingPolicy==='downstream_explicit'&&<div className="optimization-downstream-confirm"><label className="optimization-check"><input type="checkbox" checked={linkConfirmed} onChange={event=>setLinkConfirmed(event.target.checked)}/>{t('I confirm that this later measurement is the outcome linked to the selected process input.')}</label><label>{t('Describe the selected relationship')}<input value={relationLabel} onChange={event=>setRelationLabel(event.target.value)} placeholder={t('Example: growth temperature → final length')}/></label><small>{t('Step order supports pairing only; it does not prove causality.')}</small></div>}
        <div className="optimization-bound-list"><div className="optimization-section-title">{t('Search bounds · enter values in selected units')}</div>{featureIds.length?featureIds.map(id=>{const bound=bounds[id]??{min:'',max:'',unit:features.find(item=>item.parameter_id===id)?.unit??''};return <div className="optimization-bound-row" key={id}><b>{id}</b><input type="number" value={bound.min} onChange={event=>updateBound(id,'min',event.target.value)} placeholder={t('Minimum')}/><span>–</span><input type="number" value={bound.max} onChange={event=>updateBound(id,'max',event.target.value)} placeholder={t('Maximum')}/><select value={bound.unit} onChange={event=>updateBound(id,'unit',event.target.value)}>{unitChoices(bound.unit).map(unit=><option key={unit}>{unit}</option>)}</select><small>{t('stored unit')}: {features.find(item=>item.parameter_id===id)?.unit}</small></div>}):<small>{t('Select at least one input variable.')}</small>}</div>
        <div className="optimization-constraint-list"><div className="optimization-section-title">{t('Deterministic constraints')} <button type="button" className="button secondary" onClick={addConstraint} disabled={!featureIds.length}>{t('Add constraint')}</button></div>{constraints.map(item=><div className="optimization-constraint-row" key={item.id}>
          <select value={item.kind} onChange={event=>updateConstraint(item.id,{kind:event.target.value as ConstraintDraft['kind']})}><option value="linear_inequality">{t('Linear inequality')}</option><option value="linear_equality">{t('Linear equality with tolerance')}</option><option value="variable_relation">{t('Variable relation')}</option></select>
          <select value={item.parameterId} onChange={event=>{const unit=bounds[event.target.value]?.unit??features.find(x=>x.parameter_id===event.target.value)?.unit??'';updateConstraint(item.id,{parameterId:event.target.value,unit})}}>{featureIds.map(id=><option key={id} value={id}>{id}</option>)}</select>
          {item.kind==='variable_relation'?<><select value={item.sense} onChange={event=>updateConstraint(item.id,{sense:event.target.value as 'le'|'ge'})}><option value="ge">≥</option><option value="le">≤</option></select><select value={item.otherParameterId} onChange={event=>updateConstraint(item.id,{otherParameterId:event.target.value})}>{featureIds.filter(id=>id!==item.parameterId).map(id=><option key={id}>{id}</option>)}</select></>:<><select value={item.sense} onChange={event=>updateConstraint(item.id,{sense:event.target.value as 'le'|'ge'})}><option value="le">≤</option><option value="ge">≥</option></select><input type="number" value={item.threshold} onChange={event=>updateConstraint(item.id,{threshold:event.target.value})} placeholder={t('Threshold')}/><select value={item.unit} onChange={event=>updateConstraint(item.id,{unit:event.target.value})}>{unitChoices(item.unit).map(unit=><option key={unit}>{unit}</option>)}</select>{item.kind==='linear_equality'&&<input type="number" min="0" value={item.tolerance} onChange={event=>updateConstraint(item.id,{tolerance:event.target.value})} placeholder={t('Tolerance')}/>}</>}
          <button type="button" className="button secondary" onClick={()=>setConstraints(current=>current.filter(value=>value.id!==item.id))}>{t('Remove')}</button>
        </div>)}</div>
      </>}
      <div className="optimization-controls">
        <label>{t('GP kernel')}<select value={kernel} onChange={event=>setKernel(event.target.value as typeof kernel)}><option value="matern">Matérn 5/2</option><option value="rbf">RBF</option></select></label>
        {sandboxKind==='branin'||mode==='research'?<><label>{t('Acquisition')}<select value={acquisition} onChange={event=>setAcquisition(event.target.value as typeof acquisition)}><option value="ei">{t('Expected Improvement')}</option><option value="noisy_ei">{t('Monte Carlo Noisy EI')}</option><option value="pi">{t('Probability of Improvement')}</option><option value="ucb">{t('Upper Confidence Bound')}</option></select></label><label>{t('Objective')}<select disabled={mode==='sandbox'} value={maximize?'max':'min'} onChange={event=>setMaximize(event.target.value==='max')}><option value="min">{t('Minimize')}</option><option value="max">{t('Maximize')}</option></select></label><label>{t('Candidate count')}<input type="number" min="1" max="20" value={candidateCount} onChange={event=>setCandidateCount(Number(event.target.value))}/></label><label>{t('Search budget')}<input type="number" min="200" max="30000" step="100" value={searchBudget} onChange={event=>setSearchBudget(Number(event.target.value))}/></label></>:<span className="optimization-note-inline">{t('Benchmark uses a shared initial design and equal evaluation budget.')}</span>}
        <button className="button primary" disabled={busy||!topic.id||(mode==='research'&&(!methodVersionId||!featureIds.length||!targetId))} onClick={()=>void run()}>{busy?t('Running model and checks…'):mode==='sandbox'&&sandboxKind!=='branin'?t('Run benchmark'):t('Train GP and recommend')}</button>
      </div>
      <p className="optimization-safety">{t('Recommendations are computational candidates only. Uncertainty is not experimental success probability. Human review is required; this screen never executes an experiment.')}</p>
      {error&&<div className="error">{error}</div>}
    </section>
    {options&&mode==='research'&&<section className="card optimization-counts"><div className="card-title">{t('Approved data available in this method version')}</div><div className="optimization-metrics"><Metric label={t('Independent experiments')} value={options.counts.independent_experiment_count}/><Metric label={t('Approved observations')} value={options.counts.observation_count}/><Metric label={t('Replicates')} value={options.counts.replicate_count}/></div><small>{t('Counts are available records before selected feature/outcome pairing.')}</small></section>}
    {datasetSummary&&<section className="card optimization-counts"><div className="card-title">{t('Paired training dataset')}</div><div className="optimization-metrics"><Metric label={t('Independent experiments')} value={datasetSummary.independent_experiment_count}/><Metric label={t('Replicate groups')} value={datasetSummary.unique_replicate_count}/><Metric label={t('Paired observations')} value={datasetSummary.paired_observation_count}/><Metric label={t('Effective GP rows')} value={datasetSummary.effective_training_sample_count}/></div><small>{datasetSummary.pairing_policy} · {datasetSummary.replicate_policy} · {datasetSummary.causality_notice}</small></section>}
    {model&&<section className="card optimization-results"><div className="card-head"><div><div className="card-title">{t('Model result')} · #{model.model_id}</div><div className="card-sub">{model.mode==='sandbox'?t('Synthetic sandbox model'):t('Approved measured data model')} · {model.config.dataset_counts?.independent_experiment_count??model.config.sample_count} {t('independent experiments')} · {model.config.sample_count} {t('effective GP rows')} · {model.config.kernel}</div></div><span className="badge">{model.model_version}</span></div>
      <div className="optimization-metrics"><Metric label="RMSE · holdout" value={model.metrics.rmse}/><Metric label="MAE · holdout" value={model.metrics.mae}/><Metric label="95% interval coverage · holdout" value={model.metrics.coverage_95}/><Metric label={t('Validation groups')} value={model.config.validation_group_count}/></div><small>{model.config.validation_scheme} · {model.config.validation_rows} {t('validation rows')} · {t('Small-data validation is uncertain.')}</small>
      <small className="dataset-hash">Dataset SHA-256 · {model.dataset_hash}</small>
      <small className="optimization-assumption">{model.config.uncertainty_interpretation}</small>
      {candidates.length>0&&<div className="table-wrap"><table><thead><tr><th>{t('Rank')}</th><th>{t('Parameter values')}</th><th>{t('Predicted outcome')}</th><th>{t('Epistemic')}</th><th>{t('Aleatoric')}</th><th>{t('Total uncertainty')}</th><th>{t('Acquisition score')}</th><th>{t('Constraint')}</th><th>{t('Review')}</th></tr></thead><tbody>{candidates.map(candidate=><tr key={candidate.rank}><td>{candidate.rank}</td><td>{candidate.values.map((value,index)=>`${value.toPrecision(5)} ${candidate.units[index]??''}`).join(' · ')}</td><td>{candidate.predicted_mean.toPrecision(5)}</td><td>± {candidate.epistemic_std.toPrecision(3)}</td><td>± {candidate.aleatoric_std.toPrecision(3)}</td><td>± {candidate.total_predictive_std.toPrecision(3)}</td><td>{candidate.acquisition_score.toPrecision(5)}</td><td>{candidate.feasibility_status}</td><td>{t('Researcher review required')}</td></tr>)}</tbody></table></div>}
    </section>}
    {benchmark&&<section className="card optimization-results"><div className="card-title">{t('Sandbox optimization comparison')} · {benchmark.function}</div><div className="optimization-metrics"><Metric label={t('Random Search median best')} value={benchmark.policies.random_search.median_best}/><Metric label={t('Latin Hypercube median best')} value={benchmark.policies.latin_hypercube.median_best}/><Metric label={t('GP + EI median best')} value={benchmark.policies.gp_ei.median_best}/><Metric label={t('GP + UCB median best')} value={benchmark.policies.gp_ucb.median_best}/></div><div className="card-sub">{benchmark.seeds} {t('seeds')} · {benchmark.initial_points} {t('shared initial points')} · {benchmark.additional_evaluations} {t('additional evaluations')} · {t('Lower objective is better')} · {t('Known optimum')}: {benchmark.known_global_minimum_approx}</div><p className="optimization-safety">{benchmark.notice}</p></section>}
    {stage2Benchmark&&<Stage2Benchmark result={stage2Benchmark} t={t}/>}
  </div>;
}

function Stage2Benchmark({result,t}:{result:any;t:(value:string)=>string}){
  return <section className="card optimization-results optimization-stage2-results"><div className="card-title">{t('Phase 4 · Stage 2 synthetic benchmark')}</div><div className="optimization-benchmark-grid">
    {result.noisy&&<article><h4>{t('Noisy optimization')} · σ={result.noisy.noise_std}</h4><small>{result.noisy.seeds??result.seeds} {t('seeds')} · {result.additional_evaluations} {t('additional evaluations')} · {t('Known minimum')}: {result.noisy.known_minimum_approx.toPrecision(5)}</small><table><thead><tr><th>{t('Policy')}</th><th>{t('Median true best')}</th><th>{t('Median measured best')}</th><th>{t('Mean regret')}</th><th>{t('Recommendation variability')}</th></tr></thead><tbody>{Object.entries(result.noisy.policies).map(([name,value]:[string,any])=><tr key={name}><td>{name}</td><td>{value.median_best_true_objective.toPrecision(5)}</td><td>{value.median_best_observed_objective.toPrecision(5)}</td><td>{value.mean_simple_regret.toPrecision(5)}</td><td>{value.recommendation_location_std.toPrecision(4)}</td></tr>)}</tbody></table></article>}
    {result.constrained&&<article><h4>{t('Constrained optimization')}</h4><small>{result.constrained.seeds??result.seeds} {t('seeds')} · {result.additional_evaluations} {t('additional evaluations')} · {result.constrained.constraint}</small><table><thead><tr><th>{t('Policy')}</th><th>{t('Feasible suggestion rate')}</th><th>{t('Constraint violations')}</th><th>{t('Median best feasible')}</th><th>{t('Mean regret')}</th></tr></thead><tbody>{Object.entries(result.constrained.policies).map(([name,value]:[string,any])=><tr key={name}><td>{name}</td><td>{(100*value.feasible_recommendation_rate).toFixed(1)}%</td><td>{value.constraint_violation_count}</td><td>{value.median_best_feasible_objective?.toPrecision(5)??'—'}</td><td>{value.mean_simple_regret?.toPrecision(5)??'—'}</td></tr>)}</tbody></table><p className="optimization-safety">{result.constrained.notice}</p></article>}
    </div><p className="optimization-safety">{result.notice}</p></section>;
}

function Metric({label,value}:{label:string;value:number|undefined}){return <div className="optimization-metric"><small>{label}</small><b>{typeof value==='number'?value.toPrecision(5):'—'}</b></div>}
