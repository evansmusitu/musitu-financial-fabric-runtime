variable "aws_region" {
  description = "AWS region for the real-target staging foundation."
  type        = string
  default     = "af-south-1"

  validation {
    condition     = var.aws_region == "af-south-1"
    error_message = "This staging target is intentionally bound to AWS Africa (Cape Town), af-south-1."
  }
}

variable "name_prefix" {
  description = "Lowercase DNS-safe prefix for target resources."
  type        = string
  default     = "mff"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-20 lowercase DNS-safe characters."
  }
}

variable "target_environment_id" {
  description = "Immutable target identity owned by the deployment environment, not by evidence files."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{2,62}$", var.target_environment_id))
    error_message = "target_environment_id must be 3-63 lowercase letters, digits, or hyphens and start with a letter/digit."
  }
}

variable "runtime_build_commit" {
  description = "Exact MUSITU runtime commit intended for this target."
  type        = string
  default     = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.runtime_build_commit))
    error_message = "runtime_build_commit must be an exact 40-character lowercase Git SHA."
  }
}

variable "vpc_cidr" {
  description = "Dedicated VPC CIDR for the target."
  type        = string
  default     = "10.42.0.0/16"
}

variable "eks_kubernetes_version" {
  description = "Pinned EKS Kubernetes minor version. Re-review before apply."
  type        = string
  default     = "1.36"
}

variable "eks_admin_principal_arn" {
  description = "Explicit IAM principal granted EKS cluster-admin access through the EKS access API."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/.+$", var.eks_admin_principal_arn))
    error_message = "eks_admin_principal_arn must be an IAM role or user ARN."
  }
}

variable "eks_public_access_cidrs" {
  description = "Optional explicit CIDRs allowed to reach the EKS public API. Empty keeps public API access disabled."
  type        = list(string)
  default     = []

  validation {
    condition = (
      !contains(var.eks_public_access_cidrs, "0.0.0.0/0") &&
      !contains(var.eks_public_access_cidrs, "::/0")
    )
    error_message = "World-open EKS API CIDRs are forbidden."
  }
}

variable "eks_node_instance_types" {
  description = "Pinned candidate EKS worker instance types; verify regional capacity before apply."
  type        = list(string)
  default     = ["m7i.large"]
}

variable "eks_node_min_size" {
  type    = number
  default = 3
}

variable "eks_node_desired_size" {
  type    = number
  default = 3
}

variable "eks_node_max_size" {
  type    = number
  default = 9
}

variable "postgres_engine_version" {
  description = "Exact RDS PostgreSQL engine version approved after dependency compatibility review. Required for plan/apply."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+(\\.[0-9]+){0,2}$", var.postgres_engine_version))
    error_message = "postgres_engine_version must be an explicit numeric version, for example 17.6."
  }
}

variable "postgres_instance_class" {
  description = "Exact RDS instance class approved after capacity/cost review."
  type        = string
}

variable "postgres_allocated_storage_gib" {
  type    = number
  default = 100

  validation {
    condition     = var.postgres_allocated_storage_gib >= 100
    error_message = "Production-like PostgreSQL allocated storage must be at least 100 GiB."
  }
}

variable "postgres_max_allocated_storage_gib" {
  type    = number
  default = 500

  validation {
    condition     = var.postgres_max_allocated_storage_gib >= var.postgres_allocated_storage_gib
    error_message = "Maximum PostgreSQL storage must be at least allocated storage."
  }
}

variable "evidence_retention_days" {
  description = "Default immutable retention for target evidence objects."
  type        = number
  default     = 365

  validation {
    condition     = var.evidence_retention_days >= 90
    error_message = "Target evidence retention must be at least 90 days."
  }
}
