output "aws_region" {
  value = var.aws_region
}

output "target_environment_id" {
  value = var.target_environment_id
}

output "runtime_build_commit" {
  value = var.runtime_build_commit
}

output "availability_zones" {
  value = local.availability_zones
}

output "vpc_id" {
  value = aws_vpc.target.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "eks_cluster_name" {
  value = aws_eks_cluster.fabric.name
}

output "eks_cluster_endpoint" {
  value     = aws_eks_cluster.fabric.endpoint
  sensitive = true
}

output "eks_cluster_security_group_id" {
  value = aws_eks_cluster.fabric.vpc_config[0].cluster_security_group_id
}

output "postgres_endpoint" {
  value     = aws_db_instance.metadata.endpoint
  sensitive = true
}

output "postgres_master_secret_arn" {
  value     = try(aws_db_instance.metadata.master_user_secret[0].secret_arn, null)
  sensitive = true
}

output "postgres_security_group_id" {
  value = aws_security_group.postgres.id
}

output "evidence_bucket_name" {
  value = aws_s3_bucket.evidence.id
}

output "evidence_kms_key_arn" {
  value = aws_kms_key.evidence.arn
}

output "platform_kms_key_arn" {
  value = aws_kms_key.platform.arn
}

output "tigerbeetle_required_replicas" {
  value = local.tigerbeetle_required_replicas
}

output "tigerbeetle_security_group_id" {
  value = aws_security_group.tigerbeetle.id
}

output "tigerbeetle_candidate_private_subnet_ids" {
  value = aws_subnet.private[*].id
}
