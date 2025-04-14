# Redis to AWS Elastic Solution Chat Management Service Migration

## Overview

This document outlines the changes made to replace Redis functionality with the AWS Elastic Solution's chat_management service in the codebase.

## Key Files Modified

1. **WebSocket Manager (`app/ws/websocket_manager.py`)**
   - Updated to integrate with chat_management service for connection tracking
   - Modified broadcast methods to use chat_management's publish functionality
   - Added methods to handle conversation membership tracking

2. **WebSocket Router (`app/ws/router.py`)**
   - Updated to use chat_management service for connection information
   - Added additional connection statistics from chat_management service

3. **Main Application (`app/main.py`)**
   - Changed Redis PubSub listener import to chat_management service PubSub listener
   - Updated startup event to initialize the chat_management service

4. **Conversations Module (`app/conversations/messages.py`)**
   - Updated message sending, read receipts, and typing indicators to use chat_management service
   - Implemented fallback mechanisms when chat_management service is unavailable
   - Updated offline notification processing to check user connection status with chat_management service

5. **WebSocket API Endpoints (`app/ws/api_endpoints.py`)**
   - Updated connection information retrieval to use chat_management service
   - Modified health check endpoint to verify chat_management service connectivity
   - Changed connection statistics gathering to use the new service

## New Files Created

1. **Chat Management Client (`app/aws/elasticache/client.py`)**
   - Implements the AWS Elastic Solution's chat_management service API
   - Provides methods for publishing messages, tracking connections, and managing subscriptions
   - Designed as a drop-in replacement for Redis functionality

2. **Chat Management PubSub (`app/aws/elasticache/pubsub.py`)**
   - Implements message distribution across service instances
   - Handles various event types (new messages, typing indicators, read receipts, status changes)
   - Maintains compatibility with existing event handlers

3. **Module Initialization (`app/aws/elasticache/__init__.py`)**
   - Exports the chat_management_client singleton

## Functionality Changes

### Connection Management
- Replaced Redis-based connection tracking with AWS DynamoDB-based tracking
- Added instance-aware connection management to support high availability
- Enhanced connection metadata to include timestamps and instance information

### Message Distribution
- Changed from Redis PubSub channels to DynamoDB-based message distribution
- Added polling mechanism for messages (simulated; in production, would use more efficient streaming)
- Maintained the same event structure for backward compatibility

### User Conversation Tracking
- Moved from Redis sets to DynamoDB tables for tracking which conversations a user is part of
- Enhanced caching with multiple layers (local in-memory, chat_management service, Firestore)
- Improved error handling for conversation tracking

### Status Handling
- Updated user status broadcasting to use chat_management service
- Maintained offline grace period functionality
- Enhanced status change visibility across instances

## Configuration Requirements

The AWS Elastic Solution's chat_management service requires the following environment variables:

- `AWS_REGION` - The AWS region where the service is deployed
- `AWS_ACCESS_KEY_ID` - AWS access key for authentication
- `AWS_SECRET_ACCESS_KEY` - AWS secret key for authentication
- `INSTANCE_ID` - Unique identifier for this service instance (defaults to hostname if not provided)
- `CHAT_MANAGEMENT_ENDPOINT` - Optional endpoint for the chat_management service (for custom deployments)

## Testing Considerations

1. **Connection Handling**
   - Test WebSocket connections across multiple service instances
   - Verify connections are tracked correctly in the chat_management service
   - Ensure disconnections are properly cleaned up

2. **Message Distribution**
   - Test message broadcasting to ensure all connected clients receive messages
   - Verify cross-instance message distribution works correctly
   - Test with various message types (text, images, etc.)

3. **Status Broadcasting**
   - Verify user status changes are visible across all instances
   - Test the offline grace period functionality
   - Ensure status is correctly preserved in Firestore

4. **Error Handling**
   - Test resilience when the chat_management service is temporarily unavailable
   - Verify proper error logging and retry mechanisms
   - Ensure client connections remain stable during service disruptions

## Migration Notes

1. The implementation maintains backward compatibility with the existing API structure.
2. No schema changes were required in Firestore or other external systems.
3. Error handling has been enhanced with better logging and retry mechanisms.
4. The chat_management service client includes connection pooling and reconnection logic.
5. All async/await patterns have been maintained for consistency.
