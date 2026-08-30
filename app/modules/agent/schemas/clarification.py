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

