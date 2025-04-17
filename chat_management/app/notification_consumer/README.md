# Notification Consumer Service

This service is part of the redesigned notification system for the Zalo-Phake chat application. It replaces the previous AWS Lambda-based approach with a dedicated microservice following event-driven architecture principles.

## Architecture Overview

The notification system follows a decoupled, event-driven architecture with these components:

1. **Event Publishers** - Service components that emit notification events (in the conversations module)
2. **Message Queue (AWS SQS)** - Reliable, scalable message broker
3. **Notification Consumer Service** - This service, which processes notifications from the queue
4. **Push Notification Service** - Abstracted service for delivering notifications via FCM/SNS
5. **Notification Storage** - Persistent storage for notification history in Firestore

## Notification Flow

1. When events occur in the application (new messages, group invitations, friend requests, etc.), 
   the relevant services publish standardized events to SQS using the utilities in `app/aws/sqs_utils.py`.
2. This Notification Consumer Service polls the SQS queue and processes these events.
3. For each event, the service:
   - Validates the event data
   - Checks user notification preferences
   - Sends push notifications via FCM (for iOS/Android) or SNS (for web) if appropriate
   - Stores notification records in Firestore
   - Updates unread notification counts
4. The service implements robust error handling with:
   - Exponential backoff for temporary failures
   - Dead Letter Queue (DLQ) for permanent failures
   - Idempotent processing to handle potential duplicates

## Running Locally

To run the service locally:

```bash
# From project root
python -m app.notification_consumer.main
```

Make sure you have the necessary environment variables set:
- AWS credentials
- SQS_URL
- FIREBASE_SECRET
- SNS_TOPIC_ARN (for web push notifications)

## Deployment

The service is deployed as a standalone ECS task using the task definition in `deployments/notification-consumer-task-definition.json`.

## Event Types

The service handles the following event types:

1. `new_message` - When a new chat message is sent
2. `group_invitation` - When a user is invited to a group
3. `friend_request` - When a user receives a friend request
4. `direct_conversation_created` - When a new direct conversation is created
5. `group_conversation_created` - When a new group conversation is created

## Error Handling

The service implements several mechanisms for handling errors:

1. **Retry Queue** - Failed messages are sent to a retry queue with exponential backoff
2. **Dead Letter Queue (DLQ)** - Messages that fail repeatedly are sent to a DLQ
3. **Transaction-based Status Updates** - Ensuring consistent notification state in Firestore
4. **Invalid Token Cleanup** - Automatically removes invalid device tokens

## Logging and Monitoring

The service uses structured logging to provide visibility into its operation. Key metrics to monitor:

- Messages processed per minute
- Processing success rate
- Notification delivery success rate
- Invalid token rate
- DLQ message count

## Further Reading

See the design document at `docs/notification_system/notification_system_redesign.md` for more details on the architecture and design decisions.
