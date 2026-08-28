import httpx
import time
import uuid
from typing import Optional, Dict, Any
from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import PaymentFailedException
from app.integrations.bkash.models import (
    BkashGrantTokenResponse,
    BkashCreatePaymentRequest,
    BkashCreatePaymentResponse,
    BkashExecutePaymentResponse,
    BkashQueryPaymentResponse,
    BkashRefundRequest,
    BkashRefundResponse
)

class BkashClient:
    def __init__(self):
        self.base_url = settings.BKASH_BASE_URL
        self.app_key = settings.BKASH_APP_KEY
        self.app_secret = settings.BKASH_APP_SECRET
        self.username = settings.BKASH_USERNAME
        self.password = settings.BKASH_PASSWORD
        self.sandbox_mode = settings.BKASH_SANDBOX_MODE
        self._id_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _get_auth_token(self) -> str:
        if self._id_token and time.time() < self._token_expires_at - 60:
            return self._id_token

        if self.sandbox_mode and self.app_key == "sandbox_app_key":
            self._id_token = "mock_bkash_id_token_" + uuid.uuid4().hex[:12]
            self._token_expires_at = time.time() + 3600
            return self._id_token

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "username": self.username,
            "password": self.password
        }
        payload = {
            "app_key": self.app_key,
            "app_secret": self.app_secret
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/tokenized/checkout/token/grant",
                    json=payload,
                    headers=headers
                )
                if resp.status_code != 200:
                    raise PaymentFailedException(f"Failed to obtain bKash token: {resp.text}")
                data = resp.json()
                grant_res = BkashGrantTokenResponse(**data)
                self._id_token = grant_res.id_token
                self._token_expires_at = time.time() + grant_res.expires_in
                return self._id_token
        except Exception as e:
            logger.error(f"bKash Grant Token Error: {e}")
            raise PaymentFailedException(f"bKash Authentication Failed: {str(e)}")

    def _get_headers(self, token: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": token,
            "X-APP-Key": self.app_key
        }

    async def create_payment(
        self,
        payer_reference: str,
        amount: float,
        merchant_invoice_number: str,
        callback_url: Optional[str] = None
    ) -> BkashCreatePaymentResponse:
        str_amount = f"{amount:.2f}"
        callback = callback_url or settings.BKASH_CALLBACK_URL

        if self.sandbox_mode and self.app_key == "sandbox_app_key":
            payment_id = f"BK_{uuid.uuid4().hex[:14].upper()}"
            return BkashCreatePaymentResponse(
                statusCode="0000",
                statusMessage="Successful",
                paymentID=payment_id,
                bkashURL=f"https://sandbox.payment.bkash.com/redirect?paymentID={payment_id}",
                callbackURL=callback,
                amount=str_amount,
                intent="sale",
                currency="BDT",
                paymentCreateTime=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                transactionStatus="Initiated",
                merchantInvoiceNumber=merchant_invoice_number
            )

        token = await self._get_auth_token()
        headers = self._get_headers(token)
        req = BkashCreatePaymentRequest(
            payerReference=payer_reference,
            callbackURL=callback,
            amount=str_amount,
            merchantInvoiceNumber=merchant_invoice_number
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/tokenized/checkout/create",
                    json=req.model_dump(),
                    headers=headers
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("statusCode") != "0000":
                    raise PaymentFailedException(
                        f"bKash Create Payment Failed: {data.get('statusMessage', resp.text)}"
                    )
                return BkashCreatePaymentResponse(**data)
        except PaymentFailedException:
            raise
        except Exception as e:
            logger.error(f"bKash create payment exception: {e}")
            raise PaymentFailedException(f"Payment gateway error: {str(e)}")

    async def execute_payment(self, payment_id: str) -> BkashExecutePaymentResponse:
        if self.sandbox_mode and self.app_key == "sandbox_app_key":
            return BkashExecutePaymentResponse(
                statusCode="0000",
                statusMessage="Successful",
                paymentID=payment_id,
                payerReference="01700000000",
                customerMsisdn="01700000000",
                trxID=f"TRX{uuid.uuid4().hex[:10].upper()}",
                amount="550.00",
                transactionStatus="Completed",
                paymentExecuteTime=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                currency="BDT",
                intent="sale",
                merchantInvoiceNumber="MOCK-INV"
            )

        token = await self._get_auth_token()
        headers = self._get_headers(token)

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/tokenized/checkout/execute",
                    json={"paymentID": payment_id},
                    headers=headers
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("statusCode") != "0000":
                    raise PaymentFailedException(
                        f"bKash Execute Payment Failed: {data.get('statusMessage', resp.text)}"
                    )
                return BkashExecutePaymentResponse(**data)
        except PaymentFailedException:
            raise
        except Exception as e:
            logger.error(f"bKash execute payment exception: {e}")
            raise PaymentFailedException(f"bKash execution error: {str(e)}")

    async def query_payment(self, payment_id: str) -> BkashQueryPaymentResponse:
        if self.sandbox_mode and self.app_key == "sandbox_app_key":
            return BkashQueryPaymentResponse(
                statusCode="0000",
                statusMessage="Successful",
                paymentID=payment_id,
                trxID=f"TRX{uuid.uuid4().hex[:10].upper()}",
                amount="550.00",
                transactionStatus="Completed",
                verificationStatus="Complete",
                currency="BDT",
                merchantInvoiceNumber="MOCK-INV"
            )

        token = await self._get_auth_token()
        headers = self._get_headers(token)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/tokenized/checkout/payment/status",
                    json={"paymentID": payment_id},
                    headers=headers
                )
                data = resp.json()
                if resp.status_code != 200:
                    raise PaymentFailedException(f"bKash Query Failed: {resp.text}")
                return BkashQueryPaymentResponse(**data)
        except PaymentFailedException:
            raise
        except Exception as e:
            logger.error(f"bKash query payment exception: {e}")
            raise PaymentFailedException(f"bKash query error: {str(e)}")

    async def refund_payment(
        self,
        payment_id: str,
        trx_id: str,
        amount: float,
        reason: str = "Appointment / Order cancelled"
    ) -> BkashRefundResponse:
        str_amount = f"{amount:.2f}"

        if self.sandbox_mode and self.app_key == "sandbox_app_key":
            return BkashRefundResponse(
                statusCode="0000",
                statusMessage="Successful",
                originalTrxID=trx_id,
                refundTrxID=f"RF_{uuid.uuid4().hex[:10].upper()}",
                transactionStatus="Completed",
                amount=str_amount,
                currency="BDT"
            )

        token = await self._get_auth_token()
        headers = self._get_headers(token)
        req = BkashRefundRequest(
            paymentID=payment_id,
            amount=str_amount,
            trxID=trx_id,
            reason=reason
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/tokenized/checkout/payment/refund",
                    json=req.model_dump(),
                    headers=headers
                )
                data = resp.json()
                if resp.status_code != 200 or data.get("statusCode") != "0000":
                    raise PaymentFailedException(
                        f"bKash Refund Failed: {data.get('statusMessage', resp.text)}"
                    )
                return BkashRefundResponse(**data)
        except PaymentFailedException:
            raise
        except Exception as e:
            logger.error(f"bKash refund exception: {e}")
            raise PaymentFailedException(f"bKash refund error: {str(e)}")

bkash_client = BkashClient()
