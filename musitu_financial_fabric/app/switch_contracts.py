from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class SwitchContractError(RuntimeError):
    pass


def _required(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise SwitchContractError(f"{label} is required")
    return normalized


@dataclass(frozen=True)
class SwitchTransferInstruction:
    idempotency_key: str
    payer_participant_id: str
    payee_participant_id: str
    payer_alias: str
    payee_alias: str
    amount_minor: int
    currency: str
    reference: str
    request_to_pay_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "idempotency_key", _required(self.idempotency_key, "idempotency key"))
        object.__setattr__(self, "payer_participant_id", _required(self.payer_participant_id, "payer participant"))
        object.__setattr__(self, "payee_participant_id", _required(self.payee_participant_id, "payee participant"))
        object.__setattr__(self, "payer_alias", _required(self.payer_alias, "payer alias").lower())
        object.__setattr__(self, "payee_alias", _required(self.payee_alias, "payee alias").lower())
        object.__setattr__(self, "reference", _required(self.reference, "reference"))
        amount = int(self.amount_minor)
        if amount <= 0:
            raise SwitchContractError("transfer amount must be positive")
        object.__setattr__(self, "amount_minor", amount)
        currency = str(self.currency or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise SwitchContractError("currency must be an explicit three-letter code")
        object.__setattr__(self, "currency", currency)
        if self.request_to_pay_id is not None:
            object.__setattr__(self, "request_to_pay_id", _required(self.request_to_pay_id, "request-to-pay id"))

    def to_dict(self) -> dict:
        return {
            "idempotency_key": self.idempotency_key,
            "payer_participant_id": self.payer_participant_id,
            "payee_participant_id": self.payee_participant_id,
            "payer_alias": self.payer_alias,
            "payee_alias": self.payee_alias,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "reference": self.reference,
            "request_to_pay_id": self.request_to_pay_id,
        }


@dataclass(frozen=True)
class SwitchTransferResult:
    external_reference: str
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_reference", _required(self.external_reference, "external reference"))
        status = str(self.status or "").strip().lower()
        if status not in {"pending", "accepted", "succeeded", "failed", "unknown"}:
            raise SwitchContractError("unsupported switch transfer status")
        object.__setattr__(self, "status", status)


class SovereignSwitchAdapter(ABC):
    @abstractmethod
    async def submit_transfer(self, instruction: SwitchTransferInstruction) -> SwitchTransferResult:
        raise NotImplementedError


class UnconfiguredSovereignSwitchAdapter(SovereignSwitchAdapter):
    async def submit_transfer(self, instruction: SwitchTransferInstruction) -> SwitchTransferResult:
        if not isinstance(instruction, SwitchTransferInstruction):
            raise SwitchContractError("valid switch transfer instruction is required")
        raise SwitchContractError("sovereign switch adapter is not configured")


def instruction_from_accepted_request(
    request: dict,
    *,
    payer_participant_id: str,
    payee_participant_id: str,
    idempotency_key: str,
) -> SwitchTransferInstruction:
    if str(request.get("status") or "").strip().lower() != "accepted":
        raise SwitchContractError("request-to-pay must be accepted before switch transformation")
    instruction = request.get("payment_instruction")
    if not isinstance(instruction, dict):
        instruction = request
    return SwitchTransferInstruction(
        idempotency_key=idempotency_key,
        payer_participant_id=payer_participant_id,
        payee_participant_id=payee_participant_id,
        payer_alias=str(instruction.get("payer_alias") or request.get("payer_alias") or ""),
        payee_alias=str(instruction.get("payee_alias") or request.get("payee_alias") or ""),
        amount_minor=int(instruction.get("amount_minor") or request.get("amount_minor") or 0),
        currency=str(instruction.get("currency") or request.get("currency") or ""),
        reference=str(instruction.get("reference") or request.get("reference") or ""),
        request_to_pay_id=str(instruction.get("request_to_pay_id") or request.get("id") or ""),
    )
