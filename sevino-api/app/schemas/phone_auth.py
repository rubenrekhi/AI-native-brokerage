from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

PhoneStr = Annotated[
    str,
    StringConstraints(pattern=r"^\+1\d{10}$"),
]
"""E.164 US phone number: +1 followed by 10 digits (total 12 chars)."""

OtpStr = Annotated[
    str,
    StringConstraints(pattern=r"^\d{6}$"),
]
"""6-digit SMS verification code."""


class SendVerificationRequest(BaseModel):
    phone_number: PhoneStr = Field(
        ..., description="E.164-formatted US phone number, e.g. +15551234567"
    )


class SendVerificationResponse(BaseModel):
    sent: bool = True


class ConfirmVerificationRequest(BaseModel):
    phone_number: PhoneStr
    code: OtpStr = Field(..., description="6-digit code received via SMS")


class ConfirmVerificationResponse(BaseModel):
    verified: bool = True
    phone_verified_at: datetime
