# MUSITU Sovereign Payments — Zimbabwe RBZ 2026 Requirements Matrix

Date: 2026-10-06
Status: engineering requirements map; not regulatory approval
Authoritative engineering branch: `feature/musitu-sovereign-payments-20261006`

Primary sources:
- RBZ QR Code Payments Guideline, March 2026: https://www.rbz.co.zw/documents/Regulations_Acts/2026/QR_Code_Guideline_March_2026_signed.pdf
- RBZ National Payment System approval requirements: https://www.rbz.co.zw/index.php/financial-markets/nps/2-uncategorised
- RBZ National Payment System: https://www.rbz.co.zw/index.php/financial-markets/national-payment-system

## Requirement matrix

| RBZ requirement | Current MUSITU coverage | Gap / required action |
|---|---|---|
| RBZ approval before offering QR payment services | Financial Fabric production gate already requires regulator evidence before live funds | No RBZ approval exists; keep Zimbabwe profile reference-only |
| Interoperability across banks, mobile money and PSPs | Mojaloop, Payment Hub, GSMA MMAPI, ISO 20022, Open Payments foundations exist | No executed Zimbabwe participant interoperability certification |
| National Switch default inter-provider routing/clearing | Mojaloop/switch-clearing runtime exists | No Zimswitch/National Switch adapter or authorization exists |
| National Switch hosts National QR Repository | Phase 1 has a local reference QR repository | Must not represent local repository as National QR Repository; later integrate with operator-approved interface |
| MAI identifier coordination with National Switch | No MAI allocation exists | Add reference registry for caller-supplied MAI allocation references; do not invent MAI IDs |
| Scheme rules submitted to RBZ | Phase 1 defines technical state machines | Full scheme rules, settlement, disputes, consumer protection and fraud governance are external/open |
| Merchant KYC before QR onboarding | Existing merchant lifecycle has evidence-bound activation | Zimbabwe QR issuance must later bind to an approved merchant/KYC record, not merely an arbitrary merchant_ref |
| Five-year transaction/reconciliation/audit retention | Audit chain/reconciliation exist | Retention policy and real target storage lifecycle not yet proven |
| Real-time fraud detection | Production risk gate requires Tazama + Watchman | Zimbabwe target integration remains unproven |
| National AML/CFT integration | Risk/sanctions foundations exist | National AML/CFT system integration and authorization are open |
| Central repository maintains MAI ranges/templates and prevents duplication | Phase 1 aliases/QR IDs are unique locally | Add reference MAI uniqueness; authoritative allocation remains National Switch-owned |
| Least-privilege repository access and cryptographic controls | OpenFGA/OPA/SPIRE/OpenBao are required runtimes | No executed National QR Repository deployment/security audit |
| EMVCo QR standard / Zimbabwe Annexure 1 | No EMV payload serializer is claimed | Implement normalized profile fields first; serializer requires approved MAI/scheme data and conformance verification |
| Multi-scheme QR | Financial Fabric is multi-rail | No approved Zimbabwe multi-scheme payload/template yet |
| Sensitive identifiers masked/encrypted/tokenized | Card vault/security stack exists | Zimbabwe QR profile must avoid raw PAN/account/wallet IDs in payload |
| Dynamic QR preferred; amount + one-time nonce + expiry | Phase 1 has amount, nonce and optional expiry | Zimbabwe profile must require all three |
| Static QR only below USD50 equivalent plus strict controls | Generic reference static QR exists | Zimbabwe profile should reject static issuance until KYC/decal/store mapping/risk controls are evidenced |
| Remote/e-commerce requires dynamic QR/deep link | Generic QR has no channel policy | Zimbabwe profile must require dynamic for remote/e-commerce; safest Phase 2 is dynamic-only |
| Tag 01 = 12 dynamic; Tag 62-05 unique reference | Phase 1 has nonce but no normalized EMV tag declarations | Add reference fields `point_of_initiation_method=12` and `reference_tag_62_05=<nonce>`; do not claim serialization/certification |
| Offline store-and-forward may be supported under National Switch standards | `offline-value` is declared in Financial Fabric | Do not implement Zimbabwe offline settlement until National Switch technical standards are obtained |
| Settlement arrangements in operating rules | Provider settlement/ledger primitives exist | National scheme settlement-finality/liquidity rules are open |
| Periodic RBZ reports, fraud/security and uptime reporting | OpenTelemetry/audit/analytics foundations exist | Exact reporting templates, delivery mechanism and production evidence remain open |
| Retail payment-system provider governance/capital/risk/technology requirements | Strong technical control foundation | Corporate/legal/capital/governance submissions are external and cannot be manufactured by code |

## Phase 2 engineering boundary

Phase 2 may implement the Zimbabwe 2026 **reference profile** and MAI-allocation reference registry. It must remain fail-closed and non-production. It may not claim RBZ approval, National Switch registration, EMVCo certification, settlement finality, or live interoperability.

Static Zimbabwe QR issuance stays disabled until the required merchant/KYC/decal/terminal/risk controls can be represented with authentic external evidence. Offline Zimbabwe payment execution stays disabled until National Switch technical standards are obtained.
