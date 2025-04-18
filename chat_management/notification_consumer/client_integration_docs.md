# Zalo-Phake Notification System Integration Documentation

## 1. Overview

The Zalo-Phake notification system consists of two primary components:

1. **Real-time Notifications**: WebSocket-based system that delivers immediate updates for messages, typing indicators, read receipts, and user status changes.

2. **Push Notifications**: For offline users, push notifications are sent via Firebase Cloud Messaging (FCM) for all devices (mobile and web).

This document provides comprehensive guidance for integrating client applications with the notification system.

## 2. Prerequisites

Before integrating with the notification system, ensure you have:

- A valid authentication token (Firebase ID token in production or phone number in development)
- For push notifications: Firebase Cloud Messaging (FCM) set up for your mobile application
- Web Push API implementation for web applications

## 3. Authentication

### Authentication Methods

- **Production Environment**: Use Firebase ID tokens
  ```
  Authorization: Bearer <firebase_id_token>
  ```

- **Development Environment**: Use phone numbers as tokens
  ```
  Authorization: Bearer 1234567890
  ```

### Token Validation

The system validates tokens for both WebSocket connections and REST API calls. The token is verified against Firebase Authentication in production or accepted directly as a phone number in development.

## 4. WebSocket Integration

### Connecting to WebSocket

Connect to the WebSocket endpoint with your user ID and authentication token:

```javascript
const wsUrl = `ws://your-backend-host/ws/${userId}?token=${authToken}`;
const ws = new WebSocket(wsUrl);
```

### WebSocket Connection Lifecycle

```javascript
// Connection opened
ws.onopen = (event) => {
  console.log("WebSocket connection established");
  startHeartbeat(); // Start sending periodic heartbeats
};

// Connection closed
ws.onclose = (event) => {
  console.log(`WebSocket closed: ${event.code} - ${event.reason}`);
  
  // Handle close codes
  switch (event.code) {
    case 4001:
      console.error("Authentication failed - invalid token");
      break;
    case 4002:
      console.error("User ID mismatch between token and connection path");
      break;
    case 4003:
      console.error("User account is disabled");
      break;
    default:
      // Implement reconnection logic for unexpected disconnects
      setTimeout(reconnect, 5000);
  }
};

// Connection error
ws.onerror = (error) => {
  console.error("WebSocket error:", error);
};
```

### Client-Sent Events

1. **Heartbeat** (every 30 seconds)
```javascript
{
  "event": "heartbeat"
}
```

2. **Typing Notification**
```javascript
{
  "event": "typing",
  "conversationId": "7ccbca76-3f94-4a19-97cc-20079d2b9281"
}
```

3. **Message Read Receipt**
```javascript
{
  "event": "message_read",
  "conversationId": "7ccbca76-3f94-4a19-97cc-20079d2b9281",
  "messageId": "fe132e45-3a58-4eed-a935-e17a279b43e3"
}
```

4. **Status Change**
```javascript
{
  "event": "status_change",
  "status": "away" // One of: available, away, busy, invisible, offline
}
```

### Server-Sent Events

1. **New Message**
```javascript
{
  "event": "new_message",
  "conversationId": "7ccbca76-3f94-4a19-97cc-20079d2b9281",
  "messageId": "fe132e45-3a58-4eed-a935-e17a279b43e3",
  "senderId": "1234567890",
  "content": "Hello there!",
  "messageType": "text", // One of: text, image, video, audio
  "timestamp": "2025-04-18T10:05:30.819Z"
}
```

2. **Typing Indicator**
```javascript
{
  "event": "typing",
  "conversationId": "7ccbca76-3f94-4a19-97cc-20079d2b9281",
  "userId": "1234567890"
}
```

3. **Message Read Receipt**
```javascript
{
  "event": "message_read",
  "conversationId": "7ccbca76-3f94-4a19-97cc-20079d2b9281",
  "messageId": "fe132e45-3a58-4eed-a935-e17a279b43e3",
  "userId": "1234567890"
}
```

4. **User Status Change**
```javascript
{
  "event": "user_status_change",
  "userId": "1234567890",
  "status": "online",
  "conversationId": "7ccbca76-3f94-4a19-97cc-20079d2b9281" // Optional, present when specific to a conversation
}
```

5. **Heartbeat Acknowledgment**
```javascript
{
  "event": "heartbeat_ack"
}
```

6. **Error**
```javascript
{
  "event": "error",
  "message": "Missing status parameter"
}
```

### ReactJS Implementation Example

```jsx
import React, { useEffect, useRef, useState } from 'react';

