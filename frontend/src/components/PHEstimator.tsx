import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { api } from '../api/client';
import { useLanguage } from '../language';
import type { PHEstimateDraft, PHEstimateReagentDraft, PHEstimateResult } from '../types';

const species = ['HCl', 'HNO3', 'H2SO4', 'NaOH', 'KOH', 'CH3COOH', 'H3PO4', 'NH3', 'NaHCO3', 'Na2CO3'];
const blankReagent = (): PHEstimateReagentDraft => ({ id: crypto.randomUUID(), species: 'HCl', mode: 'stock', concentration: '', volume: '', amount: '', mass: '' });

export default function PHEstimator({ value, result, processSteps, onChange, onResult, onUse }: {
  value: PHEstimateDraft;
  result: PHEstimateResult | null;
  processSteps: string[];
  onChange: (value: PHEstimateDraft) => void;
  onResult: (value: PHEstimateResult | null) => void;
  onUse?: (value: PHEstimateResult) => void;
}) {
  const { t } = useLanguage();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const update = (id: string, patch: Partial<PHEstimateReagentDraft>) => {
    onResult(null); setError('');
    onChange({ ...value, reagents: value.reagents.map(item => item.id === id ? { ...item, ...patch } : item) });
  };
  const estimate = async () => {
    setBusy(true); setError('');
    try {
      const reagents = value.reagents.map(item => item.mode === 'amount'
        ? { species: item.species, amount_mmol: Number(item.amount) }
        : item.mode === 'mass' ? { species: item.species, mass_g: Number(item.mass) }
        : { species: item.species, concentration_mol_l: Number(item.concentration), volume_ml: Number(item.volume) });
      const output = await api.estimatePH({ water_volume_ml: Number(value.waterVolume), reagents });
      onResult(output);
    } catch (cause) { setError(t(cause instanceof Error?cause.message:String(cause))); onResult(null); }
    finally { setBusy(false); }
  };
  return <section className="ph-simulator">
    <div className="ph-simulator-head"><div><b>{t('Estimated solution pH')}</b><small>{t('Estimate pH from known acid/base additions when no meter reading is available.')}</small></div><span>{t('CALCULATION')}</span></div>
    <p className="ph-simulator-note">{t('This is a model estimate, not a pH measurement. The current model supports the listed simple acid/base reagents at 25 °C.')}</p>
    <label>{t('Process step')}<select value={value.stepName} onChange={event=>{onResult(null);onChange({...value,stepName:event.target.value})}}>{processSteps.map((step,index)=><option value={step} key={`${index}-${step}`}>{index+1}. {step}</option>)}</select></label>
    <label className="ph-water-volume">{t('Starting water volume')} (mL)<input type="number" min="0.001" step="any" value={value.waterVolume} onChange={event => { onResult(null); onChange({ ...value, waterVolume: event.target.value }); }} placeholder="100" /></label>
    <div className="ph-reagent-list">{value.reagents.map((item,index)=><div className="ph-reagent-row" key={item.id}>
      <label>{t('Acid/base reagent')}<select value={item.species} onChange={event=>update(item.id,{species:event.target.value})}>{species.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
      <label>{t('Dose input')}<select value={item.mode} onChange={event=>update(item.id,{mode:event.target.value as 'stock'|'amount'|'mass'})}><option value="stock">{t('Stock concentration + volume')}</option><option value="amount">{t('Amount in mmol')}</option><option value="mass">{t('Pure reagent mass (g)')}</option></select></label>
      {item.mode==='stock'?<><label>{t('Stock concentration')} (mol/L)<input type="number" min="0" step="any" value={item.concentration} onChange={event=>update(item.id,{concentration:event.target.value})} placeholder="0.1" /></label><label>{t('Added volume')} (mL)<input type="number" min="0" step="any" value={item.volume} onChange={event=>update(item.id,{volume:event.target.value})} placeholder="1" /></label></>:item.mode==='amount'?<label>{t('Amount')} (mmol)<input type="number" min="0" step="any" value={item.amount} onChange={event=>update(item.id,{amount:event.target.value})} placeholder="1" /></label>:<label>{t('Pure reagent mass')} (g)<input type="number" min="0" step="any" value={item.mass} onChange={event=>update(item.id,{mass:event.target.value})} placeholder="0.1" /></label>}
      <button type="button" className="ph-remove" aria-label={t('Remove reagent')} disabled={value.reagents.length===1} onClick={()=>{onResult(null);onChange({...value,reagents:value.reagents.filter(row=>row.id!==item.id)})}}><Trash2 size={14}/></button>
    </div>)}</div>
    <div className="ph-simulator-actions"><button type="button" className="text-button" onClick={()=>{onResult(null);onChange({...value,reagents:[...value.reagents,blankReagent()]})}}><Plus size={13}/>{t('Add reagent')}</button><button type="button" className="button outline small" disabled={busy||!value.stepName||!value.waterVolume||value.reagents.some(item=>item.mode==='stock'?(!item.concentration||!item.volume):item.mode==='amount'?!item.amount:!item.mass)} onClick={()=>void estimate()}><RefreshCw size={13}/>{busy?t('Calculating…'):t('Estimate pH')}</button></div>
    {error&&<div className="error" role="alert">{error}</div>}
    {result&&<div className="ph-estimate-result"><div><small>{t('Estimated pH · 25 °C')}</small><strong>{result.estimated_ph.toFixed(2)}</strong></div><p>{t('Calculated estimate only. Use a calibrated pH meter for the actual value.')}</p>{onUse&&<button type="button" className="button primary small" onClick={()=>onUse(result)}>{t('Add estimate to run record')}</button>}<ul>{result.assumptions.map(item=><li key={item}>{item}</li>)}</ul></div>}
  </section>;
}
