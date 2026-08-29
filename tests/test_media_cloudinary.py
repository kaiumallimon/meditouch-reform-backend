import pytest
import io

@pytest.mark.asyncio
async def test_upload_image_to_cloudinary(client, patient_auth):
    headers = patient_auth["headers"]
    
    # 1. Valid 1x1 RGB red PNG
    valid_png_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82'
    files = {"file": ("avatar.png", io.BytesIO(valid_png_content), "image/png")}
    data = {"folder": "meditouch/profiles"}

    res = await client.post("/api/v1/media/upload", files=files, data=data, headers=headers)
    assert res.status_code == 201
    res_data = res.json()["data"]
    assert "public_id" in res_data
    assert "secure_url" in res_data
    assert res_data["resource_type"] == "image"
    assert res_data["folder"] == "meditouch/profiles"
    assert "cloudinary.com" in res_data["secure_url"]

@pytest.mark.asyncio
async def test_upload_prescription_pdf_to_cloudinary(client, patient_auth):
    headers = patient_auth["headers"]

    # 2. Upload prescription PDF
    pdf_content = b"%PDF-1.4 sample prescription document content"
    files = {"file": ("my_prescription.pdf", io.BytesIO(pdf_content), "application/pdf")}

    res = await client.post("/api/v1/media/prescription", files=files, headers=headers)
    assert res.status_code == 201
    res_data = res.json()["data"]
    assert res_data["resource_type"] == "raw"
    assert res_data["folder"] == "meditouch/prescriptions"
    assert res_data["format"] == "pdf"

@pytest.mark.asyncio
async def test_upload_doctor_verification_document(client, admin_auth):
    headers = admin_auth["headers"]

    # 3. Upload doctor verification document
    doc_content = b"%PDF-1.4 official BMDC registration certificate"
    files = {"file": ("bmdc_cert.pdf", io.BytesIO(doc_content), "application/pdf")}

    res = await client.post("/api/v1/media/doctor-document", files=files, headers=headers)
    assert res.status_code == 201
    res_data = res.json()["data"]
    assert res_data["folder"] == "meditouch/doctors/documents"

@pytest.mark.asyncio
async def test_upload_invalid_extension_rejected(client, patient_auth):
    headers = patient_auth["headers"]

    # 4. Upload disallowed executable file
    exe_content = b"MZ\x90\x00\x03\x00\x00\x00"
    files = {"file": ("malicious.exe", io.BytesIO(exe_content), "application/octet-stream")}

    res = await client.post("/api/v1/media/upload", files=files, headers=headers)
    assert res.status_code == 400
    assert "not supported" in res.json()["message"]

@pytest.mark.asyncio
async def test_cdn_assets_management_read_write_delete(client, admin_auth):
    headers = admin_auth["headers"]

    # 1. Upload an asset
    valid_png_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82'
    files = {"file": ("banner.png", io.BytesIO(valid_png_content), "image/png")}
    data = {"folder": "meditouch/general"}

    upload_res = await client.post("/api/v1/media/upload", files=files, data=data, headers=headers)
    assert upload_res.status_code == 201
    asset_id = upload_res.json()["data"]["id"]

    # 2. Get CDN stats
    stats_res = await client.get("/api/v1/media/stats", headers=headers)
    assert stats_res.status_code == 200
    stats_data = stats_res.json()["data"]
    assert stats_data["total_assets"] >= 1
    assert "storage_used_formatted" in stats_data

    # 3. List assets with pagination and folder filtering
    list_res = await client.get("/api/v1/media/assets?folder=meditouch/general", headers=headers)
    assert list_res.status_code == 200
    assets = list_res.json()["data"]["items"]
    assert any(a["id"] == asset_id for a in assets)

    # 4. Delete asset
    del_res = await client.delete(f"/api/v1/media/assets/{asset_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["data"]["id"] == asset_id

