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
    clarification_questions: Optional[List[Dict[str, Any]]] = None
    primary_complaint: Optional[str] = None


# Deterministic emergency regex patterns / red flags
EMERGENCY_PATTERNS: Dict[str, List[str]] = {
    "RESPIRATORY_DISTRESS": [
        r"difficult(y)?\s+(in\s+)?breath(ing)?",
        r"short(ness)?\s+of\s+breath",
        r"trouble\s+breath(ing)?",
        r"can(')?\s*t\s+breathe?",
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

# ─── Symptom classification keyword lists ─────────────────────────────────────
COUGH_KEYWORDS = ["cough", "coughing", "whooping cough"]
FEVER_KEYWORDS = ["fever", "high temperature", "febrile"]
HEADACHE_KEYWORDS = ["headache", "head pain", "migraine", "head ache"]
ALLERGY_KEYWORDS = ["allergy", "allergic", "rash", "itching", "itchy", "hives"]
STOMACH_KEYWORDS = ["stomach ache", "stomach pain", "nausea", "vomit", "diarrhea", "diarrhoea", "indigestion", "stomach upset"]
THROAT_KEYWORDS = ["sore throat", "throat pain", "throat infection", "strep"]

VAGUE_INTENT_PATTERNS = [
    r"what should i take",
    r"what to take",
    r"what medicine",
    r"suggest medicine",
    r"recommend medicine",
    r"give me something for",
    r"cure my",
    r"treat my",
    r"medicine for",
    r"tablet for",
    r"drug for",
    r"syrup for",
]

# ─── Suspicious temperature pattern — catches "100C", "50°C", "42c" etc ──────
SUSPICIOUS_TEMP_CELSIUS = re.compile(
    r"\b([4-9][0-9]|[1-9][0-9]{2,})\s*[°]?\s*c\b",
    re.IGNORECASE,
)


def _build_cough_questions() -> List[Dict[str, Any]]:
    return [
        {
            "id": "duration",
            "type": "single_select",
            "question": "How long have you had this cough?",
            "required": True,
            "options": [
                {"id": "less_than_3_days", "label": "Less than 3 days"},
                {"id": "3_to_7_days", "label": "3–7 days"},
                {"id": "week_plus", "label": "More than a week"},
                {"id": "chronic", "label": "More than a month (chronic)"},
            ],
        },
        {
            "id": "cough_type",
            "type": "single_select",
            "question": "Is the cough dry or productive (with mucus/phlegm)?",
            "required": True,
            "options": [
                {"id": "dry", "label": "Dry (no mucus)"},
                {"id": "productive", "label": "Productive (with mucus)"},
                {"id": "barking", "label": "Barking / harsh sound"},
                {"id": "not_sure", "label": "Not sure"},
            ],
        },
        {
            "id": "severity",
            "type": "single_select",
            "question": "How severe is the cough?",
            "required": True,
            "options": [
                {"id": "mild", "label": "Mild (occasional)"},
                {"id": "moderate", "label": "Moderate (frequent, affects activity)"},
                {"id": "severe", "label": "Severe (constant, very disruptive)"},
            ],
        },
        {
            "id": "associated_symptoms",
            "type": "multi_select",
            "question": "Do you have any of these along with the cough?",
            "required": False,
            "options": [
                {"id": "fever", "label": "Fever"},
                {"id": "runny_nose", "label": "Runny or blocked nose"},
                {"id": "sore_throat", "label": "Sore throat"},
                {"id": "chest_pain", "label": "Chest pain"},
                {"id": "shortness_of_breath", "label": "Shortness of breath"},
                {"id": "none", "label": "None of the above"},
            ],
            "allow_custom_input": False,
        },
        {
            "id": "known_allergies",
            "type": "text",
            "question": "Do you have any known allergies? (medicines, dust, food, etc.) — type 'none' if not applicable",
            "required": False,
            "placeholder": "e.g. penicillin, dust, pollen",
            "allow_custom_input": True,
        },
    ]


def _build_fever_questions() -> List[Dict[str, Any]]:
    return [
        {
            "id": "temperature",
            "type": "text",
            "question": "What is your temperature? (Please specify the unit — e.g. '38.5°C' or '101°F')",
            "required": False,
            "placeholder": "e.g. 38.5°C or 101°F",
            "allow_custom_input": True,
        },
        {
            "id": "duration",
            "type": "single_select",
            "question": "How long have you had the fever?",
            "required": True,
            "options": [
                {"id": "today", "label": "Started today"},
                {"id": "1_to_3_days", "label": "1–3 days"},
                {"id": "more_than_3_days", "label": "More than 3 days"},
            ],
        },
        {
            "id": "associated_symptoms",
            "type": "multi_select",
            "question": "Any other symptoms along with the fever?",
            "required": False,
            "options": [
                {"id": "chills", "label": "Chills / shivering"},
                {"id": "body_ache", "label": "Body aches"},
                {"id": "headache", "label": "Headache"},
                {"id": "cough", "label": "Cough"},
                {"id": "rash", "label": "Skin rash"},
                {"id": "none", "label": "None of the above"},
            ],
        },
        {
            "id": "medication_taken",
            "type": "single_select",
            "question": "Have you taken any medicine for the fever?",
            "required": False,
            "options": [
                {"id": "none", "label": "No"},
                {"id": "paracetamol", "label": "Yes — Paracetamol / Napa"},
                {"id": "ibuprofen", "label": "Yes — Ibuprofen / Nurofen"},
                {"id": "other", "label": "Yes — other medicine"},
            ],
        },
    ]


def _build_headache_questions() -> List[Dict[str, Any]]:
    return [
        {
            "id": "severity",
            "type": "single_select",
            "question": "How severe is the headache?",
            "required": True,
            "options": [
                {"id": "mild", "label": "Mild (bearable)"},
                {"id": "moderate", "label": "Moderate (distracting)"},
                {"id": "severe", "label": "Severe (debilitating)"},
            ],
        },
        {
            "id": "duration",
            "type": "single_select",
            "question": "How long have you had the headache?",
            "required": True,
            "options": [
                {"id": "less_than_hour", "label": "Less than an hour"},
                {"id": "few_hours", "label": "A few hours"},
                {"id": "today", "label": "All day"},
                {"id": "multi_day", "label": "More than a day"},
            ],
        },
        {
            "id": "location",
            "type": "single_select",
            "question": "Where is the headache located?",
            "required": False,
            "options": [
                {"id": "forehead", "label": "Forehead / front"},
                {"id": "temples", "label": "Temples (sides)"},
                {"id": "back_of_head", "label": "Back of head"},
                {"id": "behind_eyes", "label": "Behind the eyes"},
                {"id": "whole_head", "label": "Entire head"},
                {"id": "one_side", "label": "One side only"},
            ],
        },
        {
            "id": "migraine_history",
            "type": "boolean",
            "question": "Have you been previously diagnosed with migraines?",
            "required": False,
        },
    ]


def _build_allergy_questions() -> List[Dict[str, Any]]:
    return [
        {
            "id": "symptoms",
            "type": "multi_select",
            "question": "What symptoms are you experiencing?",
            "required": True,
            "options": [
                {"id": "sneezing", "label": "Sneezing or runny nose"},
                {"id": "itchy_eyes", "label": "Itchy or watery eyes"},
                {"id": "hives", "label": "Hives or skin itching"},
                {"id": "swelling", "label": "Swelling (face / lips / throat)"},
                {"id": "breathing_difficulty", "label": "Difficulty breathing"},
                {"id": "other", "label": "Other symptoms"},
            ],
            "allow_custom_input": True,
        },
        {
            "id": "duration",
            "type": "single_select",
            "question": "How long have you had these symptoms?",
            "required": True,
            "options": [
                {"id": "today", "label": "Started today"},
                {"id": "few_days", "label": "A few days (2–5 days)"},
                {"id": "week_plus", "label": "More than a week"},
            ],
        },
        {
            "id": "medication_taken",
            "type": "single_select",
            "question": "Have you already taken anything for it?",
            "required": False,
            "options": [
                {"id": "none", "label": "No"},
                {"id": "antihistamine", "label": "Yes (Antihistamine / Allergy pill)"},
                {"id": "other_med", "label": "Yes (Other medicine)"},
            ],
        },
    ]


def _build_general_questions() -> List[Dict[str, Any]]:
    return [
        {
            "id": "symptoms_detail",
            "type": "text",
            "question": "Please describe your specific symptoms (location, severity, when they started):",
            "required": True,
            "placeholder": "e.g. Headache on forehead, mild fever since yesterday",
            "allow_custom_input": True,
        },
        {
            "id": "duration",
            "type": "single_select",
            "question": "How long have you been experiencing this?",
            "required": True,
            "options": [
                {"id": "today", "label": "Started today"},
                {"id": "few_days", "label": "A few days"},
                {"id": "week_plus", "label": "More than a week"},
            ],
        },
    ]


def _classify_primary_symptom(text: str) -> Optional[str]:
    """
    Identifies the primary symptom from user text using keyword matching.
    Returns the most specific match or None.
    """
    for kw in COUGH_KEYWORDS:
        if kw in text:
            return "cough"
    for kw in FEVER_KEYWORDS:
        if kw in text:
            return "fever"
    for kw in HEADACHE_KEYWORDS:
        if kw in text:
            return "headache"
    for kw in ALLERGY_KEYWORDS:
        if kw in text:
            return "allergy"
    for kw in THROAT_KEYWORDS:
        if kw in text:
            return "sore throat"
    for kw in STOMACH_KEYWORDS:
        if kw in text:
            return "stomach ache"
    return None


def _suspicious_temperature_detected(text: str) -> bool:
    """Returns True if the text contains a temperature that looks like dangerous Celsius units."""
    return bool(SUSPICIOUS_TEMP_CELSIUS.search(text))


class MedicalSafetyPolicy:
    """
    Deterministic clinical safety guard for MediTouch.
    Enforces strict boundaries between factual health information, triage safety,
    and prohibited autonomous prescribing.
    """

    @staticmethod
    def assess_symptoms(
        user_text: str,
        clinical_context: Optional[Dict[str, Any]] = None,
    ) -> TriageAssessment:
        """
        Assesses user-reported symptoms for emergency flags, clarification need, or factual info.

        Args:
            user_text: The user's current message or original request.
            clinical_context: Optional existing ClinicalContext dict from a prior turn.
                              If provided, it informs which questions have already been answered.
        """
        normalized = user_text.lower().strip()
        matched_emergencies: List[str] = []

        # 1. Suspicious temperature unit check (e.g. "100C")
        if _suspicious_temperature_detected(normalized):
            return TriageAssessment(
                status=TriageStatus.INSUFFICIENT_INFORMATION,
                is_emergency=False,
                emergency_indicators_found=[],
                guidance=(
                    "⚠️ I noticed a temperature value that may have an unusual unit. "
                    "Please clarify your temperature and unit."
                ),
                recommended_action="CLARIFY_TEMPERATURE_UNIT",
                can_recommend_medication=False,
                primary_complaint="temperature",
                clarification_questions=[
                    {
                        "id": "temperature_clarification",
                        "type": "text",
                        "question": (
                            "You mentioned a temperature — did you mean it in Fahrenheit (°F) or Celsius (°C)? "
                            "Please re-enter (e.g. '101°F' or '38.5°C'):"
                        ),
                        "required": True,
                        "placeholder": "e.g. 101°F or 38.5°C",
                        "allow_custom_input": True,
                    }
                ],
            )

        # 2. Screen for Emergency Red Flags
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
                clarification_questions=None,
            )

        # 3. Screen for Urgent Medical Review Flags
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
                clarification_questions=None,
            )

        # 4. Factual medicine lookup — no clarification needed
        is_factual_lookup = any(w in normalized for w in [
            "what is", "details of", "price of", "cost of", "how much is",
            "find napa", "find paracetamol", "cetirizine", "amoxicillin",
            "mg tablet", "mg capsule", "syrup",
        ])
        # Pure medicine name queries → pass through without clarification
        is_medicine_specific = bool(re.search(r"\b(napa|paracetamol|cetirizine|omeprazole|metformin|amoxicillin|azithromycin|fexofenadine|montelukast|ibuprofen|naproxen)\b", normalized))

        if is_factual_lookup or is_medicine_specific:
            return TriageAssessment(
                status=TriageStatus.GENERAL_INFORMATION,
                is_emergency=False,
                emergency_indicators_found=[],
                guidance="Provide safe, factual medical and health information from verified sources.",
                recommended_action="PROVIDE_FACTUAL_INFO",
                can_recommend_medication=False,
                clarification_questions=None,
            )

        # 5. Symptom + treatment intent → identify primary complaint, route to specific questions
        has_vague_intent = any(re.search(p, normalized) for p in VAGUE_INTENT_PATTERNS)
        primary = _classify_primary_symptom(normalized)

        # Additional direct symptom keywords without explicit intent
        has_symptom_keyword = primary is not None

        if has_vague_intent or has_symptom_keyword:
            # Select symptom-specific question set
            if primary == "cough":
                questions = _build_cough_questions()
            elif primary == "fever":
                questions = _build_fever_questions()
            elif primary == "headache":
                questions = _build_headache_questions()
            elif primary == "allergy":
                questions = _build_allergy_questions()
            else:
                questions = _build_general_questions()

            # If we have existing clinical_context, skip already-answered questions
            if clinical_context:
                answered = set()
                pc = clinical_context.get("primary_complaint") or {}
                if pc.get("duration"):
                    answered.add("duration")
                if pc.get("symptom_type"):
                    answered.add("cough_type")
                if pc.get("severity"):
                    answered.add("severity")
                if clinical_context.get("associated_symptoms"):
                    answered.add("associated_symptoms")
                rh = clinical_context.get("relevant_history") or {}
                if rh.get("allergies"):
                    answered.add("known_allergies")

                if answered:
                    questions = [q for q in questions if q["id"] not in answered]

            # If all questions already answered, allow continuation
            if not questions:
                return TriageAssessment(
                    status=TriageStatus.GENERAL_INFORMATION,
                    is_emergency=False,
                    emergency_indicators_found=[],
                    guidance="Sufficient information collected. Continue evaluation.",
                    recommended_action="CONTINUE_EVALUATION",
                    can_recommend_medication=False,
                    clarification_questions=None,
                    primary_complaint=primary,
                )

            complaint_label = primary or "your symptoms"
            return TriageAssessment(
                status=TriageStatus.INSUFFICIENT_INFORMATION,
                is_emergency=False,
                emergency_indicators_found=[],
                guidance=f"I need a little more information before I can safely evaluate your {complaint_label}.",
                recommended_action="ASK_CLARIFYING_SYMPTOMS",
                can_recommend_medication=False,
                clarification_questions=questions,
                primary_complaint=primary,
            )

        return TriageAssessment(
            status=TriageStatus.GENERAL_INFORMATION,
            is_emergency=False,
            emergency_indicators_found=[],
            guidance="Provide safe, factual medical and health information from verified sources.",
            recommended_action="PROVIDE_FACTUAL_INFO",
            can_recommend_medication=False,
            clarification_questions=None,
        )
