import { useState, type FormEvent } from 'react';
import { Plus, Search, Trash2 } from 'lucide-react';
import { useLanguage } from '../language';
import { techniqueCategories, techniqueTemplates, type TechniqueCategory, type TechniqueTemplate } from '../techniques';

type VariableDraft = { name: string; value: string; unit: string; material: string };
type StepDraft = { name: string; description: string; variables: VariableDraft[] };
type ListDraft = { key: string; value: string; unit: string };
type MaterialDraft = { name: string; amount: string; unit: string; role: string; lot_number: string; supplier: string };
type ObservationDraft = { category: string; description: string };

const blankVariable = (): VariableDraft => ({ name: '', value: '', unit: '', material: '' });
const blankStep = (): StepDraft => ({ name: '', description: '', variables: [blankVariable()] });

export default function ExperimentForm({ onSave, onCancel, busy }: { onSave: (payload: object) => Promise<void>; onCancel: () => void; busy: boolean }) {
  const { t } = useLanguage();
  const [name, setName] = useState('');
  const [target, setTarget] = useState('');
  const [date, setDate] = useState('');
  const [durationMinutes, setDurationMinutes] = useState('');
  const [operator, setOperator] = useState('');
  const [status, setStatus] = useState('planned');
  const [notes, setNotes] = useState('');
  const [steps, setSteps] = useState<StepDraft[]>([blankStep()]);
  const [activeStep, setActiveStep] = useState(0);
  const [category, setCategory] = useState<TechniqueCategory | 'all'>('all');
  const [techniqueQuery, setTechniqueQuery] = useState('');
  const [templateNotice, setTemplateNotice] = useState('');
  const [results, setResults] = useState<ListDraft[]>([]);
  const [materials, setMaterials] = useState<MaterialDraft[]>([]);
  const [observations, setObservations] = useState<ObservationDraft[]>([]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await onSave({
      name, target, date: date || null, duration_minutes: durationMinutes.trim() ? Number(durationMinutes) : null, operator: operator || null, status, notes,
      steps: steps.filter((step) => step.name.trim()).map((step, index) => ({
        name: step.name.trim(), description: step.description, order_index: index,
        variables: step.variables.filter((variable) => variable.name.trim() && variable.value.trim()).map((variable) => ({
          name: variable.name.trim(), value: variable.value, unit: variable.unit || null, material: variable.material || null,
        })),
      })),
      materials: materials.filter((material) => material.name.trim()).map((material) => ({
        ...material, name: material.name.trim(), amount: material.amount.trim(), unit: material.unit || null,
      })),
      results: results.filter((result) => result.key.trim() && result.value.trim()).map((result) => ({ key: result.key.trim(), value: result.value, unit: result.unit || null })),
      observations: observations.filter((observation) => observation.description.trim()),
    });
  };

  const patchStep = (index: number, update: Partial<StepDraft>) => setSteps((current) => current.map((step, i) => i === index ? { ...step, ...update } : step));
  const patchVariable = (stepIndex: number, variableIndex: number, update: Partial<VariableDraft>) => setSteps((current) => current.map((step, i) => i === stepIndex ? { ...step, variables: step.variables.map((variable, j) => j === variableIndex ? { ...variable, ...update } : variable) } : step));
  const filteredTechniques = techniqueTemplates.filter((item) => (category === 'all' || item.category === category) && t(item.name).toLocaleLowerCase().includes(t(techniqueQuery).toLocaleLowerCase()));
  const applyTechnique = (template: TechniqueTemplate) => {
    const additions = template.steps.length ? template.steps.map((stepName) => ({ ...blankStep(), name: t(stepName) })) : [blankStep()];
    const isBlank = steps.length === 1 && !steps[0].name.trim() && !steps[0].variables.some((variable) => variable.name.trim() || variable.value.trim());
    const next = isBlank ? additions : [...steps, ...additions];
    setSteps(next); setActiveStep(isBlank ? 0 : steps.length); setTemplateNotice(`${t(template.name)} · ${t('Template added to map')}`);
  };

  return <form className="experiment-form" onSubmit={submit}>
    <div className="form-section-title"><span>1</span><div><b>{t('Experiment basics')}</b><small>{t('Name the sample and what you are trying to make or measure.')}</small></div></div>
    <div className="form-grid">
      <label>{t('Experiment name')}<input required maxLength={300} value={name} onChange={(event) => setName(event.target.value)} placeholder={t('e.g. ZnO nanowire growth · batch A')} /></label>
      <label>{t('Target material or outcome')}<input required maxLength={300} value={target} onChange={(event) => setTarget(event.target.value)} placeholder={t('e.g. ZnO nanowire')} /></label>
      <label>{t('Date')}<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
      <label>{t('Duration (minutes)')}<input type="number" min="0" step="1" value={durationMinutes} onChange={(event) => setDurationMinutes(event.target.value)} placeholder={t('e.g. 150')}/></label>
      <label>{t('Operator')}<input value={operator} onChange={(event) => setOperator(event.target.value)} placeholder={t('Name (optional)')} /></label>
      <label>{t('Status')}<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="planned">{t('planned')}</option><option value="running">{t('running')}</option><option value="success">{t('success')}</option><option value="partial_success">{t('partial success')}</option><option value="failure">{t('failure')}</option></select></label>
      <label className="span-two">{t('Notes')}<textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder={t('Purpose, setup, or anything Gemma should know…')} /></label>
    </div>

    <div className="form-section-title"><span>2</span><div><b>{t('Process map')}</b><small>{t('Add steps as connected nodes. Select a node to enter its action and settings.')}</small></div></div>
    <section className="technique-library"><div className="technique-library-head"><div><b>{t('Technique templates')}</b><small>{t('Pick a technique to add a starter process map. Steps contain no assumed settings; enter your actual lab values.')}</small></div><div className="technique-search"><Search size={14}/><input value={techniqueQuery} onChange={(event) => setTechniqueQuery(event.target.value)} placeholder={t('Search techniques')}/></div></div>
      <div className="technique-categories"><button type="button" className={category === 'all' ? 'active' : ''} onClick={() => setCategory('all')}>{t('All techniques')}</button>{techniqueCategories.map((item) => <button type="button" key={item.id} className={category === item.id ? 'active' : ''} onClick={() => setCategory(item.id)}>{t(item.label)}</button>)}</div>
      <div className="technique-cards">{filteredTechniques.slice(0, 10).map((item) => <button type="button" className="technique-card" key={item.id} onClick={() => applyTechnique(item)}><b>{t(item.name)}</b><small>{t(techniqueCategories.find((group) => group.id === item.category)?.label ?? 'Custom')} · {item.steps.length || 1} {t('steps')}</small><span>{t('Use technique')} <Plus size={12}/></span></button>)}{!filteredTechniques.length&&<div className="technique-empty">{t('No techniques match this search.')}</div>}</div>
      {filteredTechniques.length > 10&&<small className="technique-count">{t('Showing first 10 matches. Narrow by category or search to find a technique.')}</small>}{templateNotice&&<div className="template-notice">{templateNotice}</div>}
    </section>
    <div className="process-map-editor"><div className="process-map-track" aria-label="Ordered process map">
      {steps.map((step, index) => <div className="process-map-item" key={index}>
        <button type="button" className={`process-map-node ${activeStep === index ? 'selected' : ''} ${step.name.trim() ? 'filled' : ''}`} onClick={() => setActiveStep(index)}>
          <span className="process-node-number">{index + 1}</span><b>{step.name.trim() || t('New process step')}</b><small>{step.variables.filter((item) => item.name.trim() && item.value.trim()).length} {t('settings')}</small>
        </button>
        {index < steps.length - 1 && <span className="process-map-link" aria-hidden="true">→</span>}
      </div>)}
      <button type="button" className="process-map-add" onClick={() => { setSteps((current) => [...current, blankStep()]); setActiveStep(steps.length); }}><Plus size={15}/><span>{t('Add step')}</span></button>
    </div>
    <section className="form-step process-step-editor">{steps[activeStep] && <>
      <div className="form-step-head"><b>{t('Edit step')} {activeStep + 1}</b>{steps.length > 1 && <button type="button" className="icon-button" aria-label={t('Remove step')} onClick={() => { setSteps((current) => current.filter((_, i) => i !== activeStep)); setActiveStep((current) => Math.max(0, Math.min(current, steps.length - 2))); }}><Trash2 size={14}/></button>}</div>
      <div className="form-grid"><label>{t('Step name')}<input required value={steps[activeStep].name} onChange={(event) => patchStep(activeStep, { name: event.target.value })} placeholder={t('e.g. Hydrothermal growth')} /></label><label>{t('Description')}<input value={steps[activeStep].description} onChange={(event) => patchStep(activeStep, { description: event.target.value })} placeholder={t('What did you do?')} /></label></div>
      <div className="variable-heading"><b>{t('Process settings')}</b><span>{t('Optional · keep the unit with each value')}</span></div>
      {steps[activeStep].variables.map((variable, variableIndex) => <div className="variable-fields" key={variableIndex}>
        <input aria-label={t('Variable name')} value={variable.name} onChange={(event) => patchVariable(activeStep, variableIndex, { name: event.target.value })} placeholder={t('Setting (e.g. temperature)')} />
        <input aria-label={t('Variable value')} value={variable.value} onChange={(event) => patchVariable(activeStep, variableIndex, { value: event.target.value })} placeholder={t('Value')} />
        <input aria-label={t('Variable unit')} value={variable.unit} onChange={(event) => patchVariable(activeStep, variableIndex, { unit: event.target.value })} placeholder={t('Unit')} />
        <input aria-label={t('Material')} value={variable.material} onChange={(event) => patchVariable(activeStep, variableIndex, { material: event.target.value })} placeholder={t('Material (optional)')} />
        <button type="button" className="icon-button" aria-label={t('Remove setting')} onClick={() => patchStep(activeStep, { variables: steps[activeStep].variables.filter((_, i) => i !== variableIndex) })}><Trash2 size={13}/></button>
      </div>)}
      <button type="button" className="text-button add-inline" onClick={() => patchStep(activeStep, { variables: [...steps[activeStep].variables, blankVariable()] })}><Plus size={13}/> {t('Add process setting')}</button>
    </>}</section></div>

    <div className="form-section-title"><span>3</span><div><b>{t('Materials used')}</b><small>{t('Record each material used in this run, including its amount and unit when known.')}</small></div></div>
    <section className="form-simple-list materials-list"><div className="variable-heading"><b>{t('Materials used')}</b><button type="button" className="text-button" onClick={() => setMaterials((current) => [...current, { name: '', amount: '', unit: '', role: '', lot_number: '', supplier: '' }])}><Plus size={13}/> {t('Add material')}</button></div>
      {materials.map((material, index) => <div className="material-fields" key={index}>
        <input aria-label={t('Material name')} value={material.name} onChange={(event) => setMaterials((current) => current.map((item, i) => i === index ? { ...item, name: event.target.value } : item))} placeholder={t('Material or reagent')} />
        <input aria-label={t('Amount')} value={material.amount} onChange={(event) => setMaterials((current) => current.map((item, i) => i === index ? { ...item, amount: event.target.value } : item))} placeholder={t('Amount')} />
        <input aria-label={t('Unit')} value={material.unit} onChange={(event) => setMaterials((current) => current.map((item, i) => i === index ? { ...item, unit: event.target.value } : item))} placeholder={t('Unit')} />
        <input aria-label={t('Purpose')} value={material.role} onChange={(event) => setMaterials((current) => current.map((item, i) => i === index ? { ...item, role: event.target.value } : item))} placeholder={t('Purpose (optional)')} />
        <input aria-label={t('Lot number')} value={material.lot_number} onChange={(event) => setMaterials((current) => current.map((item, i) => i === index ? { ...item, lot_number: event.target.value } : item))} placeholder={t('Lot / batch (optional)')} />
        <input aria-label={t('Supplier')} value={material.supplier} onChange={(event) => setMaterials((current) => current.map((item, i) => i === index ? { ...item, supplier: event.target.value } : item))} placeholder={t('Supplier (optional)')} />
        <button type="button" className="icon-button" aria-label={t('Remove material')} onClick={() => setMaterials((current) => current.filter((_, i) => i !== index))}><Trash2 size={13}/></button>
      </div>)}
      {!materials.length && <div className="materials-hint">{t('No materials added yet.')}</div>}
    </section>

    <div className="form-section-title"><span>4</span><div><b>{t('Outcome and observations')}</b><small>{t('Record what you measured and what you saw, without guessing the cause.')}</small></div></div>
    <div className="form-simple-list"><div className="variable-heading"><b>{t('Measured results')}</b><button type="button" className="text-button" onClick={() => setResults((current) => [...current, { key: '', value: '', unit: '' }])}><Plus size={13}/> {t('Add result')}</button></div>
      {results.map((result, index) => <div className="variable-fields result-fields" key={index}><input aria-label={t('Result name')} value={result.key} onChange={(event) => setResults((current) => current.map((item, i) => i === index ? { ...item, key: event.target.value } : item))} placeholder={t('Result (e.g. yield, diameter)')}/><input aria-label={t('Result value')} value={result.value} onChange={(event) => setResults((current) => current.map((item, i) => i === index ? { ...item, value: event.target.value } : item))} placeholder={t('Value')}/><input aria-label={t('Result unit')} value={result.unit} onChange={(event) => setResults((current) => current.map((item, i) => i === index ? { ...item, unit: event.target.value } : item))} placeholder={t('Unit')}/><button type="button" className="icon-button" aria-label={t('Remove result')} onClick={() => setResults((current) => current.filter((_, i) => i !== index))}><Trash2 size={13}/></button></div>)}
    </div>
    <div className="form-simple-list"><div className="variable-heading"><b>{t('Observations')}</b><button type="button" className="text-button" onClick={() => setObservations((current) => [...current, { category: 'visual', description: '' }])}><Plus size={13}/> {t('Add observation')}</button></div>
      {observations.map((observation, index) => <div className="observation-fields" key={index}><select aria-label={t('Observation category')} value={observation.category} onChange={(event) => setObservations((current) => current.map((item, i) => i === index ? { ...item, category: event.target.value } : item))}><option value="visual">{t('Visual')}</option><option value="instrument">{t('Instrument')}</option><option value="handling">{t('Handling')}</option><option value="other">{t('Other')}</option></select><input aria-label={t('Observation')} value={observation.description} onChange={(event) => setObservations((current) => current.map((item, i) => i === index ? { ...item, description: event.target.value } : item))} placeholder={t('Describe what happened')}/><button type="button" className="icon-button" aria-label={t('Remove observation')} onClick={() => setObservations((current) => current.filter((_, i) => i !== index))}><Trash2 size={13}/></button></div>)}
    </div>
    <div className="form-actions"><button type="button" className="button outline" onClick={onCancel}>{t('Cancel')}</button><button type="submit" className="button primary" disabled={busy}><Plus size={14}/>{busy ? t('Saving…') : t('Save experiment')}</button></div>
  </form>;
}
