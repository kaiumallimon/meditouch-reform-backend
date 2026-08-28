from pydantic import BaseModel, Field
from typing import Optional

class BkashGrantTokenResponse(BaseModel):
    statusCode: str
    statusMessage: str
    id_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None

class BkashCreatePaymentRequest(BaseModel):
    mode: str = "0011"
    payerReference: str
    callbackURL: str
    amount: str
    currency: str = "BDT"
    intent: str = "sale"
    merchantInvoiceNumber: str

class BkashCreatePaymentResponse(BaseModel):
    statusCode: str
    statusMessage: str
    paymentID: str
    bkashURL: str
    callbackURL: str
    successCallbackURL: Optional[str] = None
    failureCallbackURL: Optional[str] = None
    cancelledCallbackURL: Optional[str] = None
    amount: str
    intent: str
    currency: str
    paymentCreateTime: str
    transactionStatus: str
    merchantInvoiceNumber: str

class BkashExecutePaymentResponse(BaseModel):
    statusCode: str
    statusMessage: str
    paymentID: str
    payerReference: Optional[str] = None
    customerMsisdn: Optional[str] = None
    trxID: Optional[str] = None
    amount: str
    transactionStatus: str
    paymentExecuteTime: Optional[str] = None
    currency: str
    intent: str
    merchantInvoiceNumber: str

class BkashQueryPaymentResponse(BaseModel):
    statusCode: str
    statusMessage: str
    paymentID: str
    trxID: Optional[str] = None
    amount: str
    transactionStatus: str
    verificationStatus: Optional[str] = None
    currency: str
    merchantInvoiceNumber: str

class BkashRefundRequest(BaseModel):
    paymentID: str
    amount: str
    trxID: str
    sku: str = "REFUND"
    reason: str = "Customer requested cancellation"

class BkashRefundResponse(BaseModel):
    statusCode: str
    statusMessage: str
    originalTrxID: str
    refundTrxID: Optional[str] = None
    transactionStatus: str
    amount: str
    currency: str
