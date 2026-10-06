# Operational Runbook: On-Call & Incident Response

## 1. Alarm Catalog & Response Procedures

### Alarm: `serverless-orders-dlq-messages-visible-prod`
- **Severity**: High (P2)
- **Description**: Triggered when 1 or more failed messages land in the SQS Dead Letter Queue (`serverless-orders-dlq-prod`).
- **Diagnosis**:
  1. Inspect DLQ messages in AWS Console or via AWS CLI:
     ```bash
     aws sqs receive-message \
       --queue-url "https://sqs.us-east-1.amazonaws.com/293162038789/serverless-orders-dlq-prod" \
       --attribute-names All \
       --message-attribute-names All \
       --max-number-of-messages 5
     ```
  2. Search CloudWatch Logs for the `orderId` or `messageId` in `/aws/lambda/serverless-orders-worker-prod`.
  3. Check the `errorMessage` field in DynamoDB:
     ```bash
     aws dynamodb get-item \
       --table-name serverless-orders-prod \
       --key '{"orderId": {"S": "<ORDER_ID>"}}'
     ```
- **Remediation**:
  1. If root cause was a temporary downstream outage that has been resolved, execute a **DLQ Redrive** (see Section 2).
  2. If the payload is invalid/poison pill, record the event and let the DLQ retain or purge the message.

---

### Alarm: `serverless-orders-ingest-errors-prod`
- **Severity**: Critical (P1)
- **Description**: Triggered when Ingest Lambda experiences runtime exceptions.
- **Diagnosis**:
  ```bash
  aws logs filter-log-events \
    --log-group-name "/aws/lambda/serverless-orders-ingest-prod" \
    --filter-pattern "ERROR" \
    --start-time $(date -d '15 minutes ago' +%s000)
  ```
- **Remediation**: Check for DynamoDB throttling or IAM permission issues.

---

### Alarm: `serverless-orders-api-5xx-prod`
- **Severity**: High (P2)
- **Description**: API Gateway is returning 5xx responses (integration failure or Lambda crash).
- **Diagnosis**: Inspect `/aws/vendedlogs/apis/serverless-orders-api-prod` for `$context.status >= 500`.

---

## 2. DLQ Inspection and Redrive Guide

### How SQS Redrive Works
The DLQ is configured with an **SQS Redrive Allow Policy** permitting the main queue (`serverless-orders-queue-prod`) as its destination.

### Starting a Message Move Task (CLI)
To move all messages from the DLQ back to the main queue for reprocessing:
```bash
# 1. Start Redrive
aws sqs start-message-move-task \
  --source-arn "arn:aws:sqs:us-east-1:293162038789:serverless-orders-dlq-prod"

# 2. Check Redrive Progress
aws sqs list-message-move-tasks \
  --source-arn "arn:aws:sqs:us-east-1:293162038789:serverless-orders-dlq-prod"
```

---

## 3. Routine Operations & Maintenance

### Checking Free-Tier Usage and Spend
```bash
aws budgets describe-budget \
  --account-id 293162038789 \
  --budget-name "serverless-orders-safety-budget-prod"
```

### Complete Infrastructure Teardown
To remove all AWS resources and eliminate any lingering footprint:
```bash
cd infra
terraform destroy -auto-approve
```
