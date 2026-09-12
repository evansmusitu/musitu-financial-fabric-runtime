variable "environment" {
  type        = string
  description = "Deployment environment."
  default     = "sandbox"
  validation {
    condition     = contains(["sandbox", "test", "development", "production"], var.environment)
    error_message = "environment must be sandbox, test, development, or production."
  }
}

variable "production_mode" {
  type        = string
  description = "Production activation mode."
  default     = "shadow"
  validation {
    condition     = contains(["shadow", "pilot", "live"], var.production_mode)
    error_message = "production_mode must be shadow, pilot, or live."
  }
}

variable "live_funds_enabled" {
  type        = bool
  description = "Explicit real-funds activation flag."
  default     = false
}

variable "authorization_manifest_path" {
  type        = string
  description = "Path to the externally retained production authorization evidence manifest."
  default     = ""
}

variable "authorization_manifest_sha256" {
  type        = string
  description = "SHA-256 pin of the external production authorization evidence manifest."
  default     = ""
  sensitive   = true
}

variable "deployment_evidence_manifest_path" {
  type        = string
  description = "Path to the retained target-environment deployment evidence manifest."
  default     = ""
}

variable "deployment_evidence_manifest_sha256" {
  type        = string
  description = "SHA-256 pin of the target-environment deployment evidence manifest."
  default     = ""
  sensitive   = true
}

variable "release_commit" {
  type        = string
  description = "Exact 40-hex source revision embedded in the running release."
  default     = ""
  validation {
    condition     = var.release_commit == "" || can(regex("^[0-9a-fA-F]{40}$", var.release_commit))
    error_message = "release_commit must be empty or an exact 40-hex commit SHA."
  }
}

variable "release_image_digest" {
  type        = string
  description = "Immutable OCI digest of the running release image."
  default     = ""
  validation {
    condition     = var.release_image_digest == "" || can(regex("^sha256:[0-9a-fA-F]{64}$", var.release_image_digest))
    error_message = "release_image_digest must be empty or a sha256 OCI digest."
  }
}

variable "production_enabled_rails" {
  type        = set(string)
  description = "Rails enabled by the deployment for production funds movement."
  default     = []
  validation {
    condition     = alltrue([for rail in var.production_enabled_rails : contains(["ecocash"], lower(rail))])
    error_message = "Only production connectors implemented by this release may be enabled."
  }
}

variable "production_enabled_currencies" {
  type        = set(string)
  description = "Currencies enabled by the deployment for production funds movement."
  default     = []
  validation {
    condition     = alltrue([for currency in var.production_enabled_currencies : can(regex("^[A-Z]{3}$", currency))])
    error_message = "Production currencies must use uppercase three-letter codes."
  }
}

variable "max_single_payment_minor" {
  type        = number
  description = "Deployment single-payment ceiling in minor units."
  default     = 0
  validation {
    condition     = var.max_single_payment_minor >= 0 && floor(var.max_single_payment_minor) == var.max_single_payment_minor
    error_message = "max_single_payment_minor must be a non-negative integer."
  }
}

