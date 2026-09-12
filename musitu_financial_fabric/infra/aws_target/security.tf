resource "aws_kms_key" "platform" {
  description             = "MUSITU Financial Fabric target platform encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  tags = {
    Name = "${local.cluster_name}-platform"
  }
}

resource "aws_kms_alias" "platform" {
  name          = "alias/${local.cluster_name}-platform"
  target_key_id = aws_kms_key.platform.key_id
}

resource "aws_kms_key" "evidence" {
  description             = "MUSITU Financial Fabric immutable target evidence encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = "${local.cluster_name}-evidence"
  }
}

resource "aws_kms_alias" "evidence" {
  name          = "alias/${local.cluster_name}-evidence"
  target_key_id = aws_kms_key.evidence.key_id
}

resource "aws_s3_bucket" "evidence" {
  bucket              = local.evidence_bucket_name
  force_destroy       = false
  object_lock_enabled = true

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = local.evidence_bucket_name
    Purpose = "target-evidence"
  }
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.evidence.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  depends_on = [aws_s3_bucket_versioning.evidence]

  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.evidence_retention_days
    }
  }
}

data "aws_iam_policy_document" "evidence_bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.evidence.arn,
      "${aws_s3_bucket.evidence.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  policy = data.aws_iam_policy_document.evidence_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.evidence]
}
