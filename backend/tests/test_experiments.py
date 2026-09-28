from datetime import date
from app.db.models import Experiment,ProcessStep,ProcessVariable
from app.services.experiment.compare import compare
from app.services.failure_analysis.service import analyze

def make(code,status,cycles):
    e=Experiment(id=1 if code=='a' else 2,code=code,name=code,target='ZnO',status=status,demo=True,steps=[])
    s=ProcessStep(id=1,experiment_id=e.id,name='growth',order_index=1,variables=[]);e.steps=[s]
    s.variables=[ProcessVariable(name='seed_cycles',value=str(cycles),unit='cycles')]
    return e

def test_comparison():
    result=compare(make('a','failure',2),make('b','success',3))
    assert result['different_variables'][0]['name']=='seed_cycles'

def test_failure_analysis_never_claims_cause():
    a,b=make('a','failure',2),make('b','success',3)
    result=analyze(a,[a,b])
    assert result['candidate_variables'][0]['variable']=='seed_cycles'
    assert 'causation is UNKNOWN' in result['statement']
    assert result['candidate_variables'][0]['evidence_status']=='UNKNOWN'

def test_unexplained_recorded_variables_are_unknown():
    a,b=make('a','failure',2),make('b','success',3)
    result=analyze(a,[a,b])
    assert result['candidate_variables'][0]['evidence_status']=='UNKNOWN'
    assert result['candidate_variables'][0]['evidence_ids']==[]
    assert 'UNKNOWN' in result['statement']