locals {
  authorization_manifest_present = var.authorization_manifest_path != "" && fileexists(var.authorization_manifest_path)
  authorization_manifest_raw     = local.authorization_manifest_present ? file(var.authorization_manifest_path) : ""
  authorization_manifest         = try(jsondecode(local.authorization_manifest_raw), {})
  authorization_hash_matches = (
    local.authorization_manifest_present &&
    can(regex("^[0-9a-fA-F]{64}$", var.authorization_manifest_sha256)) &&
    lower(var.authorization_manifest_sha256) == sha256(local.authorization_manifest_raw)
  )
  authorization_evidence_bundle_path   = trimspace(try(local.authorization_manifest.evidence_bundle.path, ""))
  authorization_evidence_bundle_sha256 = lower(trimspace(try(local.authorization_manifest.evidence_bundle.sha256, "")))
  authorization_evidence_bundle_hash_matches = (
    local.authorization_evidence_bundle_path != "" &&
    can(regex("^[0-9a-fA-F]{64}$", local.authorization_evidence_bundle_sha256)) &&
    try(filesha256(local.authorization_evidence_bundle_path) == local.authorization_evidence_bundle_sha256, false)
  )

  required_evidence = ["regulator", "sponsor_bank", "data_protection", "independent_security", "rail_provider"]
  evidence_approved = alltrue([
    for key in local.required_evidence :
    try(local.authorization_manifest.evidence[key].status, "") == "approved" &&
    trimspace(try(local.authorization_manifest.evidence[key].evidence_ref, "")) != ""
  ])

  authorized_funds_scope = lower(try(local.authorization_manifest.funds_scope, ""))
  funds_scope_matches = (
    var.production_mode == "pilot" ? contains(["pilot", "production"], local.authorized_funds_scope) :
    var.production_mode == "live" ? local.authorized_funds_scope == "production" :
    false
  )

  authorization_not_expired = try(
    timecmp(try(local.authorization_manifest.expires_at, ""), plantimestamp()) > 0,
    false
  )

  authorized_rails = toset([
    for rail in try(local.authorization_manifest.launch_scope.rails, []) : lower(rail)
  ])
  authorized_currencies = toset([
    for currency in try(local.authorization_manifest.launch_scope.currencies, []) : upper(currency)
  ])
  authorized_max_single_payment_minor = try(tonumber(local.authorization_manifest.launch_scope.max_single_payment_minor), 0)

  runtime_rails      = toset([for rail in var.production_enabled_rails : lower(rail)])
  runtime_currencies = toset([for currency in var.production_enabled_currencies : upper(currency)])
  rails_within_authorization = (
    length(local.runtime_rails) > 0 &&
    length(local.authorized_rails) > 0 &&
    alltrue([for rail in local.runtime_rails : contains(local.authorized_rails, rail)])
  )
  currencies_within_authorization = (
    length(local.runtime_currencies) > 0 &&
    length(local.authorized_currencies) > 0 &&
    alltrue([for currency in local.runtime_currencies : contains(local.authorized_currencies, currency)])
  )
  payment_limit_within_authorization = (
    var.max_single_payment_minor > 0 &&
    local.authorized_max_single_payment_minor > 0 &&
    var.max_single_payment_minor <= local.authorized_max_single_payment_minor
  )

  deployment_manifest_present = var.deployment_evidence_manifest_path != "" && fileexists(var.deployment_evidence_manifest_path)
  deployment_manifest_raw     = local.deployment_manifest_present ? file(var.deployment_evidence_manifest_path) : ""
  deployment_manifest         = try(jsondecode(local.deployment_manifest_raw), {})
  deployment_hash_matches = (
    local.deployment_manifest_present &&
    can(regex("^[0-9a-fA-F]{64}$", var.deployment_evidence_manifest_sha256)) &&
    lower(var.deployment_evidence_manifest_sha256) == sha256(local.deployment_manifest_raw)
  )
  deployment_evidence_bundle_path   = trimspace(try(local.deployment_manifest.evidence_bundle.path, ""))
  deployment_evidence_bundle_sha256 = lower(trimspace(try(local.deployment_manifest.evidence_bundle.sha256, "")))
  deployment_evidence_bundle_hash_matches = (
    local.deployment_evidence_bundle_path != "" &&
    can(regex("^[0-9a-fA-F]{64}$", local.deployment_evidence_bundle_sha256)) &&
    try(filesha256(local.deployment_evidence_bundle_path) == local.deployment_evidence_bundle_sha256, false)
  )
  deployment_target_identity = trimspace(try(local.deployment_manifest.target_environment_id, "")) != ""

  release_commit_matches = (
    can(regex("^[0-9a-fA-F]{40}$", var.release_commit)) &&
    lower(try(local.deployment_manifest.release.commit_sha, "")) == lower(var.release_commit)
  )
  release_image_matches = (
    can(regex("^sha256:[0-9a-fA-F]{64}$", var.release_image_digest)) &&
    lower(try(local.deployment_manifest.release.image_digest, "")) == lower(var.release_image_digest)
  )
  rollback_image_digest = lower(try(local.deployment_manifest.release.rollback_image_digest, ""))
  rollback_image_valid = (
    can(regex("^sha256:[0-9a-fA-F]{64}$", local.rollback_image_digest)) &&
    local.rollback_image_digest != lower(var.release_image_digest)
  )
  deployment_authorization_binding = (
    can(regex("^[0-9a-fA-F]{64}$", var.authorization_manifest_sha256)) &&
    lower(try(local.deployment_manifest.release.authorization_manifest_sha256, "")) == lower(var.authorization_manifest_sha256)
  )

  deployment_required_evidence = [
    "dark_deployment",
    "monitoring_alerting",
    "postgres_backup_restore",
    "tigerbeetle_recovery",
    "provider_reconciliation",
    "activation_rollback_drill",
  ]
  deployment_evidence_passed = alltrue([
    for key in local.deployment_required_evidence :
    try(local.deployment_manifest.evidence[key].status, "") == "passed" &&
    trimspace(try(local.deployment_manifest.evidence[key].evidence_ref, "")) != ""
  ])

  independent_kill_control_names = ["network", "provider", "settlement"]
  independent_kill_controls_verified = alltrue([
    for key in local.independent_kill_control_names :
    try(local.deployment_manifest.independent_kill_controls[key].status, "") == "verified" &&
    try(local.deployment_manifest.independent_kill_controls[key].independent_of_application, false) == true &&
    trimspace(try(local.deployment_manifest.independent_kill_controls[key].evidence_ref, "")) != ""
  ])

  deployment_verified_at_valid = try(
    timecmp(try(local.deployment_manifest.verified_at, ""), plantimestamp()) <= 0,
    false
  )
  deployment_not_expired = try(
    timecmp(try(local.deployment_manifest.expires_at, ""), plantimestamp()) > 0,
    false
  )
}

