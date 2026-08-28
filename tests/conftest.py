import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from mongomock_motor import AsyncMongoMockClient
from datetime import datetime, timezone
import uuid

from app.main import app
from app.db.mongodb import get_db, db_manager
from app.core.security import hash_password, create_access_token
from app.common.enums import UserRole, DoctorVerificationStatus
from app.integrations.medicine_source.medeasy_parser import ingest_medicine_catalog

@pytest_asyncio.fixture
async def mock_db():
    client = AsyncMongoMockClient()
    db = client["test_meditouch"]
    db_manager.db = db
    
    # Ingest baseline catalog for tests
    await ingest_medicine_catalog(db)
    
    yield db
    client.close()

@pytest_asyncio.fixture
async def client(mock_db):
    app.dependency_overrides[get_db] = lambda: mock_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

@pytest_asyncio.fixture
async def admin_auth(mock_db):
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "name": "Super Admin",
        "phone": "+8801900000001",
        "email": "admin@meditouch.com",
        "hashed_password": hash_password("AdminPass123!"),
        "role": UserRole.ADMIN.value,
        "is_active": True,
        "created_at": datetime.now(timezone.utc)
    }
    await mock_db.users.insert_one(user_doc)
    token = create_access_token({"sub": user_id, "role": UserRole.ADMIN.value, "phone": user_doc["phone"], "name": user_doc["name"]})
    return {"user": user_doc, "token": token, "headers": {"Authorization": f"Bearer {token}"}}

@pytest_asyncio.fixture
async def doctor_auth(mock_db):
    user_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "name": "Dr. Rafiqul Islam",
        "phone": "+8801700000002",
        "email": "dr.rafiq@meditouch.com",
        "hashed_password": hash_password("DoctorPass123!"),
        "role": UserRole.DOCTOR.value,
        "is_active": True,
        "created_at": datetime.now(timezone.utc)
    }
    await mock_db.users.insert_one(user_doc)

    doctor_profile = {
        "id": doc_id,
        "user_id": user_id,
        "name": "Dr. Rafiqul Islam",
        "phone": "+8801700000002",
        "email": "dr.rafiq@meditouch.com",
        "bmdc_reg_number": "A-12345",
        "specialties": ["General Medicine", "Cardiology"],
        "qualifications": ["MBBS", "FCPS (Medicine)"],
        "experience_years": 10,
        "consultation_fee": 500.0,
        "bio": "Experienced general physician.",
        "is_verified": True,
        "verification_status": DoctorVerificationStatus.VERIFIED.value,
        "is_active": True,
        "rating": 5.0,
        "total_reviews": 12,
        "total_consultations": 45,
        "created_at": datetime.now(timezone.utc)
    }
    await mock_db.doctors.insert_one(doctor_profile)

    token = create_access_token({"sub": user_id, "role": UserRole.DOCTOR.value, "phone": user_doc["phone"], "name": user_doc["name"]})
    return {"user": user_doc, "doctor": doctor_profile, "token": token, "headers": {"Authorization": f"Bearer {token}"}}

@pytest_asyncio.fixture
async def patient_auth(mock_db):
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "name": "Kamal Hossain",
        "phone": "+8801800000003",
        "email": "kamal@meditouch.test",
        "hashed_password": hash_password("PatientPass123!"),
        "role": UserRole.USER.value,
        "is_active": True,
        "addresses": [
            {
                "id": str(uuid.uuid4()),
                "label": "Home",
                "recipient_name": "Kamal Hossain",
                "recipient_phone": "+8801800000003",
                "division": "Dhaka",
                "district": "Dhaka",
                "upazila_or_thana": "Mirpur",
                "street_address": "House 12, Road 4, Section 10",
                "is_default": True
            }
        ],
        "created_at": datetime.now(timezone.utc)
    }
    await mock_db.users.insert_one(user_doc)
    token = create_access_token({"sub": user_id, "role": UserRole.USER.value, "phone": user_doc["phone"], "name": user_doc["name"]})
    return {"user": user_doc, "token": token, "headers": {"Authorization": f"Bearer {token}"}}