function ChatComponent({ userId, authToken }) {
  const [messages, setMessages] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const ws = useRef(null);
  const heartbeatInterval = useRef(null);
  
  // Connect to WebSocket
  const connectWebSocket = () => {
    const wsUrl = `ws://your-backend/ws/${userId}?token=${authToken}`;
    ws.current = new WebSocket(wsUrl);
    
    ws.current.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      
      // Start heartbeat
      heartbeatInterval.current = setInterval(() => {
        if (ws.current.readyState === WebSocket.OPEN) {
          ws.current.send(JSON.stringify({ event: 'heartbeat' }));
        }
      }, 30000);
    };
    
    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      switch (data.event) {
        case 'new_message':
          handleNewMessage(data);
          break;
        case 'typing':
          handleTypingIndicator(data);
          break;
        case 'message_read':
          handleReadReceipt(data);
          break;
        case 'user_status_change':
          handleStatusChange(data);
          break;
        case 'heartbeat_ack':
          // Heartbeat acknowledged
          break;
        case 'error':
          console.error('WebSocket error:', data.message);
          break;
      }
    };
    
    ws.current.onclose = (event) => {
      setIsConnected(false);
      clearInterval(heartbeatInterval.current);
      
      // Implement reconnection logic
      if (event.code !== 4001 && event.code !== 4003) {
        setTimeout(connectWebSocket, 5000);
      }
    };
    
    ws.current.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  };
  
  // Handle new message
  const handleNewMessage = (data) => {
    setMessages(prev => [...prev, data]);
    
    // Send read receipt
    if (ws.current.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify({
        event: 'message_read',
        conversationId: data.conversationId,
        messageId: data.messageId
      }));
    }
  };
  
  // Send message
  const sendMessage = (content, conversationId) => {
    // Messages are sent via API, not WebSocket
    fetch('/api/v1/conversations/${conversationId}/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${authToken}`
      },
      body: JSON.stringify({
        content,
        messageType: 'text'
      })
    });
  };
  
  // Cleanup on unmount
  useEffect(() => {
    connectWebSocket();
    
    return () => {
      if (ws.current) {
        ws.current.close();
      }
      if (heartbeatInterval.current) {
        clearInterval(heartbeatInterval.current);
      }
    };
  }, [userId, authToken]);
  
  return (
    <div className="chat-container">
      {/* Your chat UI components */}
    </div>
  );
}
```

## 5. Push Notification Integration

### Registering Device Tokens

To receive push notifications, register device tokens using the API:

```javascript
fetch('/api/v1/device-tokens', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${authToken}`
  },
  body: JSON.stringify({
    userId: userPhoneNumber,
    token: fcmToken, // Firebase Cloud Messaging token
    deviceType: 'android' // 'ios', 'android', or 'web'
  })
});
```

### Unregistering Tokens on Logout

When users log out, unregister the device token:

```javascript
fetch(`/api/v1/device-tokens/${fcmToken}`, {
  method: 'DELETE',
  headers: {
    'Authorization': `Bearer ${authToken}`
  }
});
```

### Push Notification Payload Structure

**Android/iOS (FCM):**
```json
{
  "notification": {
    "title": "John Doe",
    "body": "Hello there!"
  },
  "data": {
    "conversationId": "7ccbca76-3f94-4a19-97cc-20079d2b9281",
    "messageId": "fe132e45-3a58-4eed-a935-e17a279b43e3"
  }
}
```

**Web (FCM):**
```json
{
  "notification": {
    "title": "John Doe",
    "body": "Hello there!"
  },
  "data": {
    "conversationId": "7ccbca76-3f94-4a19-97cc-20079d2b9281",
    "messageId": "fe132e45-3a58-4eed-a935-e17a279b43e3"
  }
}
```

### Handling Received Push Notifications

**Android Example:**
```kotlin
class MyFirebaseMessagingService : FirebaseMessagingService() {
    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        // Extract data
        val conversationId = remoteMessage.data["conversationId"]
        val messageId = remoteMessage.data["messageId"]
        
        // Show notification
        showNotification(remoteMessage.notification?.title, remoteMessage.notification?.body)
        
        // Update conversation UI if the app is in foreground
        updateConversationIfActive(conversationId)
    }
}
```

**iOS Example (Swift):**
```swift
func application(_ application: UIApplication, didReceiveRemoteNotification userInfo: [AnyHashable: Any],
                 fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void) {
    // Extract data
    guard let conversationId = userInfo["conversationId"] as? String,
          let messageId = userInfo["messageId"] as? String else {
        completionHandler(.failed)
        return
    }
    
    // Handle notification
    if application.applicationState == .active {
        // App is in foreground, update UI directly
        updateConversationIfActive(conversationId)
    } else {
        // App is in background, show notification
    }
    
    completionHandler(.newData)
}
```

## 6. Notification Management API

### Fetching Notifications

Retrieve recent notifications with pagination:

```javascript
// Get all notifications (paginated)
fetch('/api/v1/notifications?page=1&size=20', {
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${authToken}`
  }
});