resource "terraform_data" "musitu_production_guard" {
  input = {
    environment              = var.environment
    production_mode          = var.production_mode
    live_funds               = var.live_funds_enabled
    enabled_rails            = sort(tolist(local.runtime_rails))
    enabled_currencies       = sort(tolist(local.runtime_currencies))
    max_single_payment_minor = var.max_single_payment_minor
    release_commit           = lower(var.release_commit)
    release_image_digest     = lower(var.release_image_digest)
  }

  lifecycle {
    precondition {
      condition = !var.live_funds_enabled || (
        var.environment == "production" &&
        contains(["pilot", "live"], var.production_mode) &&
        local.authorization_hash_matches &&
        local.authorization_evidence_bundle_hash_matches &&
        local.evidence_approved &&
        local.funds_scope_matches &&
        local.authorization_not_expired &&
        local.rails_within_authorization &&
        local.currencies_within_authorization &&
        local.payment_limit_within_authorization
      )
      error_message = "Live funds require a byte-pinned, unexpired external authorization manifest and byte-pinned authorization evidence bundle whose approved evidence, funds scope, rails, currencies, and single-payment ceiling contain the exact deployment perimeter."
    }

    precondition {
      condition = !var.live_funds_enabled || (
        local.deployment_hash_matches &&
        local.deployment_evidence_bundle_hash_matches &&
        local.deployment_target_identity &&
        local.release_commit_matches &&
        local.release_image_matches &&
        local.rollback_image_valid &&
        local.deployment_authorization_binding &&
        local.deployment_evidence_passed &&
        local.independent_kill_controls_verified &&
        local.deployment_verified_at_valid &&
        local.deployment_not_expired
      )
      error_message = "Live funds require a byte-pinned target deployment evidence manifest and byte-pinned target evidence bundle bound to the exact release commit, immutable OCI digest, distinct rollback digest, external authorization pin, executed target-environment drills, and independent network/provider/settlement kill controls."
    }
  }
}
