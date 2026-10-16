import pytest
from pydantic import ValidationError
from app.schemas.core import AnalysisExplanation, Claim
from app.services.calculator.service import amount,dilution

def test_claim_contract():
    with pytest.raises(ValidationError): Claim(claim="x",status="SUPPORTED")
    with pytest.raises(ValidationError): Claim(claim="x",status="INFERRED")
    assert Claim(claim="unknown",status="UNKNOWN").evidence_ids==[]

def test_amount_50_mM_60_mL():
    assert amount(50,"mM",60,"mL")["result"]==pytest.approx(.003)

def test_dilution():
    assert dilution(1,.01,c2=.1)["result"]==pytest.approx(.1)

def test_unit_conversion():
    assert amount(.05,"M",60,"mL")["result"]==pytest.approx(.003)

def test_claim_with_evidence_is_accepted():
    assert Claim(claim="directly observed",status="SUPPORTED",evidence_ids=[12]).evidence_ids==[12]

def test_gemma_analysis_explanation_cannot_add_numeric_measurements():
    assert AnalysisExplanation(summary="표면 거칠기 미리보기 결과입니다.",review_notes=["스캔 라인 아티팩트를 확인하세요."])
    with pytest.raises(ValidationError,match="numeric measurements"):
        AnalysisExplanation(summary="평균은 2.4 nm입니다.")
    with pytest.raises(ValidationError,match="numeric measurements"):
        AnalysisExplanation(summary="단일 구성 요소가 감지되었습니다.")
