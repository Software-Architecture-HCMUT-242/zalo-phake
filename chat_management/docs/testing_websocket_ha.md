# Testing WebSocket High Availability 

This guide outlines the testing procedures for verifying the WebSocket High Availability implementation.

## Prerequisites

1. **Multiple API Instances**:
   - At least 2 instances running on different ports
   - Configure each with a unique `INSTANCE_ID` environment variable

2. **Redis**:
   - Local Redis server or ElastiCache (for production)
   - Redis CLI for monitoring

3. **Test Users**:
   - Multiple test user accounts

## Test Scenarios

### 1. Basic WebSocket Connection

**Objective**: Verify WebSocket connections can be established and are registered in Redis

**Steps**:
1. Connect a user to instance A
2. Verify connection in Redis using:
   ```
   HGETALL connections:{user_id}
   ```
3. Check the subscription is registered:
   ```
   SMEMBERS subscriptions:{instance_id}
   ```

**Expected Result**:
- Connection and subscription info should be present in Redis
- User should be marked as online in Firestore

### 2. Cross-Instance Message Delivery

**Objective**: Verify messages sent on one instance are delivered to users connected to other instances

**Steps**:
1. Connect User A to Instance A
2. Connect User B to Instance B
3. User A sends a message to a conversation with User B
4. Monitor Redis PubSub activity:
   ```
   MONITOR
   ```

**Expected Result**:
- Message should be published to Redis
- User B should receive the message on Instance B
- Message should be stored in Firestore

### 3. Read Receipt Propagation

**Objective**: Verify read receipts propagate across instances

**Steps**:
1. Connect User A to Instance A
2. Connect User B to Instance B
3. User A sends a message
4. User B marks the message as read via WebSocket or API
5. Check if User A receives the read receipt notification

**Expected Result**:
- Read receipt should be published to Redis
- User A should receive the read receipt notification
- Message "readBy" field should be updated in Firestore

### 4. Typing Indicator

**Objective**: Verify typing indicators work across instances

**Steps**:
1. Connect User A to Instance A
2. Connect User B to Instance B
3. User A sends a typing event
4. Check if User B receives the typing notification

**Expected Result**:
- Typing event should be published to Redis
- User B should receive the typing notification

### 5. Instance Failure Resilience

**Objective**: Verify users can reconnect to other instances if one fails

**Steps**:
1. Connect User A to Instance A
2. Shutdown Instance A
3. User A reconnects (should connect to Instance B)
4. Verify User A is still marked as online
5. Test sending and receiving messages

**Expected Result**:
- User should be able to reconnect to another instance
- Redis should show the new connection in a different instance
- Messages and notifications should continue to work

### 6. Redis Failure Resilience

**Objective**: Verify the system continues to work in degraded mode if Redis fails

**Steps**:
1. Connect User A and User B to the same instance
2. Shutdown Redis
3. User A sends a message
4. Check the health endpoint status

**Expected Result**:
- Message should be delivered to User B directly (same instance)
- Health endpoint should report Redis as disconnected with "degraded" status
- System should attempt to reconnect to Redis

### 7. Offline Notification Filtering

**Objective**: Verify offline notifications are only sent to truly offline users

**Steps**:
1. Connect User A to any instance
2. Keep User B disconnected
3. User A sends a message to a conversation with both users
4. Monitor offline notification processing logs

**Expected Result**:
- User B should receive an offline notification
- User A should not receive an offline notification
- Logs should show User A was filtered out due to active connection

### 8. Multiple Connections Per User

**Objective**: Verify users can have multiple active connections across instances

**Steps**:
1. Connect User A to Instance A using Client 1
2. Connect User A to Instance B using Client 2
3. Send a message to User A from another user
4. Disconnect one of User A's clients

**Expected Result**:
- Both clients should receive the message
- Redis should show connections on both instances
- After disconnecting one client, user should still be shown as online
- Only after all connections are closed should the user be marked offline (after grace period)

### 9. API Endpoint Testing

**Objective**: Verify REST API endpoints work as alternatives to WebSocket events

**Steps**:
1. Test `POST /{conversation_id}/typing` endpoint
2. Test `POST /{conversation_id}/messages/{message_id}/read` endpoint
3. Verify the events are published to Redis
4. Verify WebSocket clients receive the notifications

**Expected Result**:
- API endpoints should return 200 OK responses
- Redis should show published events
- WebSocket clients should receive notifications

### 10. Health Endpoint Testing

**Objective**: Verify health endpoint reports accurate status

**Steps**:
1. Call `/api/health` when all services are working
2. Shutdown Redis and call the endpoint again
3. Restart Redis and verify status returns to healthy

**Expected Result**:
- Initial response should show "healthy" status
- After Redis shutdown, response should show "degraded" status with Redis service error
- After Redis restart, status should return to "healthy"

### 11. Load Testing

**Objective**: Verify system performance under load

**Steps**:
1. Connect multiple users across multiple instances (100+ if possible)
2. Generate high message volume 
3. Monitor Redis memory and CPU usage
4. Check message delivery latency

**Expected Result**:
- All messages should be delivered
- System should remain stable
- Latency should stay within acceptable limits

## Troubleshooting

### Common Issues

1. **Subscriber Timeouts**:
   - Check Redis max clients setting
   - Verify connection pool configuration

2. **Message Delivery Failures**:
   - Check Redis PubSub logs
   - Verify channel names match exactly
   - Check instance ID in environment variables

3. **High Latency**:
   - Check Redis CPU usage
   - Monitor network traffic
   - Consider Redis clustering for better scalability

4. **Connection Tracking Issues**:
   - Verify TTL settings for Redis keys
   - Check connection registration in transaction

## Monitoring Commands

### Redis Monitoring

```bash
# Monitor all Redis commands
redis-cli MONITOR

# Check active subscriptions
redis-cli PUBSUB CHANNELS

# Check memory usage
redis-cli INFO memory

# Check active connections for a user
redis-cli HGETALL connections:user123

# Check instance subscriptions
redis-cli SMEMBERS subscriptions:instance-1
```

### Application Monitoring

```bash
# Get connection statistics
curl -X GET http://localhost:8000/api/connections/stats

# Check system health
curl -X GET http://localhost:8000/api/health

# Check user connection info
curl -X GET http://localhost:8000/api/connections/info
```

## Conclusion

This testing procedure ensures that the WebSocket High Availability implementation is working correctly. By testing all these scenarios, we can be confident that the system will handle real-world usage, including high load and component failures, while maintaining a good user experience.
