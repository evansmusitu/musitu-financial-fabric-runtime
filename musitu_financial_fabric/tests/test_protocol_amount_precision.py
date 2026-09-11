from __future__ import annotations

import pytest

from app.protocols.adapters import (
    gsma_transaction,
    iso20022_pacs008,
    open_payments_incoming,
    stripe_payment_intent,
)


def test_stripe_requires_integer_minor_units():
    with pytest.raises(ValueError, match="integer minor-unit"):
        stripe_payment_intent({"amount": 10.5, "currency": "usd"})

    intent = stripe_payment_intent({"amount": "1050", "currency": "usd"})
    assert intent.amount_minor == 1050
    assert intent.currency == "USD"


def test_gsma_decimal_amount_is_converted_exactly_without_float_rounding():
    intent = gsma_transaction({
        "amount": {"amount": "10.01", "currency": "USD"},
        "debitParty": [{"partyId": "payer-1"}],
    })
    assert intent.amount_minor == 1001
    assert intent.currency == "USD"


def test_gsma_subcent_amount_is_rejected_instead_of_rounded():
    with pytest.raises(ValueError, match="precision smaller"):
        gsma_transaction({"amount": {"amount": "10.001", "currency": "USD"}})


def test_iso20022_requires_explicit_currency_and_exact_cent_precision():
    xml = '<Document><IntrBkSttlmAmt Ccy="USD">12.34</IntrBkSttlmAmt></Document>'
    intent = iso20022_pacs008(xml)
    assert intent.amount_minor == 1234
    assert intent.currency == "USD"

    with pytest.raises(ValueError, match="currency not found"):
        iso20022_pacs008('<Document><IntrBkSttlmAmt>12.34</IntrBkSttlmAmt></Document>')

    with pytest.raises(ValueError, match="precision smaller"):
        iso20022_pacs008('<Document><IntrBkSttlmAmt Ccy="USD">12.345</IntrBkSttlmAmt></Document>')


def test_open_payments_asset_scale_is_normalized_exactly_to_two_decimal_minor_units():
    scale_two = open_payments_incoming({
        "incomingAmount": {"value": "1234", "assetCode": "USD", "assetScale": 2}
    })
    assert scale_two.amount_minor == 1234

    scale_three_exact = open_payments_incoming({
        "incomingAmount": {"value": "12340", "assetCode": "USD", "assetScale": 3}
    })
    assert scale_three_exact.amount_minor == 1234

    with pytest.raises(ValueError, match="cannot be represented exactly"):
        open_payments_incoming({
            "incomingAmount": {"value": "12345", "assetCode": "USD", "assetScale": 3}
        })


def test_open_payments_requires_explicit_asset_scale():
    with pytest.raises(ValueError, match="requires assetScale"):
        open_payments_incoming({"incomingAmount": {"value": "1234", "assetCode": "USD"}})


def test_protocol_currency_must_be_explicit_three_letter_code():
    with pytest.raises(ValueError, match="three-letter"):
        gsma_transaction({"amount": {"amount": "1.00", "currency": ""}})
