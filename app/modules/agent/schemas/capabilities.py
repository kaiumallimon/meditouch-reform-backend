from enum import Enum
from typing import Dict, List, Set
from app.common.enums import UserRole

class ToolCapability(str, Enum):
    """Explicit capabilities required by agent tools."""
    # Read Capabilities
    READ_CATALOG = "READ_CATALOG"
    READ_PERSONAL_DATA = "READ_PERSONAL_DATA"
    READ_ADMIN_DATA = "READ_ADMIN_DATA"
    READ_CDN_DATA = "READ_CDN_DATA"
    
    # Clinical & Medical Capabilities
    MEDICAL_INFORMATION = "MEDICAL_INFORMATION"
    MEDICAL_TRIAGE = "MEDICAL_TRIAGE"
    
    # Administrative Mutation Capabilities
    CREATE_USER = "CREATE_USER"
    DEACTIVATE_PROFILE = "DEACTIVATE_PROFILE"
    DELETE_PROFILE = "DELETE_PROFILE"
    CREATE_DOCTOR = "CREATE_DOCTOR"
    VERIFY_DOCTOR = "VERIFY_DOCTOR"
    DELETE_DOCTOR = "DELETE_DOCTOR"
    CREATE_MEDICINE = "CREATE_MEDICINE"
    UPDATE_MEDICINE = "UPDATE_MEDICINE"
    DELETE_MEDICINE = "DELETE_MEDICINE"


# Role-Based Capability Matrix
ROLE_CAPABILITY_MATRIX: Dict[str, Set[ToolCapability]] = {
    UserRole.USER.value: {
        ToolCapability.READ_CATALOG,
        ToolCapability.READ_PERSONAL_DATA,
        ToolCapability.MEDICAL_INFORMATION,
        ToolCapability.MEDICAL_TRIAGE,
    },
    UserRole.DOCTOR.value: {
        ToolCapability.READ_CATALOG,
        ToolCapability.READ_PERSONAL_DATA,
        ToolCapability.MEDICAL_INFORMATION,
        ToolCapability.MEDICAL_TRIAGE,
    },
    UserRole.NURSE.value: {
        ToolCapability.READ_CATALOG,
        ToolCapability.READ_PERSONAL_DATA,
        ToolCapability.MEDICAL_INFORMATION,
        ToolCapability.MEDICAL_TRIAGE,
    },
    UserRole.ADMIN.value: {
        ToolCapability.READ_CATALOG,
        ToolCapability.READ_PERSONAL_DATA,
        ToolCapability.READ_ADMIN_DATA,
        ToolCapability.READ_CDN_DATA,
        ToolCapability.MEDICAL_INFORMATION,
        ToolCapability.MEDICAL_TRIAGE,
        ToolCapability.CREATE_USER,
        ToolCapability.DEACTIVATE_PROFILE,
        ToolCapability.DELETE_PROFILE,
        ToolCapability.CREATE_DOCTOR,
        ToolCapability.VERIFY_DOCTOR,
        ToolCapability.DELETE_DOCTOR,
        ToolCapability.CREATE_MEDICINE,
        ToolCapability.UPDATE_MEDICINE,
        ToolCapability.DELETE_MEDICINE,
    },
    UserRole.DEVELOPER.value: {
        # Developer has all admin capabilities
        ToolCapability.READ_CATALOG,
        ToolCapability.READ_PERSONAL_DATA,
        ToolCapability.READ_ADMIN_DATA,
        ToolCapability.READ_CDN_DATA,
        ToolCapability.MEDICAL_INFORMATION,
        ToolCapability.MEDICAL_TRIAGE,
        ToolCapability.CREATE_USER,
        ToolCapability.DEACTIVATE_PROFILE,
        ToolCapability.DELETE_PROFILE,
        ToolCapability.CREATE_DOCTOR,
        ToolCapability.VERIFY_DOCTOR,
        ToolCapability.DELETE_DOCTOR,
        ToolCapability.CREATE_MEDICINE,
        ToolCapability.UPDATE_MEDICINE,
        ToolCapability.DELETE_MEDICINE,
    },
}

def is_role_permitted_for_capability(role: str, capability: ToolCapability) -> bool:
    """Evaluates whether the given role is granted the requested capability."""
    allowed_caps = ROLE_CAPABILITY_MATRIX.get(role, set())
    return capability in allowed_caps
