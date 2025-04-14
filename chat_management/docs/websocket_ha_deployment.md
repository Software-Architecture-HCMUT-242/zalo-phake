# WebSocket High Availability Deployment Guide

This guide provides instructions for deploying the WebSocket high availability system across multiple instances using Redis/Amazon ElastiCache.

## Prerequisites

- Multiple API instances (EC2, ECS, or Kubernetes pods)
- Redis cluster (Amazon ElastiCache or self-managed Redis)
- Load balancer (ALB, NLB, or similar)
- Firestore database
- Existing authentication system

## Environment Configuration

Each API instance requires the following environment variables:

```
# Instance identification
INSTANCE_ID=unique-instance-id  # e.g., chat-api-1, chat-api-2, etc.

# Redis configuration
REDIS_HOST=your-redis-cluster-endpoint
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password
REDIS_SSL=true
REDIS_DB=0

# Application settings
WS_GRACE_PERIOD=60  # Seconds to wait before marking a user offline
WS_HEARTBEAT_INTERVAL=30  # Seconds between heartbeat checks
```

## Redis Configuration

1. **Cluster Mode**:
   - Enable Redis cluster mode for scalability
   - Configure at least 3 shards with 1 replica each for high availability
   - Enable automatic failover

2. **Memory Settings**:
   - Set `maxmemory` according to expected connection load
   - Use `volatile-lru` eviction policy

3. **Persistence**:
   - Enable AOF persistence with `appendfsync everysec`
   - Configure RDB snapshots as backup

4. **Monitoring**:
   - Enable CloudWatch metrics (if using ElastiCache)
   - Set up alerts for memory usage, CPU, and connection count

## Load Balancer Configuration

1. **Health Check**:
   - Path: `/api/health`
   - Success codes: 200
   - Interval: 30 seconds
   - Timeout: 5 seconds
   - Threshold: 3 consecutive successes/failures

2. **WebSocket Support**:
   - Protocol: HTTP/1.1
   - Connection timeout: 10 seconds
   - Idle timeout: 300 seconds (adjust based on your application's heartbeat)

3. **SSL Configuration**:
   - Terminate SSL at the load balancer
   - Use AWS Certificate Manager or similar for SSL certificates

## Deployment Steps

1. **Database Setup**:
   ```bash
   # Ensure the system collection exists in Firestore
   firebase firestore:set --collection=system --doc=health '{"status": "healthy", "created_at": "TIMESTAMP"}'
   ```

2. **Deploy Redis Cluster**:
   - If using ElastiCache:
     ```bash
     aws elasticache create-replication-group \
       --replication-group-id chat-redis \
       --replication-group-description "Redis cluster for chat" \
       --engine redis \
       --cache-node-type cache.m5.large \
       --num-cache-clusters 3 \
       --automatic-failover-enabled
     ```

3. **Deploy API Instances**:
   - For each instance, set a unique `INSTANCE_ID` environment variable
   - Deploy the application code
   - Start the FastAPI server with uvicorn:
     ```bash
     uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
     ```

4. **Configure Load Balancer**:
   - Create a target group with all API instances
   - Configure the health check as described above
   - Create a load balancer with WebSocket support
   - Configure SSL termination if needed

5. **Verify Deployment**:
   - Test WebSocket connections to multiple instances
   - Verify message delivery across instances
   - Check Redis connectivity with the health check endpoint

## Scaling Considerations

1. **API Instances**:
   - Monitor CPU and memory usage
   - Set up auto-scaling based on connection count or CPU usage
   - Add instances gradually to distribute load

2. **Redis Cluster**:
   - Monitor memory usage and network throughput
   - Scale Redis by adding shards when approaching 70% memory usage
   - Consider separate Redis instances for different channels if needed

## Troubleshooting

1. **Connection Issues**:
   - Check load balancer logs for connection timeouts
   - Verify WebSocket protocols are properly configured
   - Ensure Redis connectivity from all instances

2. **Message Delivery Issues**:
   - Check Redis PubSub logs for errors
   - Verify channel subscriptions
   - Check for serialization/deserialization errors

3. **Performance Issues**:
   - Monitor Redis CPU and memory usage
   - Check API instance connection counts
   - Verify Redis commands per second

## Monitoring

1. **Key Metrics**:
   - Active connections per instance and globally
   - Message delivery rate
   - Redis memory usage and CPU
   - Error rates for WebSocket operations

2. **Logging**:
   - Set up centralized logging with a search interface
   - Implement structured logging for easier filtering
   - Log connection events, errors, and key operations

## Security Considerations

1. **Redis Security**:
   - Use VPC isolation for Redis clusters
   - Enable encryption in transit and at rest
   - Use strong passwords and IAM authentication if available

2. **WebSocket Security**:
   - Implement proper authentication for WebSocket connections
   - Validate user permissions before performing operations
   - Rate limit connection attempts to prevent abuse

3. **API Security**:
   - Use HTTPS for all communications
   - Implement proper authentication and authorization
   - Validate all inputs to prevent injection attacks