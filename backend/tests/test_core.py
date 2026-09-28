import pytest
from pydantic import ValidationError
from app.schemas.core import Claim
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
