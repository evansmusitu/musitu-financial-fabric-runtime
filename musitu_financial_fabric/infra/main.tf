terraform {
  required_version = ">= 1.8.0"
}

locals {
  system_name = "musitu-financial-fabric"
  environment = "sandbox"
}

output "system_name" {
  value = local.system_name
}

output "environment" {
  value = local.environment
}
