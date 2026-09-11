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

variable "authorization_manifest_sha256" {
  type        = string
  description = "SHA-256 pin of the external production authorization evidence manifest."
  default     = ""
  sensitive   = true
}

resource "terraform_data" "musitu_production_guard" {
  input = {
    environment     = var.environment
    production_mode = var.production_mode
    live_funds      = var.live_funds_enabled
  }

  lifecycle {
    precondition {
      condition = !var.live_funds_enabled || (
        var.environment == "production" &&
        contains(["pilot", "live"], var.production_mode) &&
        can(regex("^[0-9a-fA-F]{64}$", var.authorization_manifest_sha256))
      )
      error_message = "Live funds require production environment, pilot/live mode, and a pinned external authorization manifest SHA-256."
    }
  }
}
