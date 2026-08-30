from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field

MAX_QUESTIONS_PER_CLARIFICATION = 5
MAX_OPTION_COUNT = 8
MAX_CLARIFICATION_ROUNDS = 5
DEFAULT_CLARIFICATION_TTL_SECONDS = 600  # 10 minutes

class QuestionType(str, Enum):
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    TEXT = "text"
    FREE_TEXT = "free_text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    ENTITY_SELECT = "entity_select"

class ClarificationOption(BaseModel):
    id: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=200)
    subtitle: Optional[str] = Field(None, max_length=300)
    metadata: Optional[Dict[str, Any]] = None

class ClarificationQuestion(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    type: QuestionType = QuestionType.SINGLE_SELECT
    question: str = Field(..., min_length=1, max_length=500)
    required: bool = True
    options: Optional[List[ClarificationOption]] = None
    allow_custom_input: bool = False
    placeholder: Optional[str] = Field(None, max_length=200)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    max_length: Optional[int] = Field(500, le=1000)

class ClarificationSubmission(BaseModel):
    action: str = "submit_clarification"
    session_id: str
    clarification_id: str

class ClarificationRequiredPayload(BaseModel):
    clarification_id: str
    message: str
    questions: List[ClarificationQuestion]
    submission: ClarificationSubmission

class ClarificationAnswer(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=50)
    value: Union[str, List[str], int, float, bool]

class ClarificationSubmissionRequest(BaseModel):
    answers: List[ClarificationAnswer]


# ─── Clinical Context ────────────────────────────────────────────────────────
# Structured clinical state persisted in MongoDB alongside the clarification.
# Enables multi-turn context accumulation without relying on LLM memory alone.

class PrimaryComplaintContext(BaseModel):
    """Structured representation of the user's primary complaint."""
    symptom: str
    duration: Optional[str] = None
    symptom_type: Optional[str] = None   # e.g. "dry" for cough
    severity: Optional[str] = None       # "mild" | "moderate" | "severe"
    onset: Optional[str] = None

class AssociatedSymptom(BaseModel):
    symptom: str
    value: Optional[Union[str, bool]] = None
    severity: Optional[str] = None
    known_history: Optional[str] = None  # e.g. "migraine" for headache

class RelevantHistory(BaseModel):
    allergies: List[str] = Field(default_factory=list)
    chronic_conditions: List[str] = Field(default_factory=list)
    current_medications: List[str] = Field(default_factory=list)

class ClinicalContext(BaseModel):
    """
    Full structured clinical state for an ongoing symptom task.
    Merged cumulatively from each clarification round.
    The primary_complaint is NEVER replaced by a secondary symptom answer
    unless the user explicitly switches subject.
    """
    primary_complaint: Optional[PrimaryComplaintContext] = None
    secondary_complaints: List[AssociatedSymptom] = Field(default_factory=list)
    associated_symptoms: List[AssociatedSymptom] = Field(default_factory=list)
    relevant_history: RelevantHistory = Field(default_factory=RelevantHistory)
    red_flags: List[str] = Field(default_factory=list)
    clarification_status: str = "pending"  # pending | completed

    def to_context_string(self) -> str:
        """Renders clinical context as a human-readable injection for the LLM."""
        parts: List[str] = []
        if self.primary_complaint:
            pc = self.primary_complaint
            desc = f"Primary complaint: **{pc.symptom}**"
            details = []
            if pc.duration:
                details.append(f"duration: {pc.duration}")
            if pc.symptom_type:
                details.append(f"type: {pc.symptom_type}")
            if pc.severity:
                details.append(f"severity: {pc.severity}")
            if details:
                desc += f" ({', '.join(details)})"
            parts.append(desc)
        if self.associated_symptoms:
            sym_list = ", ".join(s.symptom for s in self.associated_symptoms)
            parts.append(f"Associated symptoms: {sym_list}")
        if self.secondary_complaints:
            sec = ", ".join(s.symptom for s in self.secondary_complaints)
            parts.append(f"Secondary complaints: {sec}")
        rh = self.relevant_history
        if rh.allergies:
            parts.append(f"Known allergies: {', '.join(rh.allergies)}")
        if rh.current_medications:
            parts.append(f"Current medications: {', '.join(rh.current_medications)}")
        return "\n".join(parts) if parts else "No structured clinical context yet."

    def merge_answers(self, question_answers: List[Dict[str, Any]]) -> None:
        """
        Merges a list of {question_id, question, value} dicts into this context.
        This is ALWAYS additive. Primary complaint is never replaced.
        """
        for ans in question_answers:
            qid = ans.get("question_id", "")
            val = ans.get("value")

            if val is None:
                continue

            if isinstance(val, list):
                val_str = val
            else:
                val_str = str(val)

            # Duration always maps to primary complaint duration
            if qid == "duration":
                if self.primary_complaint:
                    self.primary_complaint.duration = val_str if isinstance(val_str, str) else val_str[0]

            elif qid == "cough_type":
                if self.primary_complaint:
                    self.primary_complaint.symptom_type = val_str if isinstance(val_str, str) else val_str[0]

            elif qid == "severity":
                if self.primary_complaint:
                    self.primary_complaint.severity = val_str if isinstance(val_str, str) else val_str[0]

            elif qid in ("associated_symptoms", "symptoms", "symptoms_detail"):
                # Add to associated symptoms list — never replace primary complaint
                items = val_str if isinstance(val_str, list) else [val_str]
                for item in items:
                    normalized = item.strip().lower()
                    # Skip if it's the same as primary complaint
                    pc_symptom = (self.primary_complaint.symptom.lower() if self.primary_complaint else "")
                    if normalized and normalized != pc_symptom:
                        if not any(s.symptom.lower() == normalized for s in self.associated_symptoms):
                            self.associated_symptoms.append(AssociatedSymptom(symptom=item.strip()))

            elif qid in ("fever", "has_fever"):
                has_fever = val if isinstance(val, bool) else str(val).lower() in ("true", "yes", "fever", "1")
                if has_fever:
                    if not any(s.symptom.lower() == "fever" for s in self.associated_symptoms):
                        self.associated_symptoms.append(AssociatedSymptom(symptom="fever", value=True))

            elif qid in ("allergy", "allergies", "known_allergy", "known_allergies"):
                items = val_str if isinstance(val_str, list) else [val_str]
                for item in items:
                    normalized = item.strip()
                    if normalized and normalized.lower() not in ("none", "no", "none known"):
                        if normalized not in self.relevant_history.allergies:
                            self.relevant_history.allergies.append(normalized)

            elif qid in ("medication_taken", "current_medications", "medications"):
                items = val_str if isinstance(val_str, list) else [val_str]
                for item in items:
                    normalized = item.strip()
                    if normalized and normalized.lower() not in ("none", "no"):
                        if normalized not in self.relevant_history.current_medications:
                            self.relevant_history.current_medications.append(normalized)

            # Unknown question IDs are stored as associated symptoms as a fallback
            # to avoid silently dropping context data
