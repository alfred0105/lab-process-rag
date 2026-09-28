from app.db.models import Experiment

def variable_map(exp: Experiment):
    out={}
    for step in exp.steps:
        for v in step.variables:
            out[v.name]=(v.value,v.unit,v.material)
    return out

def compare(a: Experiment,b: Experiment):
    av,bv=variable_map(a),variable_map(b); same=[]; different=[]; missing=[]
    for name in sorted(av.keys()|bv.keys()):
        if name not in av or name not in bv:
            missing.append({"name":name,"experiment_a":av.get(name),"experiment_b":bv.get(name)})
        elif av[name]==bv[name]: same.append({"name":name,"value":av[name][0],"unit":av[name][1]})
        else: different.append({"name":name,"experiment_a":av[name][0],"unit_a":av[name][1],"experiment_b":bv[name][0],"unit_b":bv[name][1]})
    return {"same_variables":same,"different_variables":different,"missing_variables":missing}
