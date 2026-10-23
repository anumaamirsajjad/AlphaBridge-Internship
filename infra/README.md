# Infrastructure (Terraform)

This folder describes every AWS resource the project uses. Changes are made here, through
Terraform, never in the AWS console.

## One-time setup (the only manual step)

Terraform stores its record of the resources in an S3 bucket, and locks it with a lock file in the same bucket.
Create the bucket once, in `ap-south-1`:

1. **S3:** create a bucket named `alphabridge-tfstate-169774886945`. Turn on **Versioning** and **Default encryption**. Block all public access.

The DynamoDB table created earlier is no longer used, and it can be deleted during cleanup.

## Commands

Run these from the `infra` folder, with credentials for the Terraform identity (see the open question in the project notes):

```powershell
cd "C:\Users\MTS\OneDrive\Desktop\transaction feature\infra"
terraform init            # downloads the AWS provider and connects to the state
terraform fmt -check      # checks the formatting
terraform validate        # checks the configuration
terraform plan -var "image_tag=<commit id>"   # shows what would change, changes nothing
terraform apply -var "image_tag=<commit id>"  # makes the changes
terraform destroy         # removes everything, used at cleanup
```

## Rules

- Never change a resource in the AWS console. Change this code, then `plan` and `apply`.
- The pipeline runs `plan` on pull requests, and `apply` after merging to `main`.
- Secrets are not stored here. The database password stays in Secrets Manager.
