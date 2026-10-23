# Pins the Terraform version and the AWS provider, so every run uses the same tools.
#
# The state (the record of what Terraform created) is stored in S3. A lock file in the same
# bucket stops two runs from changing things at the same time. The bucket is created once by
# hand (see README.md). That's the only manual step.

terraform {
  required_version = ">= 1.6.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "5.80.0"
    }
  }

  backend "s3" {
    bucket       = "alphabridge-tfstate-169774886945"
    key          = "alphabridge/terraform.tfstate"
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true
  }
}
