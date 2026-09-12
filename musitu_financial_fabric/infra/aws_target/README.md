# MUSITU Financial Fabric — AWS target staging foundation

This directory is a **staging implementation**, not proof of a deployed production target.

It is intentionally isolated on branch `musitu-financial-fabric-aws-target-staging-20260912` while the authoritative production-readiness release remains at `80c72d9f711561dd46337d7286ee7bfb2bb5e658`.

## What this layer implements

- AWS Africa (Cape Town), `af-south-1`, as the provisional target region.
- Three-AZ VPC topology with public ingress subnets, private workload subnets, per-AZ NAT gateways, and an S3 gateway endpoint.
- Amazon EKS foundation with:
  - Kubernetes 1.36 pin for staging validation;
  - private API access always enabled;
  - public API access disabled unless an explicit non-world-open CIDR allowlist is supplied;
  - all control-plane log types enabled;
  - KMS envelope encryption;
  - API-based EKS access with no implicit cluster-creator administrator;
  - an explicit administrator IAM principal;
  - three-node minimum on-demand worker baseline.
- Production-like PostgreSQL foundation with:
  - exact engine version required at plan/apply;
  - exact instance class required at plan/apply;
  - Multi-AZ;
  - KMS encryption;
  - RDS-managed master password in Secrets Manager;
  - 35-day backups;
  - deletion protection and final snapshot;
  - no public endpoint;
  - a fail-closed security group with no ingress/egress until the runtime network layer is explicitly reviewed.
- Immutable target-evidence storage with:
  - a dedicated KMS key;
  - S3 versioning;
  - public-access blocking;
  - Object Lock in COMPLIANCE mode;
  - default retention of at least 90 days (365 by default);
  - Terraform `prevent_destroy` for the evidence bucket and evidence key.
- A reserved, fail-closed TigerBeetle security boundary and a contract for six dedicated replica slots.

## What this layer deliberately does **not** implement

It does **not** deploy TigerBeetle replicas. Upstream production guidance must be re-read at the exact pinned TigerBeetle release before selecting EC2 host class, storage, AMI, ports, replica placement, quorum/recovery procedures, and network rules. Docker/Kubernetes is not being assumed for TigerBeetle.

It does **not** deploy the remaining required runtime components. The authoritative registry still requires all 26 runtime rows to be deployed and observed healthy on the same exact target before `required_runtime_health` may pass.

It does **not** configure PostgreSQL workload ingress. That is added only when the EKS workload security groups/service identities and exact dependent runtimes are pinned.

It does **not** create or infer EcoCash credentials, regulatory approval, bank authorization, production secrets, customer data, or live-funds permission.

It does **not** define `MUSITU_LIVE_FUNDS_ENABLED=true`. The target remains a dark/shadow environment until every external and target-evidence gate genuinely passes.

## Validation without AWS credentials

The staging CI performs formatting, provider initialization, and static OpenTofu validation only. It does not run `plan` or `apply`, and therefore does not claim regional capacity, account quotas, cost approval, or real target evidence.

The AWS provider is pinned to `6.62.0`. The current EKS minor pin is `1.36`; both must be reviewed before an authorized apply.

## Inputs required before a real plan/apply

At minimum:

- `target_environment_id` — immutable target identity, assigned independently of evidence manifests;
- `eks_admin_principal_arn` — real authorized IAM role/user ARN;
- `postgres_engine_version` — exact dependency-reviewed RDS PostgreSQL version;
- `postgres_instance_class` — exact capacity/cost-reviewed RDS class.

Before any apply, also establish:

- an authorized AWS account and billing owner;
- explicit budget alarms/guardrails;
- sufficient af-south-1 service quotas;
- approved remote OpenTofu state storage/locking and operator IAM;
- the exact runtime deployment plan for all 26 required components;
- the pinned TigerBeetle release and immutable host image;
- upstream chart/operator/image pins and provenance for the Kubernetes runtime layer.

## Acceptance boundary

Successful `tofu validate` means only that this foundation is structurally valid against the pinned provider schema. It does not mean AWS resources exist.

The real target reaches topology-deployed state only after the full 26-runtime environment and MUSITU application are actually deployed on one immutable target and every provisioning record is retained. It reaches runtime-health-passed state only after the repository's target-side collector exits 0 against that exact target/build.
