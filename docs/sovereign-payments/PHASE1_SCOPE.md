# MUSITU Sovereign Payments — Phase 1 Scope

Date: 2026-10-06
Branch: `feature/musitu-sovereign-payments-20261006`
Base Financial Fabric commit: `a80ce52c3b8fcef3e6cece76103417236bcb0c4c`

## Purpose

Phase 1 adds scheme-level reference primitives to MUSITU Financial Fabric without changing its international multi-rail product boundary or enabling a new production payment rail.

Implemented reference capabilities:

- sovereign participant registry and payment-alias directory;
- sovereign QR repository with nonce and expiry controls;
- request-to-pay creation, idempotency, actor-controlled terminal decisions, and accepted payment-instruction envelopes.

## Safety and production boundary

These capabilities do not authorize or move real funds.

Phase 1 does **not**:

- add `sovereign` to the existing production rail allow-list;
- modify the existing EcoCash production-connector authorization boundary;
- post to TigerBeetle or any settlement account as a result of QR resolution or request-to-pay acceptance;
- claim RBZ, Zimswitch, NPCI/UPI, EMVCo, bank, card-network, or mobile-money certification;
- modify the authoritative 39-item Financial Fabric required-component registry;
- implement national clearing finality, participant liquidity management, scheme certification, dispute adjudication, offline value, or a production national switch.

## Architecture

The sovereign scheme layer sits above participant and alias records and below later payment orchestration. A QR resolution or accepted request-to-pay returns normalized payment-initiation data only. A future explicitly authorized orchestration step may translate that instruction into an existing Financial Fabric payment intent or an approved national-switch message.

## Required external work before any production claim

A production sovereign deployment requires, at minimum:

- explicit regulator and scheme/operator authorization;
- approved participant and settlement-bank roles;
- a finalized national addressing and QR profile;
- participant onboarding/certification rules;
- clearing, settlement-finality and liquidity controls;
- disputes, refunds/reversals and consumer-protection rules;
- independent security review and retest;
- target deployment evidence and live-funds authorization under the existing Financial Fabric production gate.

## Phase 2 candidates

The next engineering layer should cover participant certification states, national-switch message adapters, clearing/liquidity control contracts, scheme fees and limits, disputes/reversals, and approved QR serialization profiles. Those capabilities must remain isolated from production until the external scheme design is agreed.