// Get only unread notifications
fetch('/api/v1/notifications?page=1&size=20&unread_only=true', {
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${authToken}`
  }
});
```

### Marking Notifications as Read

Mark individual notifications as read:

```javascript
fetch(`/api/v1/notifications/${notificationId}/read`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${authToken}`
  }
});
```

Mark all notifications as read:

```javascript
fetch('/api/v1/notifications/read-all', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${authToken}`
  }
});
```

### Notification Preferences

Get user notification preferences:

```javascript
fetch('/api/v1/notification-preferences', {
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${authToken}`
  }
});
```

Update notification preferences:

```javascript
fetch('/api/v1/notification-preferences', {
  method: 'PUT',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${authToken}`
  },
  body: JSON.stringify({
    userId: userPhoneNumber,
    pushEnabled: true,
    messageNotifications: true,
    groupNotifications: true,
    friendRequestNotifications: true,
    systemNotifications: true,
    muteUntil: null // ISO datetime string to mute until a specific time
  })
});
```

## 7. Testing with Postman

### Setting Up WebSocket Requests

1. **Create a WebSocket Request**
   - Open Postman and click on "New" > "WebSocket Request"
   - Enter the WebSocket URL: `ws://your-backend/ws/1234567890?token=1234567890`
   - Click "Connect"

2. **Sending Events**
   - In the "Message" field, enter a JSON object:
     ```json
     {
       "event": "heartbeat"
     }
     ```
   - Click "Send"
   - Observe the response in the Messages panel

3. **Testing Typing Indicators**
   ```json
   {
     "event": "typing",
     "conversationId": "your-conversation-id"
   }
   ```

4. **Testing Read Receipts**
   ```json
   {
     "event": "message_read",
     "conversationId": "your-conversation-id",
     "messageId": "your-message-id"
   }
   ```

### Testing REST API Endpoints

Create a Postman collection with the following requests:

1. **Register Device Token**
   - URL: `POST /api/v1/device-tokens`
   - Headers: `Authorization: Bearer <token>`
   - Body:
     ```json
     {
       "userId": "1234567890",
       "token": "fcm-token-here",
       "deviceType": "android"
     }
     ```

2. **Fetch Notifications**
   - URL: `GET /api/v1/notifications?page=1&size=20`
   - Headers: `Authorization: Bearer <token>`

3. **Mark Notification as Read**
   - URL: `POST /api/v1/notifications/{notification_id}/read`
   - Headers: `Authorization: Bearer <token>`

4. **Update Notification Preferences**
   - URL: `PUT /api/v1/notification-preferences`
   - Headers: `Authorization: Bearer <token>`
   - Body:
     ```json
     {
       "userId": "1234567890",
       "pushEnabled": true,
       "messageNotifications": true,
       "groupNotifications": true,
       "friendRequestNotifications": true,
       "systemNotifications": true
     }
     ```

## 8. Best Practices

### WebSocket Connection

1. **Heartbeat Implementation**
   - Send heartbeat messages every 30 seconds
   - If no response is received, reconnect after a short timeout
   - Example:
     ```javascript
     setInterval(() => {
       if (ws.readyState === WebSocket.OPEN) {
         ws.send(JSON.stringify({ event: 'heartbeat' }));
         
         // Set a timeout to verify we get a response
         const heartbeatTimeout = setTimeout(() => {
           // No response received within 5 seconds
           if (ws.readyState === WebSocket.OPEN) {
             ws.close();
             // Reconnect logic will be triggered by onclose
           }
         }, 5000);
         
         // Clear timeout when response is received
         ws.addEventListener('message', function responseHandler(event) {
           const data = JSON.parse(event.data);
           if (data.event === 'heartbeat_ack') {
             clearTimeout(heartbeatTimeout);
             ws.removeEventListener('message', responseHandler);
           }
         });
       }
     }, 30000);
     ```

2. **Reconnection Logic**
   - Implement exponential backoff for reconnection attempts
   - Don't retry if the connection was rejected due to authentication (4001, 4003)
   - Reset the backoff timer after successful connection
   - Example:
     ```javascript
     let reconnectAttempts = 0;
     const maxReconnectAttempts = 10;
     
     function reconnect() {
       if (reconnectAttempts < maxReconnectAttempts) {
         const timeout = Math.min(30000, Math.pow(2, reconnectAttempts) * 1000);
         setTimeout(() => {
           reconnectAttempts++;
           connectWebSocket();
         }, timeout);
       } else {
         console.error('Maximum reconnection attempts reached');
       }
     }
     ```

3. **Error Handling**
   - Log and handle errors appropriately
   - Implement user feedback for persistent connection issues
   - Maintain a connection state indicator in the UI
   - Consider switching to offline mode after multiple failed reconnection attempts

### Push Notifications

1. **Device Token Management**
   - Register device tokens on app startup
   - Refresh FCM token when notified by Firebase
   - Unregister tokens during logout
   - Handle token expiration and renewal

2. **Silent Notifications**
   - For important updates that don't need user notification
   - Use to sync data in the background

3. **Notification Grouping**
   - Group notifications from the same conversation
   - Use notification channels on Android for categorization
   - Implement notification summary when many notifications are pending

### Offline Support

1. **Message Queue**
   - Queue outgoing messages when offline
   - Resend when connection is restored
   - Provide visual feedback on message status (sending, sent, delivered, read)

2. **Local Storage**
   - Cache recent conversations and messages
   - Store notification preferences locally
   - Update local cache when receiving push notifications