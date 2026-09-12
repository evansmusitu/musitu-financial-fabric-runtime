data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  availability_zones = slice(sort(data.aws_availability_zones.available.names), 0, 3)
  cluster_name       = "${var.name_prefix}-${var.target_environment_id}"

  common_tags = {
    System              = "musitu-financial-fabric"
    Environment         = "production-shadow"
    TargetEnvironmentId = var.target_environment_id
    RuntimeBuildCommit  = var.runtime_build_commit
    LiveFunds           = "disabled"
    ManagedBy           = "opentofu"
    IaCStage            = "aws-target-staging"
  }

  evidence_bucket_name = "${var.name_prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-${var.target_environment_id}-evidence"
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

check "three_failure_domains_available" {
  assert {
    condition     = length(data.aws_availability_zones.available.names) >= 3
    error_message = "The selected AWS account/region must expose at least three available Availability Zones."
  }
}

check "eks_scaling_bounds_are_coherent" {
  assert {
    condition = (
      var.eks_node_min_size >= 3 &&
      var.eks_node_desired_size >= var.eks_node_min_size &&
      var.eks_node_max_size >= var.eks_node_desired_size
    )
    error_message = "EKS scaling must preserve at least three nodes and coherent min/desired/max bounds."
  }
}
