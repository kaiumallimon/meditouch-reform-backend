import re
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class TriageStatus(str, Enum):
    EMERGENCY = "EMERGENCY"
    URGENT_MEDICAL_REVIEW = "URGENT_MEDICAL_REVIEW"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    GENERAL_INFORMATION = "GENERAL_INFORMATION"


class TriageAssessment(BaseModel):
    status: TriageStatus
    is_emergency: bool
    emergency_indicators_found: List[str] = Field(default_factory=list)
    guidance: str
    recommended_action: str
    can_recommend_medication: bool = False


# Deterministic emergency regex patterns / red flags
EMERGENCY_PATTERNS: Dict[str, List[str]] = {
    "RESPIRATORY_DISTRESS": [
        r"difficult(y)?\s+(in\s+)?breath(ing)?",
        r"short(ness)?\s+of\s+breath",
        r"trouble\s+breath(ing)?",
        r"can(')?t\s+breathe?",
        r"cannot\s+breathe?",
        r"struggling\s+to\s+breathe?",
        r"stridor",
        r"wheezing\s+severely",
        r"choking",
        r"gasping\s+for\s+air",
        r"blue\s+lips",
        r"cyanosis",
    ],
    "ANAPHYLAXIS_AIRWAY": [
        r"throat\s+(is\s+)?swell(ing|ed|en)?",
        r"swollen\s+throat",
        r"tongue\s+(is\s+)?swell(ing|ed|en)?",
        r"swollen\s+tongue",
        r"lip(s)?\s+(are\s+|is\s+)?swell(ing|ed|en)?",
        r"swollen\s+lip(s)?",
        r"throat\s+closing",
        r"anaphylaxis",
        r"allergic\s+reaction\s+(spreading|severe)",
    ],
    "CARDIOVASCULAR": [
        r"chest\s+pain",
        r"chest\s+pressure",
        r"crushing\s+chest",
        r"pain\s+radiating\s+to\s+(left\s+)?(arm|jaw|back)",
        r"heart\s+attack",
        r"severe\s+palpitations\s+with\s+dizziness",
    ],
    "NEUROLOGICAL_STROKE": [
        r"faint(ing|ed)?",
        r"loss\s+of\s+consciousness",
        r"pass(ed)?\s+out",
        r"unresponsive",
        r"facial\s+droop",
        r"face\s+droop(ing)?",
        r"slurred\s+speech",
        r"sudden\s+numbness",
        r"worst\s+headache\s+of\s+my\s+life",
        r"thunderclap\s+headache",
        r"seizure(s)?",
        r"convulsion(s)?",
    ],
    "SEVERE_BLEEDING": [
        r"severe\s+bleeding",
        r"uncontrollable\s+bleeding",
        r"coughing\s+up?\s+blood",
        r"vomiting\s+blood",
        r"heavy\s+blood\s+loss",
    ],
}

URGENT_REVIEW_PATTERNS: List[str] = [
    r"high\s+fever\s+(over\s+)?(103|39)",
    r"stiff\s+neck\s+with\s+fever",
    r"severe\s+abdominal\s+pain",
    r"acute\s+belly\s+pain",
    r"blood\s+in\s+stool",
    r"black\s+tarry\s+stool",
    r"persistent\s+vomiting",
    r"dehydration\s+in\s+infant",
]


class MedicalSafetyPolicy:
    """
    Deterministic clinical safety guard for MediTouch.
    Enforces strict boundaries between factual health information, triage safety,
    and prohibited autonomous prescribing.
    """

    @staticmethod
    def assess_symptoms(user_text: str) -> TriageAssessment:
        normalized = user_text.lower().strip()
        matched_emergencies: List[str] = []

        # 1. Screen for Emergency Red Flags
        for category, patterns in EMERGENCY_PATTERNS.items():
            for pat in patterns:
                m = re.search(pat, normalized)
                if m:
                    matched_emergencies.append(m.group(0))
                    break

        if matched_emergencies:
            return TriageAssessment(
                status=TriageStatus.EMERGENCY,
                is_emergency=True,
                emergency_indicators_found=matched_emergencies,
                guidance=(
                    "🚨 **CRITICAL MEDICAL EMERGENCY DETECTED** 🚨\n\n"
                    "Your symptoms indicate a potentially life-threatening emergency. "
                    "**DO NOT wait or attempt self-medication.**\n\n"
                    "- **Call emergency medical services immediately** (e.g., 999 / 911 or local emergency number).\n"
                    "- Go to the nearest Hospital Emergency Room right away.\n"
                    "- If you are alone, alert someone nearby immediately."
                ),
                recommended_action="CALL_EMERGENCY_SERVICES",
                can_recommend_medication=False,
            )

        # 2. Screen for Urgent Medical Review Flags
        matched_urgent: List[str] = []
        for pat in URGENT_REVIEW_PATTERNS:
            if re.search(pat, normalized):
                matched_urgent.append(pat)

        if matched_urgent:
            return TriageAssessment(
                status=TriageStatus.URGENT_MEDICAL_REVIEW,
                is_emergency=False,
                emergency_indicators_found=matched_urgent,
                guidance=(
                    "⚠️ **Urgent Medical Review Needed**\n\n"
                    "Your symptoms require prompt clinical evaluation by a licensed healthcare professional. "
                    "Please book an urgent telemedicine consultation or visit an urgent care clinic."
                ),
                recommended_action="CONSULT_DOCTOR_URGENTLY",
                can_recommend_medication=False,
            )

        # 3. Check for general / vague symptom queries
        is_vague_symptom_query = any(
            w in normalized
            for w in [
                "what should i take",
                "what to take",
                "what medicine",
                "suggest medicine",
                "recommend medicine",
                "give me something for",
                "cure my",
                "treat my",
                "mild allergy",
                "having allergy",
                "have fever",
                "have headache",
            ]
        )

        if is_vague_symptom_query:
            return TriageAssessment(
                status=TriageStatus.INSUFFICIENT_INFORMATION,
                is_emergency=False,
                emergency_indicators_found=[],
                guidance=(
                    "A broad symptom description alone is not enough to safely evaluate your condition or determine appropriate treatment. "
                    "Please describe your specific symptoms in more detail (e.g., duration, severity, location), "
                    "or consult a licensed doctor for proper clinical assessment."
                ),
                recommended_action="ASK_CLARIFYING_SYMPTOMS",
                can_recommend_medication=False,
            )

        return TriageAssessment(
            status=TriageStatus.GENERAL_INFORMATION,
            is_emergency=False,
            emergency_indicators_found=[],
            guidance="Provide safe, factual medical and health information from verified sources.",
            recommended_action="PROVIDE_FACTUAL_INFO",
            can_recommend_medication=False,
        )
