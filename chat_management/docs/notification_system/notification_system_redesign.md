# Notification System Redesign

## 1. Overview

This document outlines a redesigned notification system for the Zalo-Phake chat application. The new system addresses the limitations of the current implementation while providing a more scalable, reliable, and maintainable architecture for delivering real-time notifications to users.

## 2. Architecture Overview

The new notification system uses a decoupled, event-driven architecture with the following components:

1. **Event Publishers** - Service components that emit notification events
2. **Message Queue (AWS SQS)** - Reliable, scalable message broker
3. **Notification Consumer Service** - Dedicated microservice for processing notifications
4. **Push Notification Service** - Abstracted service for delivering notifications via Firebase Cloud Messaging
5. **Notification Storage** - Database layer for persisting notification history
6. **API Layer** - RESTful endpoints for notification management

## 3. System Components

### 3.1 Event Publishers

Multiple services can publish notification events:
- **Chat Service** - Emits new message events
- **Group Service** - Emits group invitation events
- **User Service** - Emits friend request events

Events are standardized with a common format to ensure consistency.

### 3.2 Message Queue (AWS SQS)

- **Main Notification Queue** - Handles all notification events
- **Dead Letter Queue (DLQ)** - Captures failed notification processing attempts
- **Retry Queue** - Managed by the consumer service for controlled retries with backoff

### 3.3 Notification Consumer Service

A dedicated microservice with the following responsibilities:
- Consuming notification events from SQS
- Applying business logic and notification rules
- Managing user preferences and delivery channels
- Batching notifications for efficiency
- Implementing retry logic with exponential backoff
- Tracking delivery status

### 3.4 Push Notification Service

An abstracted service that handles:
- Device token management and rotation
- Cross-platform delivery (iOS, Android, Web)
- Batched delivery to FCM for efficiency
- Token validation and cleanup

### 3.5 Notification Storage

- **Notifications Table** - Stores notification history and status
- **User Preferences** - Stores user notification settings
- **Device Tokens** - Manages user device registration

### 3.6 API Layer

RESTful endpoints for:
- Retrieving notifications with pagination and filtering
- Managing notification preferences
- Registering and managing device tokens
- Marking notifications as read/unread

## 4. Event Format

All notification events follow a standardized format:

```json
{
  "eventId": "uuid-string",
  "eventType": "NEW_MESSAGE|GROUP_INVITATION|FRIEND_REQUEST|etc",
  "timestamp": "ISO8601-datetime",
  "publisher": "service-name",
  "version": "1.0",
  "payload": {
    // Event-specific data
  },
  "recipients": [
    {
      "userId": "user-id",
      "deliveryChannels": ["PUSH", "IN_APP", "EMAIL"]
    }
  ]
}
```

## 5. Notification Flows

See the accompanying PlantUML diagrams in the `/diagrams` directory for detailed flow visualizations:

- `new_message_flow.puml` - New message notification flow
- `group_invitation_flow.puml` - Group invitation notification flow
- `friend_request_flow.puml` - Friend request notification flow
- `error_handling_flow.puml` - Error handling and retry flow
- `token_management_flow.puml` - Device token management flow
- `deployment_architecture.puml` - Overall system architecture

## 7. Technical Implementation

### 7.1 SQS Configuration

```yaml
NotificationQueue:
  Type: AWS::SQS::Queue
  Properties:
    QueueName: zalo-phake-notifications
    VisibilityTimeout: 60
    MessageRetentionPeriod: 345600  # 4 days
    RedrivePolicy:
      deadLetterTargetArn: !GetAtt NotificationDLQ.Arn
      maxReceiveCount: 5

NotificationDLQ:
  Type: AWS::SQS::Queue
  Properties:
    QueueName: zalo-phake-notifications-dlq
    MessageRetentionPeriod: 1209600  # 14 days

RetryQueue:
  Type: AWS::SQS::Queue
  Properties:
    QueueName: zalo-phake-notifications-retry
    VisibilityTimeout: 120
    MessageRetentionPeriod: 86400  # 1 day
    DelaySeconds: 60  # Initial delay before messages become visible
```

### 7.2 Notification Consumer Service

The Notification Consumer Service will be implemented as a standalone microservice with the following components:

1. **Queue Listener** - Continuously polls SQS for new messages
2. **Event Processor** - Parses and validates notification events
3. **User Preference Manager** - Retrieves and applies user notification settings
4. **Notification Router** - Determines appropriate delivery channels
5. **Retry Manager** - Implements exponential backoff and retry logic
6. **Status Tracker** - Monitors and records notification delivery status

#### Main Processing Logic:

