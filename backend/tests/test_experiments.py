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

def test_comparison_keeps_same_named_variables_from_distinct_steps():
    a,b=make('a','failure',2),make('b','success',2)
    for experiment, values in ((a,('60','min')), (b,('1','h'))):
        second=ProcessStep(id=2,experiment_id=experiment.id,name='annealing',step_type='heat',order_index=2,variables=[])
        second.variables=[ProcessVariable(name='temperature',value=values[0],unit=values[1])]
        first=ProcessVariable(name='temperature',value='25',unit='°C')
        experiment.steps[0].variables.append(first)
        experiment.steps.append(second)
    result=compare(a,b)
    assert len(result['same_variables']) == 3  # includes the unchanged seed_cycles value
    assert [item['step_name'] for item in result['same_variables'] if item['name'] == 'temperature'] == ['growth', 'annealing']

def test_comparison_normalizes_equivalent_units_and_marks_incompatible_units_unresolved():
    a,b=make('a','failure',2),make('b','success',2)
    a.steps[0].variables[0].value='1'; a.steps[0].variables[0].unit='h'
    b.steps[0].variables[0].value='60'; b.steps[0].variables[0].unit='min'
    assert len(compare(a,b)['same_variables']) == 1
    b.steps[0].variables[0].unit='g'
    result=compare(a,b)
    assert result['different_variables'] == []
    assert result['unresolved_variables'][0]['reason'] == 'incompatible_or_unknown_units'

def test_comparison_distinguishes_missing_value_from_zero():
    a,b=make('a','failure',0),make('b','success',0)
    a.steps[0].variables[0].value=None
    result=compare(a,b)
    assert result['missing_variables'] == []
    assert result['unresolved_variables'][0]['reason'] == 'value_missing'

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
