"""Grouped leave-one-condition-out baseline check for literature run data.

This is an evaluation harness, not the app recommender. It compares fixed
standardized ridge regression with a training-mean baseline, keeping all
replicates at identical process settings in the same holdout fold.
"""
import csv,json,math,collections
from pathlib import Path
import numpy as np
p=Path(__file__).resolve().parents[1] / 'docs' / 'research-data' / 'cross-domain-process-outcomes.csv'
with p.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
for r in rows:
 r['f']=json.loads(r.pop('factors_json')); r['o']=json.loads(r.pop('outcomes_json'))

def num(v):
 if isinstance(v,bool):return None
 if isinstance(v,(int,float)) and math.isfinite(v):return float(v)
 if isinstance(v,dict) and isinstance(v.get('mean'),(int,float)):return float(v['mean'])
 return None

def features(train,test):
 keys=sorted({k for r in train+test for k in r['f']})
 nkeys=[k for k in keys if all(isinstance(r['f'].get(k),(int,float)) and not isinstance(r['f'].get(k),bool) for r in train+test)]
 ckeys=[k for k in keys if k not in nkeys]
 means={k:float(np.mean([r['f'][k] for r in train])) for k in nkeys}
 stds={k:float(np.std([r['f'][k] for r in train])) or 1. for k in nkeys}
 vocab={k:sorted({str(r['f'].get(k)) for r in train})[1:] for k in ckeys}
 def vector(r):
  v=[1.]
  v += [(float(r['f'][k])-means[k])/stds[k] for k in nkeys]
  for k in ckeys: v += [1. if str(r['f'].get(k))==val else 0. for val in vocab[k]]
  return v
 return np.array([vector(r) for r in train]),np.array([vector(r) for r in test])

out=[]
for ds in sorted({r['dataset_id'] for r in rows}):
 subset=[r for r in rows if r['dataset_id']==ds]
 groups=collections.defaultdict(list)
 for r in subset:groups[json.dumps(r['f'],sort_keys=True,separators=(',',':'))].append(r)
 outcome_names=sorted({k for r in subset for k in r['o']})
 for oname in outcome_names:
  valid=[r for r in subset if num(r['o'].get(oname)) is not None]
  vals=[]; baselines=[];preds=[];actual=[]
  # Validate only groups represented in outcomes, holding all same-factor repetitions together.
  vg=collections.defaultdict(list)
  for r in valid: vg[json.dumps(r['f'],sort_keys=True,separators=(',',':'))].append(r)
  gkeys=list(vg)
  for gk in gkeys:
   test=vg[gk]
   train=[r for k,rs in vg.items() if k!=gk for r in rs]
   if len(train)<2:continue
   Xtr,Xte=features(train,test)
   ytr=np.array([num(r['o'][oname]) for r in train]); yte=np.array([num(r['o'][oname]) for r in test])
   # Fixed standardized ridge baseline, lambda=1, intercept unpenalized.
   penalty=np.eye(Xtr.shape[1]); penalty[0,0]=0
   try: coef=np.linalg.solve(Xtr.T@Xtr+penalty,Xtr.T@ytr)
   except np.linalg.LinAlgError: coef=np.linalg.lstsq(Xtr.T@Xtr+penalty,Xtr.T@ytr,rcond=None)[0]
   yhat=Xte@coef; ybase=np.full(len(test),float(np.mean(ytr)))
   preds.extend(yhat.tolist()); baselines.extend(ybase.tolist()); actual.extend(yte.tolist())
  if not actual: continue
  mae=float(np.mean(np.abs(np.array(actual)-preds))); bmae=float(np.mean(np.abs(np.array(actual)-baselines)))
  rmse=float(np.sqrt(np.mean((np.array(actual)-preds)**2)))
  improvement=(bmae-mae)/bmae*100 if bmae else None
  out.append({'dataset_id':ds,'outcome':oname,'runs':len(valid),'unique_conditions':len(vg),'model_test_n':len(actual),'ridge_mae':mae,'mean_baseline_mae':bmae,'ridge_rmse':rmse,'mae_improvement_pct':improvement,'quality':'pilot' if len(vg)>=8 else 'too_few_unique_conditions'})
print(json.dumps({'metric':'MAE vs training-mean baseline','rows':len(rows),'datasets':len({r['dataset_id'] for r in rows}),'results':out},ensure_ascii=False,indent=2))
