# Terraform state bootstrap

GitHub-hosted runners have empty local disks. The application configuration therefore uses this S3 backend and DynamoDB lock table, created once before the normal `infra/` configuration is initialized.

Run this only with an authorized human/operator AWS session in account `293162038789` and `us-east-1`:

```powershell
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply
terraform -chdir=infra init -migrate-state
terraform -chdir=infra plan
```

When prompted by `-migrate-state`, answer `yes` to copy the existing local state into the encrypted, versioned S3 bucket. Do not run `terraform apply` from GitHub until migration has completed. If the bucket or lock table was already created outside Terraform, import it into this bootstrap state instead of deleting it.

The bootstrap resources are intentionally protected from destruction. They retain history for the application stack; deleting them would again make GitHub deployments attempt to recreate tracked AWS resources.
