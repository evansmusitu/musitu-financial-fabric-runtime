# MUSITU Financial Fabric — Provider-Neutral Target Staging

This directory is a **fail-closed staging contract**, not a production deployment and not evidence that a production target exists.

It is isolated on branch `musitu-financial-fabric-provider-neutral-target-staging-20260912` and is anchored to authoritative runtime release `80c72d9f711561dd46337d7286ee7bfb2bb5e658`. The authoritative release branch is not changed by this work.

## Purpose

Advance target architecture without cloud spend or fabricated deployment evidence. The contract preserves the exact 26 required runtime boundary from `musitu_financial_fabric/stack/required-components.json` and makes unresolved production facts explicit instead of guessing them.

## Fail-closed foundation

The Kustomize foundation contains only:

- a dedicated namespace labelled as staging-only and not production-authorized;
- Kubernetes Pod Security Admission labels at `restricted` for enforce, audit, and warn;
- a namespace-wide default-deny NetworkPolicy for ingress and egress;
- a ResourceQuota with `pods: "0"`.

There are intentionally **no runtime Deployments, StatefulSets, DaemonSets, Jobs, Services, Ingresses/Gateways, PVCs, Secrets, ConfigMaps containing credentials, or cloud resources** here. The zero-pod quota means this foundation cannot admit workloads even if someone applies it accidentally.

## Exact runtime contract

`runtime-contract.json` enumerates all 26 required runtime components and their authoritative health-variable mapping. Every deployment-specific field remains unresolved until it has real evidence:

- immutable image digest and provenance;
- concrete manifest path;
- measured resource profile;
- startup/readiness/liveness probe profile;
- least-privilege network profile;
- workload identity profile;
- secret-delivery profile;
- persistence profile where applicable;
- backup/restore profile where applicable;
- PodDisruptionBudget profile;
- topology/anti-affinity profile;
- measured benchmark result.

No component is deployable merely because it appears in the inventory.

## Workload identity and secrets boundary

The target architecture requires workload identity rather than shared static credentials. SPIFFE/SPIRE is the required workload-identity runtime and OpenBao is the required secrets/PKI runtime. Exact bootstrap and trust-domain mechanics remain unresolved until the target environment and deployment method are selected and tested.

Plaintext production credentials, provider tokens, KYC data, customer data, EcoCash secrets, bank credentials, and regulatory approvals must never be invented or committed here.

## Persistence and recovery boundary

Stateful runtimes require an explicit storage, backup, restore, durability, encryption, retention, and recovery test profile before deployability can pass. A manifest that merely creates a PVC is not recovery evidence.

## Availability boundary

Runtime manifests must define appropriate startup/readiness/liveness probes, disruption budgets, and topology spread or anti-affinity. Those values are component-specific and must not be fabricated. They become acceptable only after upstream requirements and measured behavior are recorded.

## Resource benchmarking

`resource-benchmark-plan.json` is a measurement protocol, not production sizing. CPU, memory, storage, queue/backlog, and latency values must be measured against a declared load model. Until a component has a measured result, its `benchmark_status` stays `unmeasured` and deployability fails.

## Immutable supply-chain boundary

Production-intended workload images must use exact `sha256:<64-hex>` OCI digests with retained provenance. Mutable tags alone are insufficient. This contract does not choose image digests on behalf of upstream projects.

## Target-health evidence

After a real target is explicitly authorized, fully deployed, and bound to an exact release commit and image digest, the existing `musitu_financial_fabric/scripts/collect_runtime_health_evidence.py` collector remains the authority for the 26-runtime health proof. Static manifests or CI validation do not substitute for that target-side evidence.

## Live funds and claims

`MUSITU_LIVE_FUNDS_ENABLED` remains false. Nothing in this directory constitutes provider approval, bank approval, regulatory approval, production authorization, independent validation, customer evidence, or permission to move live funds.
