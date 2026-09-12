resource "aws_db_subnet_group" "metadata" {
  name       = "${local.cluster_name}-postgres"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.cluster_name}-postgres"
  }
}

resource "aws_security_group" "postgres" {
  name        = "${local.cluster_name}-postgres"
  description = "Fail-closed PostgreSQL boundary; workload ingress is added only by a reviewed runtime layer."
  vpc_id      = aws_vpc.target.id

  ingress = []
  egress  = []

  tags = {
    Name = "${local.cluster_name}-postgres"
  }
}

resource "aws_db_instance" "metadata" {
  identifier = "${local.cluster_name}-postgres"

  engine         = "postgres"
  engine_version = var.postgres_engine_version
  instance_class = var.postgres_instance_class

  allocated_storage     = var.postgres_allocated_storage_gib
  max_allocated_storage = var.postgres_max_allocated_storage_gib
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.platform.arn

  db_name  = "musitu"
  username = "musituadmin"

  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.platform.arn

  multi_az               = true
  publicly_accessible    = false
  db_subnet_group_name   = aws_db_subnet_group.metadata.name
  vpc_security_group_ids = [aws_security_group.postgres.id]

  backup_retention_period   = 35
  copy_tags_to_snapshot     = true
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.cluster_name}-postgres-final"

  auto_minor_version_upgrade = false
  apply_immediately          = false

  performance_insights_enabled    = true
  performance_insights_kms_key_id = aws_kms_key.platform.arn

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "${local.cluster_name}-postgres"
    Purpose = "metadata-transactional-state"
  }
}
