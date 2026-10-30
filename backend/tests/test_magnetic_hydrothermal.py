import pytest
from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_magnetic_stir_bar_characterization_uses_actual_rpm_and_labels_limits():
    response=client.post('/api/simulations/magnetic-stir-bar',json={
        'bar_length_mm':25,'bar_diameter_mm':8,'rpm':500,'liquid_density_kg_m3':1000,
        'dynamic_viscosity_pa_s':0.001,'liquid_volume_ml':50,'beaker_inner_diameter_mm':40,
        'bottom_clearance_mm':1})
    assert response.status_code==200
    result=response.json()
    assert result['status']=='DIMENSIONLESS_ESTIMATE'
    assert result['results']['bar_tip_speed_m_s']==pytest.approx(0.6545,rel=1e-3)
    assert any('mixing time' in item for item in result['limitations'])

def test_hydrothermal_water_reference_matches_known_water_saturation_pressure():
    response=client.post('/api/simulations/hydrothermal/water-state',json={'temperature_c':100,'hold_time_h':2,'fill_fraction':0.7})
    assert response.status_code==200
    assert response.json()['results']['pure_water_saturation_pressure_mpa_abs']==pytest.approx(0.1014,rel=0.003)

def test_hydrothermal_pressure_bounds():
    response=client.post('/api/simulations/hydrothermal/water-state',json={'temperature_c':400,'hold_time_h':2})
    assert response.status_code==400

def test_hydrothermal_water_state_carries_coated_substrate_context_without_claiming_coupling():
    substrate={'substrate_material':'glass','coating_material':'oxide seed','nominal_dry_thickness_um':0.4}
    response=client.post('/api/simulations/hydrothermal/water-state',json={
        'temperature_c':90,'hold_time_h':4,'substrate_context':substrate})
    assert response.status_code==200
    assert response.json()['inputs']['substrate_context']==substrate
    assert any('does not alter' in item for item in response.json()['limitations'])

def test_zno_model_is_explicitly_literature_reference_and_bounded():
    response=client.post('/api/simulations/hydrothermal/literature-growth-reference',json={'time_h':8})
    assert response.status_code==200
    result=response.json()
    assert result['status']=='PUBLISHED_REFERENCE_ONLY'
    assert result['results']['reported_array_layer_length_um_reference']==pytest.approx(2.4)
    assert 'not a prediction' in result['limitations'][0]

def test_zno_reference_refuses_extrapolation():
    response=client.post('/api/simulations/hydrothermal/literature-growth-reference',json={'time_h':9})
    assert response.status_code==400

def test_spin_coating_thickness_model_returns_curve_and_distinguishes_wet_dry():
    response=client.post('/api/simulations/coating/spin',json={
        'substrate_length_mm':25,'substrate_width_mm':25,'dispensed_volume_ml':0.1,
        'density_kg_m3':1000,'dynamic_viscosity_pa_s':0.01,'rpm':1000,
        'spin_time_s':30,'nonvolatile_volume_fraction':0.05,'coating_cycles':2,
        'substrate_material':'glass','coating_material':'test sol'})
    assert response.status_code==200
    result=response.json()
    assert result['status']=='FIRST_ORDER_PROCESS_ESTIMATE'
    assert result['results']['end_of_spin_wet_thickness_um'] < result['results']['initial_uniform_wet_thickness_um']
    assert result['results']['cycles_nominal_dry_thickness_um']==pytest.approx(2*result['results']['single_cycle_nominal_dry_thickness_um'])
    assert len(result['results']['thickness_time_curve'])==21
    assert any('evaporation' in item.lower() for item in result['limitations'])

def test_spin_coating_refuses_unknown_material_physics_as_missing_values():
    response=client.post('/api/simulations/coating/spin',json={
        'substrate_length_mm':25,'substrate_width_mm':25,'dispensed_volume_ml':0.1,
        'density_kg_m3':1000,'dynamic_viscosity_pa_s':0.01,'rpm':1000,
        'spin_time_s':30,'nonvolatile_volume_fraction':0,'coating_cycles':1})
    assert response.status_code==400
