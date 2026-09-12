locals {
  tigerbeetle_required_replicas = 6
}

resource "aws_security_group" "tigerbeetle" {
  name        = "${local.cluster_name}-tigerbeetle"
  description = "Reserved fail-closed security boundary for dedicated TigerBeetle replicas."
  vpc_id      = aws_vpc.target.id

  # No network path is opened in the foundation layer. Exact client/operator
  # rules are added only after the pinned TigerBeetle release, AMI, ports,
  # quorum topology, and recovery design are reviewed.
  ingress = []
  egress  = []

  tags = {
    Name    = "${local.cluster_name}-tigerbeetle"
    Purpose = "dedicated-ledger-plane"
  }
}

check "tigerbeetle_replica_contract" {
  assert {
    condition     = local.tigerbeetle_required_replicas == 6
    error_message = "The current real-target contract requires six production-faithful TigerBeetle replica slots."
  }
}
