# Demo Cost Safety

This stack is designed for a small demo workload, not a guarantee of zero AWS charges. Confirm current AWS pricing and Free Tier eligibility for the deployment account and region before applying Terraform.

## Boundaries

- API Gateway is throttled to 5 RPS with a burst of 10; ingest rejects bodies over 10 KiB.
- DynamoDB uses on-demand billing and TTL removes orders and verification records after seven days. TTL deletion is asynchronous.
- Lambda and API logs retain seven days.
- The verification runner receives one job at a time, has a 60-second timeout, accepts only fixed scenarios, and uses at most 10 requests for its small-load probe (below its hard limit of 100).
- Failure tokens affect at most three tagged verification requests and expire within 900 seconds.
- Terraform creates an AWS Budget alert; an alert does not stop usage.

## Demo workload and cleanup

Run a small number of verification jobs manually. Do not expose the application token from the hosted site or use public verification automation. When finished, run `terraform destroy` from `infra/`, then confirm that queues, functions, log groups, and the budget have been removed as intended.
