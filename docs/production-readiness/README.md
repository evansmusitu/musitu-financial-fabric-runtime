# MUSITU Financial Fabric — Production Readiness

Baseline sandbox evidence SHA: `fa2f8967c01e76cb2141475a77678431dc93d4db`.

This directory is the fail-closed production-readiness control plane. Sandbox completeness does not equal production authorization.

Production activation is forbidden until every software-controlled production gate is PASS and every external/regulatory dependency has independent evidence recorded.

Never infer or claim RBZ approval, EcoCash production connectivity, sponsor-bank approval, card-network certification, custody authorization, or permission to handle real customer funds from repository or CI evidence alone.


Real-funds readiness now has two independent pinned evidence inputs: the external authorization manifest and a target-deployment evidence manifest. The latter must bind the exact running commit/image, rollback image, authorization-manifest digest, executed target-environment drills, and evidence of independent network/provider/settlement kill controls. It is deliberately fail-closed and does not convert self-authored metadata into external authorization.
