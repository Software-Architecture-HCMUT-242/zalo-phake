# WebSocket Architecture for High Availability

## Overview

The WebSocket system is designed for high availability across multiple API instances using Redis/Amazon ElastiCache as the communication backbone. This architecture ensures that messages are delivered to users regardless of which API instance they are connected to.

## Key Components

1. **WebSocket Manager**: Handles WebSocket connections, messaging, and state management
2. **Redis PubSub**: Handles cross-instance communication for real-time events
3. **Connection Registry**: Tracks active connections across all instances
4. **REST API Endpoints**: Provides HTTP alternatives for WebSocket operations
5. **Health Monitoring**: Ensures system reliability and helps with load balancing

## Connection Flow

1. When a user connects via WebSocket:
   - The connection is accepted and registered locally on the API instance
   - Connection information is stored in Redis with instance ID, expiration time, and metadata
   - User status is updated to "online" in Firestore
   - The instance subscribes to Redis channels for the user and their conversations

2. When a user disconnects:
   - The local connection is removed
   - Connection info is removed from Redis
   - The system checks if the user has any other active connections across all instances
   - If no connections remain, a grace period timer starts
   - After the grace period (if no reconnection), user status is updated to "offline"

## Message Distribution Flow

1. When a message needs to be broadcast (typing indicator, message read receipt, etc.):
   - The API instance publishes the event to the appropriate Redis channel
   - Redis distributes the message to all subscribed instances
   - Each instance delivers the message to local WebSocket connections

2. Message delivery optimization:
   - Direct local delivery happens first (on the same instance)
   - Redis PubSub delivers to other instances in parallel
   - Instances filter messages to prevent echo or duplicate delivery

## Fault Tolerance

1. **Instance Failure**:
   - Redis connection registry tracks all connections across instances
   - TTL (Time To Live) on connection entries ensures cleanup of dead connections
   - Connections automatically reconnect and rebalance across healthy instances

2. **Redis Failure**:
   - Local WebSocket functionality continues to work (degraded mode)
   - Health check endpoint reports "degraded" status to alert monitoring systems
   - System auto-recovers when Redis becomes available again

## API Endpoints

The system provides REST API alternatives to WebSocket operations:

1. **POST /api/user/status** - Update user status
2. **POST /api/messages/read** - Mark messages as read
3. **POST /api/conversations/{conversation_id}/typing** - Send typing indicators
4. **GET /api/connections/info** - Get connection information for current user
5. **GET /api/connections/stats** - Get global connection statistics (admin only)
6. **GET /api/health** - System health check for load balancers

## Security

1. All API endpoints require authentication using the existing auth middleware
2. WebSocket connections validate user IDs against tokens
3. Conversation participation is verified before allowing operations
4. Admin-only endpoints have additional authorization checks

## Performance Considerations

1. **Connection Pooling**:
   - Redis connections are pooled to prevent resource exhaustion
   - WebSocket connections are distributed across instances by the load balancer

2. **Message Delivery**:
   - Local delivery is prioritized (optimization to avoid round-trip)
   - Cross-instance delivery happens via Redis PubSub
   - Messages include instance ID to prevent echo effects

3. **Scaling**:
   - The system scales horizontally by adding more API instances
   - Redis can be scaled independently based on message volume
   - Connection count per instance should be monitored and balanced

## Monitoring

1. **Health Checks**:
   - Each instance exposes a health endpoint (/api/health)
   - The health check verifies Redis and Firestore connectivity
   - Instance connection counts are reported for load balancing decisions

2. **Metrics**:
   - Connection counts (global and per-instance)
   - Message delivery statistics
   - Redis PubSub queue sizes
   - Error rates for connection and message handling

## Load Balancer Configuration

1. **Health Checks**:
   - Route: GET /api/health
   - Success criteria: 200 OK response with "status": "healthy" or "degraded"
   - Failure threshold: 3 consecutive failures
   - Interval: 30 seconds

2. **Session Stickiness**:
   - Not required due to cross-instance message delivery
   - Can be enabled for performance optimization if desired

3. **Timeouts**:
   - Connection timeout: 10 seconds
   - Read/Write timeout: 60 seconds
   - Keepalive timeout: 60 seconds