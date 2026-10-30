from datetime import date
from types import SimpleNamespace
from app.db.models import Experiment,ProcessStep,ProcessVariable
from app.services.experiment.compare import compare
from app.services.failure_analysis.service import analyze

def make(code,status,cycles):
    e=Experiment(id=1 if code=='a' else 2,code=code,name=code,target='ZnO',status=status,demo=True,topic_id=1,method_version_id=1,steps=[])
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

def test_numeric_comparison_uses_only_reported_uncertainty_and_never_assumes_resolution():
    a,b=make('a','failure',2),make('b','success',2)
    left,right=a.steps[0].variables[0],b.steps[0].variables[0]
    left.value='50'; right.value='50.00000001'
    without=compare(a,b)['different_variables'][0]['comparison']
    assert without['tolerance_basis']=='floating_point_conversion_only_no_measurement_precision_assumed'
    left.measurement_uncertainty=0.1
    right.measurement_uncertainty=0.1
    with_uncertainty=compare(a,b)['same_variables'][0]['comparison']
    assert with_uncertainty['tolerance_basis']=='combined_reported_standard_uncertainty'
    assert with_uncertainty['comparison_tolerance']>without['comparison_tolerance']

def test_temperature_uncertainty_uses_delta_conversion():
    a,b=make('a','failure',2),make('b','success',2)
    left,right=a.steps[0].variables[0],b.steps[0].variables[0]
    left.name=right.name='temperature'; left.value='25'; left.unit='°C'; left.measurement_uncertainty=0.5
    right.value='77'; right.unit='°F'; right.measurement_uncertainty=0.9
    comparison=compare(a,b)['same_variables'][0]['comparison']
    assert comparison['tolerance_basis']=='combined_reported_standard_uncertainty'
    assert 0.7 < comparison['comparison_tolerance'] < 0.8

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

def test_same_version_comparison_blocks_unknown_version_ids():
    a,b=make('a','failure',2),make('b','success',3)
    a.method_version_id=b.method_version_id=None
    result=compare(a,b)
    assert result['comparison_context']['comparison_status']=='blocked_version_mismatch_or_unknown'
    assert result['comparison_context']['same_method_version'] is False

def test_cross_version_comparison_requires_same_method_and_explicit_mode():
    a,b=make('a','failure',2),make('b','success',3)
    a.method_version_id=1; b.method_version_id=2
    a.method_version=SimpleNamespace(method_id=10,version_label='1')
    b.method_version=SimpleNamespace(method_id=10,version_label='2')
    assert compare(a,b)['comparison_context']['comparison_status']=='blocked_version_mismatch_or_unknown'
    result=compare(a,b,comparison_mode='cross_version')
    assert result['comparison_context']['comparison_status']=='comparable'
    assert result['comparison_context']['comparison_mode']=='cross_version'

def test_failure_analysis_keeps_step_and_duplicate_variable_candidates_distinct():
    failed,success=make('a','failure',2),make('b','success',3)
    for record, values in ((failed,('50','60')), (success,('75','80'))):
        step=record.steps[0]
        step.variables=[ProcessVariable(name='temperature',value=value,unit='°C',material='solution') for value in values]
        second=ProcessStep(id=2,experiment_id=record.id,name='annealing',step_type='heat',order_index=2,variables=[])
        second.variables=[ProcessVariable(name='temperature',value='100' if record is failed else '110',unit='°C',material='substrate')]
        record.steps.append(second)
    result=analyze(failed,[failed,success])
    assert len(result['candidate_variables'])==3
    assert len({item['variable_id'] for item in result['candidate_variables']})==3

def test_failure_analysis_separates_demo_and_lab_records_and_does_not_rank_unresolved():
    failed,success=make('a','failure',2),make('b','success',3)
    success.demo=False
    result=analyze(failed,[failed,success])
    assert result['closest_successful_experiments']==[]
    assert result['excluded_successful_experiments'][0]['reason']=='demo_and_lab_records_must_not_be_mixed'
    success.demo=True
    success.steps[0].variables[0].unit='g'
    result=analyze(failed,[failed,success])
    assert result['candidate_variables']==[]
    assert result['unresolved_variables'][0]['reason']=='incompatible_or_unknown_units'
