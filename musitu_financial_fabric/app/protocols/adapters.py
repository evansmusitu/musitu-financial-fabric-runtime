from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedIntent:
    amount_minor: int
    currency: str
    payer_ref: str | None
    description: str | None
    protocol: str


def stripe_payment_intent(payload: dict) -> NormalizedIntent:
    return NormalizedIntent(int(payload["amount"]), str(payload["currency"]).upper(), payload.get("payment_method"), payload.get("description"), "stripe")


def open_payments_incoming(payload: dict) -> NormalizedIntent:
    value = payload.get("incomingAmount") or payload.get("amount") or {}
    return NormalizedIntent(int(value["value"]), str(value["assetCode"]).upper(), payload.get("walletAddress"), payload.get("metadata", {}).get("description"), "open-payments")


def gsma_transaction(payload: dict) -> NormalizedIntent:
    amount = payload.get("amount") or payload.get("debitParty") or {}
    amount_value = payload.get("amount", {}).get("amount") if isinstance(payload.get("amount"), dict) else payload.get("amount")
    currency = payload.get("amount", {}).get("currency") if isinstance(payload.get("amount"), dict) else payload.get("currency")
    return NormalizedIntent(int(round(float(amount_value) * 100)), str(currency).upper(), payload.get("debitParty", [{}])[0].get("partyId") if isinstance(payload.get("debitParty"), list) and payload.get("debitParty") else None, payload.get("description"), "gsma-mmapi")


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
    currency = amount_node.attrib.get("Ccy", "USD")
    return NormalizedIntent(int(round(float(amount_node.text) * 100)), currency.upper(), None, "ISO 20022 pacs.008", "iso20022")


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
