import pytest
from app.integrations.zegocloud.token_generator import generate_zegocloud_token
from app.integrations.medicine_source.medeasy_parser import normalize_medicine_record, SAMPLE_MEDEASY_DATASET

def test_zegocloud_token_generation():
    token = generate_zegocloud_token(
        user_id="user_12345",
        room_id="room_67890",
        app_id=123456789,
        server_secret="0123456789abcdef0123456789abcdef",
        expiry_seconds=3600
    )
    assert token.startswith("04")
    assert len(token) > 20

def test_medeasy_record_normalization():
    sample = SAMPLE_MEDEASY_DATASET[0]
    norm = normalize_medicine_record(sample)
    assert norm["brand"] == "Napa Extra"
    assert norm["category"] == "TABLET"
    assert norm["unit_price"] == 3.0
    assert norm["in_stock"] is True
