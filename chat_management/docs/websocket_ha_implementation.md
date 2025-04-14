# WebSocket High Availability Implementation

This document provides an overview of the WebSocket high availability implementation for the chat application. The system allows WebSocket connections across multiple API instances to work together, providing fault tolerance and scalability.

## Key Files and Components

### 1. WebSocket Manager (`app/ws/websocket_manager.py`)
- Enhanced to support cross-instance awareness
- Uses Redis for connection tracking and PubSub
- Handles message broadcasting across instances
- Manages user status and activity tracking

### 2. WebSocket Router (`app/ws/router.py`)
- Manages WebSocket connections and message handling
- Implements participant validation for security
- Adds structured error responses
- Properly handles disconnection cleanup

### 3. API Endpoints (`app/ws/api_endpoints.py`)
- Provides HTTP alternatives to WebSocket operations
- Implements secure user status updates
- Handles read receipts and typing notifications
- Adds connection information and health monitoring

### 4. Redis Connection (`app/redis/connection.py`)
- Provides a connection pool for Redis operations
- Configurable via environment variables
- Handles connection errors gracefully

### 5. Redis PubSub (`app/redis/pubsub.py`)
- Implements the Redis PubSub listener
- Handles cross-instance message distribution
- Provides fault tolerance with retries
- Maps events to appropriate handlers

### 6. Main Application (`app/main.py`)
- Initializes background tasks for PubSub
- Sets up health check monitoring
- Registers all API routes

## Error Handling

The implementation includes robust error handling:

- **400 Bad Request**: For invalid data formats or missing parameters
- **401 Unauthorized**: For authentication failures (via dependency injection)
- **403 Forbidden**: When users try to access conversations they're not a part of
- **404 Not Found**: For non-existent resources
- **500 Internal Server Error**: For database or other unexpected errors

All errors include detailed error messages and appropriate status codes.

## Implementation Features

### 1. Connection Management
- Each connection has a unique ID
- Connection data is stored in Redis with metadata
- Connections are tracked across instances
- Grace period handling for reconnections

### 2. Message Delivery
- Messages are published to Redis channels
- Each instance has a PubSub listener
- Local connections receive messages directly 
- Remote connections receive via Redis PubSub

### 3. Status Tracking
- User status is stored in Firestore
- Status changes broadcast to all relevant conversations
- Online/offline status handled with a grace period
- Status handled via both WebSocket and HTTP APIs

### 4. Security
- User authentication required for all operations
- Conversation participation validated for each action
- Admin-only endpoints have role-based access control
- Input validation for all parameters

### 5. Health Monitoring
- Health check endpoint for load balancers
- Service-level health reporting (Redis, Firestore)
- Connection statistics for monitoring
- Degraded mode operation when components fail

## Testing Considerations

The implementation is designed for testability:

1. **Unit Testing**:
   - Each component can be tested in isolation
   - Redis and Firestore operations can be mocked
   - WebSocket functionality can be tested with mock clients

2. **Integration Testing**:
   - Multi-instance setup can be tested locally with Docker
   - Redis PubSub can be verified with test channels
   - Connection tracking can be tested with simulated connections

3. **Load Testing**:
   - Connection handling under load should be tested
   - Message delivery latency should be measured
   - Redis performance should be monitored

## Deployment Notes

1. **Instance Identification**:
   - Each instance needs a unique ID (via environment variable)
   - In AWS, this can be the EC2 instance ID or container ID

2. **Redis Configuration**:
   - Redis needs to be accessible from all API instances
   - For AWS, ElastiCache in cluster mode is recommended
   - Enable automatic failover for high availability

3. **Load Balancing**:
   - Load balancer must support WebSockets
   - Health check should use the `/api/health` endpoint
   - Session stickiness is optional but may improve performance

## Environment Variables

```
INSTANCE_ID=unique-instance-id  # Required for instance identification
REDIS_HOST=localhost  # Redis host (default: localhost)
REDIS_PORT=6379       # Redis port (default: 6379)
REDIS_PASSWORD=       # Redis password (if required)
REDIS_SSL=false       # Whether to use SSL for Redis (default: false)
REDIS_DB=0            # Redis database index (default: 0)
```