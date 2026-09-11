from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class NormalizedIntent:
    amount_minor: int
    currency: str
    payer_ref: str | None
    description: str | None
    protocol: str


def _currency(value: object) -> str:
    code = str(value or "").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("currency must be an explicit three-letter code")
    return code


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is not a valid monetary amount")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} is not a valid monetary amount") from exc
    if not amount.is_finite():
        raise ValueError(f"{field} must be finite")
    return amount


def _minor_integer(value: object, *, field: str) -> int:
    amount = _decimal(value, field=field)
    if amount != amount.to_integral_value():
        raise ValueError(f"{field} must be an integer minor-unit amount")
    return int(amount)


def _major_to_minor(value: object, *, field: str) -> int:
    amount = _decimal(value, field=field)
    minor = amount * Decimal(100)
    if minor != minor.to_integral_value():
        raise ValueError(f"{field} has precision smaller than the supported 2-decimal minor unit")
    return int(minor)


def _scaled_integer_to_minor(value: object, scale: object, *, field: str) -> int:
    amount = _minor_integer(value, field=field)
    asset_scale = _minor_integer(scale, field="assetScale")
    if not 0 <= asset_scale <= 18:
        raise ValueError("assetScale must be between 0 and 18")
    minor = Decimal(amount).scaleb(-asset_scale) * Decimal(100)
    if minor != minor.to_integral_value():
        raise ValueError(f"{field} cannot be represented exactly in the supported 2-decimal minor unit")
    return int(minor)


def stripe_payment_intent(payload: dict) -> NormalizedIntent:
    return NormalizedIntent(
        _minor_integer(payload["amount"], field="amount"),
        _currency(payload["currency"]),
        payload.get("payment_method"),
        payload.get("description"),
        "stripe",
    )


def open_payments_incoming(payload: dict) -> NormalizedIntent:
    value = payload.get("incomingAmount") or payload.get("amount") or {}
    if not isinstance(value, dict):
        raise ValueError("Open Payments amount must be an object")
    if "assetScale" not in value:
        raise ValueError("Open Payments amount requires assetScale")
    return NormalizedIntent(
        _scaled_integer_to_minor(value["value"], value["assetScale"], field="value"),
        _currency(value["assetCode"]),
        payload.get("walletAddress"),
        payload.get("metadata", {}).get("description"),
        "open-payments",
    )


def gsma_transaction(payload: dict) -> NormalizedIntent:
    amount_value = payload.get("amount", {}).get("amount") if isinstance(payload.get("amount"), dict) else payload.get("amount")
    currency = payload.get("amount", {}).get("currency") if isinstance(payload.get("amount"), dict) else payload.get("currency")
    payer_ref = (
        payload.get("debitParty", [{}])[0].get("partyId")
        if isinstance(payload.get("debitParty"), list) and payload.get("debitParty")
        else None
    )
    return NormalizedIntent(
        _major_to_minor(amount_value, field="amount"),
        _currency(currency),
        payer_ref,
        payload.get("description"),
        "gsma-mmapi",
    )


def iso20022_pacs008(xml_body: str) -> NormalizedIntent:
    root = ET.fromstring(xml_body)
    amount_node = None
    for node in root.iter():
        local = node.tag.split("}")[-1]
        if local in {"IntrBkSttlmAmt", "InstdAmt"}:
            amount_node = node
            break
    if amount_node is None or not amount_node.text:
        raise ValueError("ISO20022 amount not found")
    if "Ccy" not in amount_node.attrib:
        raise ValueError("ISO20022 amount currency not found")
    return NormalizedIntent(
        _major_to_minor(amount_node.text, field="ISO20022 amount"),
        _currency(amount_node.attrib["Ccy"]),
        None,
        "ISO 20022 pacs.008",
        "iso20022",
    )


def mpp_challenge(amount_minor: int, currency: str, resource: str) -> dict:
    return {
        "protocol": "mpp",
        "status": 402,
        "payment": {"amount_minor": amount_minor, "currency": currency.upper(), "method": "musitu", "resource": resource},
    }


def x402_challenge(amount_minor: int, currency: str, resource: str) -> dict:
    payload = {"scheme": "musitu", "amount_minor": amount_minor, "currency": currency.upper(), "resource": resource}
    token = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return {"protocol": "x402", "status": 402, "payment_required": token, "requirements": payload}
