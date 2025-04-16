# WebSocket API Documentation

This document outlines how client applications should interact with the WebSocket API endpoint (`/ws/{user_id}`) in the Chat Management service.

## 1. Connection

### Endpoint URL Structure
```
ws://<your-backend-host>:<port>/ws/{user_id}?token=<AUTH_TOKEN>
```

### Connection Parameters
- **user_id**: This parameter in the path corresponds to the authenticated user's identifier. In development mode, this is typically the user's phone number (e.g., `+84912345678`). This identifier is used for server-side identification and management of user connections.
- **token**: Authentication token passed as a query parameter. In production mode, this should be a Firebase ID token. In development mode, this can be the user's phone number.

### Authentication Flow
1. The WebSocket endpoint requires authentication via the `token` query parameter.
2. The server validates this token before accepting the WebSocket connection.
3. The token must match the same format used for Bearer authentication in the REST API.
4. The user ID derived from the token must match the `user_id` in the path.

### Authentication Errors
The WebSocket connection will be rejected with the following close codes:
- **4001**: Unauthorized - Invalid or missing token
- **4002**: User ID mismatch (token user ID doesn't match path user ID)
- **4003**: User account is disabled

## 2. Events Sent by Client

Client applications need to send the following JSON-formatted events over the WebSocket connection:

### Typing Notification
Used to indicate the user is typing in a specific conversation.

```json
{
  "event": "typing",
  "conversationId": "string"
}
```

### Message Read Receipt
Used to mark a specific message within a conversation as read.

```json
{
  "event": "message_read",
  "conversationId": "string",
  "messageId": "string"
}
```

### Heartbeat
Should be sent periodically to keep the connection alive and update the user's last active time.

```json
{
  "event": "heartbeat"
}
```

### Status Change
Used to update the user's presence status.

```json
{
  "event": "status_change",
  "status": "string" // e.g., "available", "away", "busy"
}
```

## 3. Events Received by Client

The server will send the following JSON-formatted events to client applications:

### New Message
Sent when a new message is created in a conversation the user is part of.

```json
{
  "event": "new_message",
  "conversationId": "string",
  "messageId": "string",
  "senderId": "string",
  "content": "string",
  "messageType": "text|image|video|audio",
  "timestamp": "ISO-8601 timestamp"
}
```

### Typing Indicator
Sent when another user is typing in a conversation.

```json
{
  "event": "typing",
  "conversationId": "string",
  "userId": "string"
}
```

### Message Read Receipt
Sent when another user reads a message in a conversation.

```json
{
  "event": "message_read",
  "conversationId": "string",
  "messageId": "string",
  "userId": "string"
}
```

### User Status Change
Sent when a user's status changes.

```json
{
  "event": "user_status_change",
  "userId": "string",
  "status": "string",
  "conversationId": "string" // Optional, included when relevant
}
```

### Heartbeat Acknowledgment
Simple acknowledgment of a heartbeat message.

```json
{
  "event": "heartbeat_ack"
}
```

### Status Change Acknowledgment
Confirmation that a status change was processed.

```json
{
  "event": "status_change_ack",
  "status": "string"
}
```

### Error Message
Sent when an error occurs processing a client request.

```json
{
  "event": "error",
  "message": "string"
}
```

## 4. Postman Testing Guide

### Setting Up a WebSocket Connection in Postman

1. **Create a WebSocket Request:**
   - Open Postman and click on the "New" button
   - Select "WebSocket Request" from the options

2. **Enter the Connection URL with Authentication:**
   - For local development: `ws://localhost:8000/ws/+84912345678?token=+84912345678`
   - For production: `ws://your-host/ws/{user_id}?token={firebase_id_token}`
   - Replace `+84912345678` with a valid test user ID (must be a Vietnamese phone number in development mode)
   - Ensure the token matches the authentication token used in REST API calls
   - In development mode, the token can be the same as the user ID
   - In production, the token must be a valid Firebase ID token
   - Click "Connect" to establish the WebSocket connection

3. **Troubleshoot Connection Issues:**
   - If the connection is rejected, check the WebSocket close code and reason:
     - **4001**: Make sure you're providing a valid token
     - **4002**: Ensure the user ID in the path matches the user ID in the token
     - **4003**: Verify the user account is not disabled

4. **Send a Heartbeat Event:**
   - In the message composer at the bottom, enter the following JSON:
     ```json
     {"event": "heartbeat"}
     ```
   - Click "Send" to transmit the message

5. **Observe the Response:**
   - You should receive a `heartbeat_ack` message in the messages panel
   - The response will look like:
     ```json
     {"event": "heartbeat_ack"}
     ```

6. **Testing Other Events:**
   - To test typing notifications, send:
     ```json
     {"event": "typing", "conversationId": "<valid-conversation-id>"}
     ```
   - To test read receipts, send:
     ```json
     {"event": "message_read", "conversationId": "<valid-conversation-id>", "messageId": "<valid-message-id>"}
     ```
   - To test status changes, send:
     ```json
     {"event": "status_change", "status": "away"}
     ```

## 5. ReactJS Implementation Example

Below is a concise example of integrating WebSocket functionality into a React application:

```jsx
import React, { useState, useEffect, useRef } from 'react';

const ChatComponent = ({ userId, authToken, conversationId }) => {
  const [messages, setMessages] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [typingUsers, setTypingUsers] = useState({});
  const webSocketRef = useRef(null);
  const typingTimeoutRef = useRef(null);

  // Establish WebSocket connection
  useEffect(() => {
    // Create WebSocket connection with authentication token
    const wsUrl = `ws://your-backend-host:port/ws/${userId}?token=${authToken}`;
    const ws = new WebSocket(wsUrl);
    webSocketRef.current = ws;

    // Connection opened
    ws.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      
      // Set up heartbeat interval (every 30 seconds)
      const heartbeatInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ event: 'heartbeat' }));
        }
      }, 30000);
      
      // Return cleanup function
      return () => {
        clearInterval(heartbeatInterval);
      };
    };

    // Handle incoming messages
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      // Handle different event types
      switch (data.event) {
        case 'new_message':
          setMessages((prevMessages) => [...prevMessages, data]);
          break;
        
        case 'typing':
          if (data.conversationId === conversationId) {
            // Set typing indicator for this user
            setTypingUsers((prev) => ({
              ...prev,
              [data.userId]: true
            }));
            
            // Clear typing indicator after 3 seconds of no updates
            const timeoutId = setTimeout(() => {
              setTypingUsers((prev) => {
                const updated = {...prev};
                delete updated[data.userId];
                return updated;
              });
            }, 3000);
            
            // Clear previous timeout if it exists
            if (typingTimeoutRef.current?.[data.userId]) {
              clearTimeout(typingTimeoutRef.current[data.userId]);
            }
            
            // Store the new timeout
            typingTimeoutRef.current = {
              ...typingTimeoutRef.current,
              [data.userId]: timeoutId
            };
          }
          break;
        
        case 'message_read':
          // Update message read status in your UI
          setMessages((prevMessages) => 
            prevMessages.map((msg) => 
              msg.messageId === data.messageId 
                ? { ...msg, readBy: [...(msg.readBy || []), data.userId] }
                : msg
            )
          );
          break;
        
        case 'user_status_change':
          // Handle user status changes in your UI
          console.log(`User ${data.userId} is now ${data.status}`);
          break;
        
        case 'heartbeat_ack':
          // Heartbeat acknowledged - connection is healthy
          console.log('Heartbeat acknowledged');
          break;
        
        case 'error':
          console.error('WebSocket error:', data.message);
          break;
      }
    };

    // Connection closed
    ws.onclose = (event) => {
      console.log('WebSocket disconnected:', event.code, event.reason);
      setIsConnected(false);
      
      // Handle authentication errors
      if (event.code === 4001) {
        console.error('Authentication failed: Invalid or missing token');
        // You might want to redirect to login or refresh the token
      } else if (event.code === 4002) {
        console.error('Authentication failed: User ID mismatch');
        // The user ID in the path doesn't match the one in the token
      } else if (event.code === 4003) {
        console.error('Authentication failed: User account is disabled');
        // Consider logging the user out or showing a notification
      }
      
      // Attempt to reconnect after 5 seconds (if not auth error)
      if (event.code < 4000) {
        setTimeout(() => {
          console.log('Attempting to reconnect...');
          // Clean up old timeouts
          if (typingTimeoutRef.current) {
            Object.values(typingTimeoutRef.current).forEach(clearTimeout);
          }
        }, 5000);
      }
    };

    // Connection error
    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    // Clean up function
    return () => {
      // Clear all typing timeouts
      if (typingTimeoutRef.current) {
        Object.values(typingTimeoutRef.current).forEach(clearTimeout);
      }
      
      // Close WebSocket connection
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    };
  }, [userId, conversationId]);

  // Handle input changes and send typing notifications
  const handleInputChange = (e) => {
    setInputValue(e.target.value);
    
    // Send typing notification
    if (webSocketRef.current?.readyState === WebSocket.OPEN && conversationId) {
      webSocketRef.current.send(JSON.stringify({
        event: 'typing',
        conversationId: conversationId
      }));
    }
  };

  // Mark a message as read
  const markMessageAsRead = (messageId) => {
    if (webSocketRef.current?.readyState === WebSocket.OPEN && conversationId) {
      webSocketRef.current.send(JSON.stringify({
        event: 'message_read',
        conversationId: conversationId,
        messageId: messageId
      }));
    }
  };

  // Update user status
  const updateStatus = (status) => {
    if (webSocketRef.current?.readyState === WebSocket.OPEN) {
      webSocketRef.current.send(JSON.stringify({
        event: 'status_change',
        status: status // e.g., "available", "away", "busy"
      }));
    }
  };

  return (
    <div className="chat-container">
      <div className="connection-status">
        {isConnected ? 'Connected' : 'Disconnected'}
      </div>
      
      <div className="status-controls">
        <button onClick={() => updateStatus('available')}>Available</button>
        <button onClick={() => updateStatus('away')}>Away</button>
        <button onClick={() => updateStatus('busy')}>Busy</button>
      </div>
      
      <div className="messages-container">
        {messages.map((msg) => (
          <div 
            key={msg.messageId} 
            className="message"
            onClick={() => markMessageAsRead(msg.messageId)}
          >
            <div className="message-sender">{msg.senderId}</div>
            <div className="message-content">{msg.content}</div>
            <div className="message-time">
              {new Date(msg.timestamp).toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>
      
      <div className="typing-indicators">
        {Object.keys(typingUsers).length > 0 && (
          <div className="typing-indicator">
            {Object.keys(typingUsers).join(', ')} {Object.keys(typingUsers).length > 1 ? 'are' : 'is'} typing...
          </div>
        )}
      </div>
      
      <div className="input-container">
        <input
          type="text"
          value={inputValue}
          onChange={handleInputChange}
          placeholder="Type a message..."
        />
      </div>
    </div>
  );
};

export default ChatComponent;
```

### Key Implementation Notes:

1. **Connection Management:**
   - The WebSocket connection is established in a `useEffect` hook
   - The connection includes handlers for `onopen`, `onmessage`, `onclose`, and `onerror` events
   - A cleanup function ensures resources are properly released when the component unmounts

2. **Heartbeat Mechanism:**
   - A heartbeat is sent every 30 seconds to keep the connection alive
   - The server responds with a `heartbeat_ack` message

3. **Typing Notifications:**
   - Sent when the user interacts with the input field
   - Typing indicators from other users are shown for 3 seconds after the last typing event

4. **Message Read Receipts:**
   - Sent when a user clicks on a message
   - Received read receipts update the UI to show which users have read messages

5. **Status Management:**
   - Simple buttons allow the user to change their status
   - Status changes from other users are logged to the console but could update UI elements

6. **Error Handling:**
   - Connection errors and server error messages are logged
   - On disconnection, a reconnection attempt is scheduled after 5 seconds
