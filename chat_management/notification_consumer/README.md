# Notification Consumer Service

A standalone microservice for processing notification events from SQS and delivering push notifications via Firebase Cloud Messaging (FCM).

## Overview

The Notification Consumer Service is part of the redesigned notification system for the Zalo-Phake chat application. It consumes notification events from an AWS SQS queue, processes them according to business rules, and delivers push notifications to users via Firebase Cloud Messaging.

## Features

- Processes multiple notification types:
  - New message notifications
  - Group invitation notifications
  - Friend request notifications
- Implements robust error handling with exponential backoff retry logic
- Supports dead-letter queue (DLQ) for failed notifications
- Manages device token validation and cleanup
- Applies user notification preferences
- Efficient batch processing for FCM

## Architecture

The service follows a clean, modular architecture:

- `main.py` - Entry point and main processing loop
- `config.py` - Configuration settings
- `sqs_client.py` - AWS SQS client for message queue operations
- `firebase_client.py` - Firebase client for Firestore and FCM operations
- `event_processor.py` - Core event processing logic

## Requirements

- Python 3.9+
- AWS account with SQS queues configured
- Firebase project with Cloud Messaging enabled
- Firebase service account credentials

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

The service is configured via environment variables:

```bash
# Required environment variables
export AWS_ACCESS_KEY_ID=your_aws_access_key
export AWS_SECRET_ACCESS_KEY=your_aws_secret_key
export MAIN_QUEUE_URL=https://sqs.region.amazonaws.com/account-id/queue-name
export RETRY_QUEUE_URL=https://sqs.region.amazonaws.com/account-id/retry-queue-name
export DLQ_URL=https://sqs.region.amazonaws.com/account-id/dlq-name
export FIREBASE_SECRET='{"type":"service_account",...}'  # Firebase service account JSON

# Optional environment variables
export ENVIRONMENT=dev  # dev, staging, prod
export LOG_LEVEL=INFO   # DEBUG, INFO, WARNING, ERROR
export SERVICE_NAME=notification-consumer
```

## Running Locally

```bash
python main.py
```

## Running with Docker

```bash
# Build the Docker image
docker build -t notification-consumer .

# Run the container
docker run -d \
  --name notification-consumer \
  -e AWS_ACCESS_KEY_ID=your_aws_access_key \
  -e AWS_SECRET_ACCESS_KEY=your_aws_secret_key \
  -e MAIN_QUEUE_URL=https://sqs.region.amazonaws.com/account-id/queue-name \
  -e RETRY_QUEUE_URL=https://sqs.region.amazonaws.com/account-id/retry-queue-name \
  -e DLQ_URL=https://sqs.region.amazonaws.com/account-id/dlq-name \
  -e FIREBASE_SECRET='{"type":"service_account",...}' \
  notification-consumer
```

## Deployment

See the [deployment documentation](../docs/notification_system/consumer_deployment.md) for detailed instructions on deploying to AWS ECS Fargate.

## Monitoring

The service outputs structured JSON logs that can be collected and analyzed by CloudWatch Logs or other log aggregation services. Key metrics to monitor:

- Messages processed per minute
- Success rate
- Error rate by error type
- DLQ message count
- FCM delivery success rate
- Invalid token count

## Testing

To run unit tests:

```bash
pytest
```

## Related Documentation

- [Notification System Redesign](../docs/notification_system/notification_system_redesign.md)
- [Consumer Deployment Guide](../docs/notification_system/consumer_deployment.md)