```python
def process_notification_event(event):
    # Parse and validate event
    validated_event = validate_event(event)
    
    # Process each recipient
    for recipient in validated_event.recipients:
        # Check user preferences
        preferences = get_user_preferences(recipient.userId)
        
        # Apply notification rules
        if should_send_notification(validated_event, recipient, preferences):
            # Store notification
            notification_id = store_notification(validated_event, recipient)
            
            # Determine delivery channels
            channels = determine_delivery_channels(validated_event, recipient, preferences)
            
            # Send through each channel
            for channel in channels:
                try:
                    if channel == "PUSH":
                        delivery_status = push_notification_service.send(
                            recipient.userId,
                            build_push_payload(validated_event)
                        )
                    # Handle other channels...
                    
                    update_notification_status(notification_id, channel, "DELIVERED")
                except TransientError as e:
                    # Handle temporary errors with retry
                    update_notification_status(notification_id, channel, "RETRYING")
                    send_to_retry_queue(event, delay_seconds=calculate_backoff(attempt))
                except PermanentError as e:
                    # Handle permanent errors
                    update_notification_status(notification_id, channel, "FAILED")
                    log_delivery_failure(notification_id, channel, str(e))
```

### 7.3 Push Notification Service

The Push Notification Service will be implemented with the following features:

1. **Platform-Specific Formatting** - Tailored payload formatting for iOS, Android, and Web
2. **Token Management** - Efficient storage and retrieval of device tokens
3. **Batch Processing** - Grouping notifications to the same user/device for efficiency
4. **Delivery Tracking** - Recording successful and failed deliveries
5. **Token Validation** - Regular cleanup of invalid tokens

#### FCM Integration:

```python
class PushNotificationService:
    def __init__(self, firebase_credentials):
        self.firebase_app = initialize_firebase(firebase_credentials)
        self.token_service = DeviceTokenService()
        
    def send(self, user_id, payload):
        # Get user's device tokens
        tokens = self.token_service.get_tokens_for_user(user_id)
        
        if not tokens:
            return {"status": "SKIPPED", "reason": "NO_TOKENS"}
            
        # Group tokens by platform for platform-specific formatting
        tokens_by_platform = group_tokens_by_platform(tokens)
        
        results = {}
        
        # Send to each platform with appropriate formatting
        for platform, platform_tokens in tokens_by_platform.items():
            # Format payload for platform
            formatted_payload = format_for_platform(platform, payload)
            
            # Batch tokens (FCM allows up to 500 per request)
            batched_tokens = batch_tokens(platform_tokens, batch_size=500)
            
            for batch in batched_tokens:
                try:
                    # Send batch to FCM
                    response = messaging.send_multicast(
                        MulticastMessage(
                            tokens=batch,
                            notification=formatted_payload.notification,
                            data=formatted_payload.data
                        )
                    )
                    
                    # Process batch results
                    self._process_batch_results(user_id, batch, response)
                    results[platform] = {"status": "SUCCESS", "count": len(batch)}
                    
                except FirebaseError as e:
                    results[platform] = {"status": "ERROR", "error": str(e)}
                    
        return results
        
    def _process_batch_results(self, user_id, tokens, response):
        # Process successful and failed deliveries
        for idx, result in enumerate(response.responses):
            if not result.success:
                # Handle specific error codes
                if result.exception.code in FCM_INVALID_TOKEN_CODES:
                    # Remove invalid token
                    self.token_service.invalidate_token(tokens[idx])
```

## 9. Key Improvements Over Current Design

### 9.1 Scalability
- Decoupled components that can scale independently
- Efficient batch processing for FCM
- Token management optimized for large user bases

### 9.2 Reliability
- Comprehensive retry strategy with exponential backoff
- Dead letter queue for failed notifications
- Transaction-based status updates

### 9.3 Maintainability
- Clear separation of concerns
- Standardized event format
- Dedicated services for specific responsibilities

### 9.4 Observability
- Detailed delivery status tracking
- Metrics collection at each processing stage
- Structured logging for debugging

### 9.5 Security
- Improved token validation and rotation
- Permission-based notification filtering
- Rate limiting for notification senders

## 10. Implementation Plan

### Phase 1: Core Infrastructure
1. Set up SQS queues (main, retry, DLQ)
2. Implement Notification Consumer Service
3. Implement Push Notification Service
4. Create notification storage tables

### Phase 2: Event Publishers
1. Update Chat Service to publish standardized events
2. Update Group Service to publish standardized events
3. Update User Service to publish standardized events

### Phase 3: API and Management
1. Implement notification management API
2. Implement device token management API
3. Implement user preference management API

### Phase 4: Monitoring and Optimization
1. Set up monitoring and alerting
2. Implement delivery metrics collection
3. Optimize batch processing and caching

## 11. Conclusion

This redesigned notification system addresses the limitations of the current implementation while providing a scalable, reliable foundation for delivering timely notifications to users. The event-driven architecture allows for easy extension to new notification types and delivery channels as the application evolves.

The decoupled components enable independent scaling and development, while the standardized event format ensures consistency across different notification types. The comprehensive retry strategy and dedicated consumer service improve reliability, and the detailed status tracking enhances observability.
