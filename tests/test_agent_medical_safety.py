import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.agent.security.medical_safety import MedicalSafetyPolicy, TriageStatus
from app.modules.agent.tools.user.clinical import AssessSymptomSafetyTool
from app.modules.agent.tools.user.medicines import SearchMedicinesTool, GetMedicineDetailsTool
from app.modules.agent.schemas.tools import ToolExecutionStatus

def test_allergy_query_does_not_recommend_medicines():
    """
    Guarantees that general symptom queries (e.g. 'mild allergy', 'what should I take')
    do NOT recommend medications or return drug lists.
    """
    res = MedicalSafetyPolicy.assess_symptoms("I have a mild allergy, what should I take?")
    assert res.status == TriageStatus.INSUFFICIENT_INFORMATION
    assert res.is_emergency is False
    assert res.can_recommend_medication is False
    assert "licensed doctor" in res.guidance.lower() or "clinical assessment" in res.guidance.lower()

def test_emergency_respiratory_and_anaphylaxis_detection():
    """
    Guarantees that respiratory distress or anaphylaxis triggers immediate emergency screening.
    """
    # 1. Breathing distress
    res1 = MedicalSafetyPolicy.assess_symptoms("I am having difficulty breathing and chest tightness")
    assert res1.status == TriageStatus.EMERGENCY
    assert res1.is_emergency is True
    assert res1.can_recommend_medication is False
    assert res1.recommended_action == "CALL_EMERGENCY_SERVICES"
    assert "999" in res1.guidance or "emergency" in res1.guidance.lower()

    # 2. Airway swelling
    res2 = MedicalSafetyPolicy.assess_symptoms("My throat is swelling and my lips are swollen")
    assert res2.status == TriageStatus.EMERGENCY
    assert res2.is_emergency is True
    assert any("throat" in ind or "lip" in ind for ind in res2.emergency_indicators_found)

def test_emergency_cardiac_and_neurological_detection():
    """
    Guarantees cardiac and neurological red flags trigger emergency classification.
    """
    # 1. Chest pain
    res1 = MedicalSafetyPolicy.assess_symptoms("I have severe chest pain and pain radiating to left arm")
    assert res1.status == TriageStatus.EMERGENCY
    assert res1.is_emergency is True

    # 2. Syncope / Loss of consciousness
    res2 = MedicalSafetyPolicy.assess_symptoms("My father just fainted and is unresponsive")
    assert res2.status == TriageStatus.EMERGENCY
    assert res2.is_emergency is True

@pytest.mark.asyncio
async def test_assess_symptom_safety_tool_execution():
    tool = AssessSymptomSafetyTool()
    tool_res = await tool.execute(
        arguments={"symptoms_description": "I have chest pain and shortness of breath"},
        caller_id="usr_test_1",
        caller_role="USER",
        session_id="ses_test_1",
    )
    assert tool_res.status == ToolExecutionStatus.SUCCESS
    assert tool_res.result["is_emergency"] is True
    assert tool_res.result["status"] == "EMERGENCY"

@pytest.mark.asyncio
async def test_factual_medicine_search_allowed():
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[
        {
            "id": "med_1",
            "slug": "napa-500mg",
            "brand": "Napa",
            "generic_name": "Paracetamol",
            "strength": "500mg",
            "dosage_form": "Tablet",
            "unit_price": 1.20,
            "pack_size": "10x10",
            "in_stock": True,
            "stock_count": 100,
            "requires_prescription": False,
            "category": "TABLET",
            "manufacturer": "Beximco Pharmaceuticals Ltd.",
        }
    ])
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.skip = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_db.medicines.find = MagicMock(return_value=mock_cursor)
    mock_db.medicines.count_documents = AsyncMock(return_value=1)

    tool = SearchMedicinesTool(mock_db)
    tool_res = await tool.execute(
        arguments={"query": "Napa"},
        caller_id="usr_test_1",
        caller_role="USER",
        session_id="ses_test_1",
    )
    assert tool_res.status == ToolExecutionStatus.SUCCESS
    assert tool_res.result["count"] == 1
    assert tool_res.result["medicines"][0]["brand"] == "Napa"
    assert tool_res.result["medicines"][0]["generic_name"] == "Paracetamol"
