# WebSocket Flow Updates

## Overview
This update enhances the WebSocket management system to improve real-time features, including:

1. Improved read receipt functionality with database persistence
2. New user activity tracking system
3. Status change notifications across devices
4. REST API endpoints for WebSocket-related operations
5. Better error handling and logging

## Key Changes

### Enhanced Read Receipt Functionality
- Now uses Firestore transactions to ensure data consistency
- Persists read status to database before broadcasting
- Only broadcasts if the message wasn't already marked as read by the user
- Improved error handling with fallback broadcasting

### New User Activity System
- Added `handle_user_activity` method to track and broadcast user activities
- Uses `asyncio.to_thread` for database operations to avoid blocking the event loop
- Supports generic activity tracking with customizable metadata
- Special handling for status changes to broadcast to relevant conversations

### Status Management
- Added WebSocket status change event handling
- Created REST API endpoint for updating status (`POST /api/user/status`)
- Implemented status validation with clear error messages
- Status changes are persisted to the database and broadcast in real-time

### Connection Information API
- Added endpoint to retrieve current connection information (`GET /api/connections/info`)
- Returns details about user's active connections and overall system state
- Useful for debugging and monitoring

### Code Quality Improvements
- Added comprehensive docstrings with parameter descriptions
- Improved separation of concerns (validation, DB operations, notifications)
- Enhanced error logging with specific error messages
- Consistent use of async/await patterns for all IO operations
- Transaction support for critical database updates

## Updated Flow Diagram
The WebSocket flow diagram (`web_socket_flow.puml`) has been updated to reflect the new processes and interactions, including:
- Connection setup
- Heartbeat mechanism
- Status change flow (via both WebSocket and REST API)
- Read receipt flow with database updates
- Graceful disconnection handling

## Testing Considerations
- The implementation is testable with existing tools
- Input validation is performed before database operations
- Error handling includes specific error messages for easier debugging
- Transactions are used for critical database updates to ensure consistency
