from app.db.models import Experiment
from app.services.experiment.compare import compare, variable_map

def analyze(target: Experiment, pool: list[Experiment]):
    successes=[e for e in pool if e.status=="success" and e.id!=target.id]
    ranked=[]
    for e in successes:
        c=compare(target,e); shared=len(c["same_variables"]); diffs=len(c["different_variables"])+len(c["missing_variables"])
        ranked.append((shared-diffs,e,c))
    ranked.sort(key=lambda x:(-x[0],x[1].code))
    closest=[]; candidates=[]
    for _,exp,c in ranked[:3]:
        closest.append({"experiment_id":exp.id,"code":exp.code,"comparison":c})
        for d in c["different_variables"]:
            candidates.append({"variable":d["name"],"failure_value":d["experiment_a"],"success_value":d["experiment_b"],"evidence_status":"UNKNOWN","evidence_ids":[],"label":"Possible variable to investigate","success_experiment":exp.code})
    # No causal language; lab comparison is an observation, not causal evidence.
    unique={x["variable"]:x for x in candidates}
    return {"experiment_id":target.id,"failure_observations":[{"category":o.category,"description":o.description,"severity":o.severity} for o in target.observations],"closest_successful_experiments":closest,"candidate_variables":list(unique.values()),"missing_recorded_information":sorted({x["name"] for _,_,c in ranked[:3] for x in c["missing_variables"]}),"statement":"Recorded-variable differences are candidates for investigation; causation is UNKNOWN." if closest else "UNKNOWN: no recorded successful comparison is available."}
