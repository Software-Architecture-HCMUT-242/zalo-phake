# Notification Consumer Service Deployment Guide

This document outlines the deployment procedure for the Notification Consumer Service, a component of the redesigned notification system for the Zalo-Phake chat application.

## Overview

The Notification Consumer Service is a standalone microservice that processes notification events from an AWS SQS queue and delivers push notifications to users via Firebase Cloud Messaging (FCM). It's designed to run as a containerized application in AWS ECS Fargate.

## Prerequisites

Before deploying the Notification Consumer Service, ensure the following prerequisites are met:

1. AWS account with appropriate permissions for:
   - Amazon ECR (Elastic Container Registry)
   - Amazon ECS (Elastic Container Service)
   - Amazon SQS (Simple Queue Service)
   - AWS Secrets Manager
   - AWS CloudWatch Logs

2. AWS CLI configured with appropriate credentials
3. Docker installed locally for building container images
4. Firebase project with Cloud Messaging enabled
5. Firebase service account credentials

## Environment Variables

The Notification Consumer Service requires the following environment variables:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `ENVIRONMENT` | Deployment environment (dev, staging, prod) | No | `dev` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | No | `INFO` |
| `SERVICE_NAME` | Service name for logs | No | `notification-consumer` |
| `AWS_REGION` | AWS region | No | `ap-southeast-1` |
| `AWS_ACCESS_KEY_ID` | AWS access key ID | Yes | - |
| `AWS_SECRET_ACCESS_KEY` | AWS secret access key | Yes | - |
| `MAIN_QUEUE_URL` | URL of the main SQS queue | Yes | - |
| `RETRY_QUEUE_URL` | URL of the retry SQS queue | Yes | - |
| `DLQ_URL` | URL of the dead-letter SQS queue | Yes | - |
| `FIREBASE_SECRET` | Firebase service account credentials (JSON) | Yes | - |
| `FIREBASE_DB_URL` | Firebase database URL | No | `https://zalophake-bf746-default-rtdb.firebaseio.com/` |

## AWS Resources Setup

### 1. SQS Queues

Create the following SQS queues:

```bash
# Main notification queue
aws sqs create-queue \
  --queue-name zalo-phake-notifications \
  --attributes "{\"VisibilityTimeout\":\"60\", \"MessageRetentionPeriod\":\"345600\", \"RedrivePolicy\":\"{\\\"deadLetterTargetArn\\\":\\\"arn:aws:sqs:REGION:ACCOUNT_ID:zalo-phake-notifications-dlq\\\", \\\"maxReceiveCount\\\":\\\"5\\\"}\"}"

# Retry queue
aws sqs create-queue \
  --queue-name zalo-phake-notifications-retry \
  --attributes "{\"VisibilityTimeout\":\"120\", \"MessageRetentionPeriod\":\"86400\", \"DelaySeconds\":\"60\"}"

# Dead-letter queue
aws sqs create-queue \
  --queue-name zalo-phake-notifications-dlq \
  --attributes "{\"MessageRetentionPeriod\":\"1209600\"}"
```

### 2. IAM Role

Create an IAM role for the ECS task with the following permissions:
- `AmazonSQSFullAccess` - For interacting with SQS queues
- `CloudWatchLogsFullAccess` - For writing logs to CloudWatch

### 3. Secrets Manager

Store sensitive configuration in AWS Secrets Manager:

```bash
# Create a secret for AWS credentials
aws secretsmanager create-secret \
  --name zalo-phake/notification-consumer \
  --secret-string "{\"aws_access_key_id\":\"YOUR_ACCESS_KEY\", \"aws_secret_access_key\":\"YOUR_SECRET_KEY\", \"firebase_secret\":\"YOUR_FIREBASE_JSON\"}"
```

## Deployment Steps

### 1. Build the Docker Image

```bash
cd notification_consumer
docker build -t zalo-phake/notification-consumer:latest .
```

### 2. Push to Amazon ECR

```bash
# Create ECR repository if it doesn't exist
aws ecr create-repository --repository-name zalo-phake/notification-consumer

# Get ECR login token
aws ecr get-login-password | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com

# Tag and push image
docker tag zalo-phake/notification-consumer:latest ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/zalo-phake/notification-consumer:latest
docker push ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/zalo-phake/notification-consumer:latest
```

### 3. Create ECS Task Definition

Replace `ACCOUNT_ID` and `REGION` in the `task-definition.json` file with your AWS account ID and region, then register the task definition:

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

### 4. Create ECS Service

```bash
# Create the ECS cluster if it doesn't exist
aws ecs create-cluster --cluster-name zalo-phake

# Create the ECS service
aws ecs create-service \
  --cluster zalo-phake \
  --service-name notification-consumer \
  --task-definition zalo-phake-notification-consumer:1 \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxxxxxx,subnet-yyyyyyyy],securityGroups=[sg-zzzzzzzz],assignPublicIp=ENABLED}"
```

## Monitoring

The Notification Consumer Service outputs structured logs to CloudWatch Logs, which can be used for monitoring and alerting. Set up CloudWatch Alarms for:

1. Dead Letter Queue message count > 0
2. Task health checks failing
3. High CPU or memory utilization

## Scaling

The Notification Consumer Service can be scaled horizontally by adjusting the `desired-count` parameter of the ECS service. It's recommended to set up auto-scaling based on SQS queue depth:

```bash
# Set up auto-scaling
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/zalo-phake/notification-consumer \
  --min-capacity 1 \
  --max-capacity 5

# Create scaling policy based on SQS queue depth
aws application-autoscaling put-scaling-policy \
  --policy-name sqs-scaling-policy \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/zalo-phake/notification-consumer \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration file://scaling-policy.json
```

Where `scaling-policy.json` contains:

```json
{
  "TargetValue": 10.0,
  "CustomizedMetricSpecification": {
    "MetricName": "ApproximateNumberOfMessagesVisible",
    "Namespace": "AWS/SQS",
    "Dimensions": [
      {
        "Name": "QueueName",
        "Value": "zalo-phake-notifications"
      }
    ],
    "Statistic": "Average",
    "Unit": "Count"
  },
  "ScaleOutCooldown": 60,
  "ScaleInCooldown": 600
}
```

## Troubleshooting

1. **Service not starting**: Check ECS service events and task logs in CloudWatch Logs
2. **Messages not being processed**: Verify SQS queue permissions and check for messages in the DLQ
3. **FCM notifications not delivered**: Check Firebase service account permissions and device token validity
4. **High failure rate**: Analyze CloudWatch Logs for error patterns and adjust retry settings if necessary

## Additional Resources

- [AWS ECS Documentation](https://docs.aws.amazon.com/ecs/latest/developerguide/Welcome.html)
- [Firebase Admin SDK Documentation](https://firebase.google.com/docs/admin/setup)
- [AWS SQS Documentation](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html)