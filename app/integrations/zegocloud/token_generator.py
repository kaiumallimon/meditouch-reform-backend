import base64
import json
import os
import struct
import time
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from app.core.config import settings

def _aes_encrypt(plain_text: str, key: str, iv: bytes) -> bytes:
    key_bytes = key.encode('utf-8')
    if len(key_bytes) > 32:
        key_bytes = key_bytes[:32]
    elif len(key_bytes) < 16:
        key_bytes = key_bytes.ljust(16, b'0')
    elif 16 < len(key_bytes) < 24:
        key_bytes = key_bytes.ljust(24, b'0')
    elif 24 < len(key_bytes) < 32:
        key_bytes = key_bytes.ljust(32, b'0')

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(plain_text.encode('utf-8')) + padder.finalize()

    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(padded_data) + encryptor.finalize()

def generate_zegocloud_token(
    user_id: str,
    room_id: str,
    app_id: Optional[int] = None,
    server_secret: Optional[str] = None,
    expiry_seconds: Optional[int] = None,
    privilege_login_room: bool = True,
    privilege_publish_stream: bool = True
) -> str:
    app_id = app_id or settings.ZEGOCLOUD_APP_ID
    server_secret = server_secret or settings.ZEGOCLOUD_SERVER_SECRET
    expiry_seconds = expiry_seconds or settings.ZEGOCLOUD_TOKEN_EXPIRY_SECONDS

    now = int(time.time())
    expire_time = now + expiry_seconds
    nonce = int.from_bytes(os.urandom(4), byteorder='big')

    privilege: Dict[int, int] = {}
    if privilege_login_room:
        privilege[1] = 1
    if privilege_publish_stream:
        privilege[2] = 1

    payload_data = {
        "app_id": app_id,
        "user_id": str(user_id),
        "room_id": str(room_id),
        "nonce": nonce,
        "ctime": now,
        "expire": expire_time,
        "privilege": privilege,
        "stream_id_list": []
    }
    payload_json = json.dumps(payload_data)

    iv = os.urandom(16)
    encrypted = _aes_encrypt(payload_json, server_secret, iv)

    packed = struct.pack("!q", expire_time)
    packed += struct.pack("!H", len(iv))
    packed += iv
    packed += struct.pack("!H", len(encrypted))
    packed += encrypted

    token_b64 = base64.b64encode(packed).decode('utf-8')
    return f"04{token_b64}"
