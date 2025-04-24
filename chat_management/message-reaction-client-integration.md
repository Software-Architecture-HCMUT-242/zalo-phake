# Message Reactions Feature: Client Integration Guide

This document provides guidance on integrating the message reactions feature into client applications using ReactJS. It includes both the data flow explanation and example code.

## 1. Data Flow Overview

The message reactions feature follows this general flow:

1. **User adds/updates/removes a reaction**: User clicks on a message to add a reaction, clicks on a different reaction to change it, or clicks on their existing reaction to remove it.

2. **Client sends reaction to server**: Client makes a POST request to the server's reaction API endpoint.

3. **Server updates Firestore**: Server updates the message document in Firestore.

4. **Server broadcasts to WebSockets**: Server sends real-time updates to all connected clients.

5. **Clients receive updates**: All clients in the conversation receive the WebSocket event and update their UI.

## 2. API Integration

### API Endpoint Details

- **URL**: `POST /conversations/{conversation_id}/messages/{message_id}/reactions`
- **Method**: POST
- **Authentication**: Bearer token
- **Request Body**:
  ```json
  {
    "reaction": "👍" // String for add/update, null or "" for remove
  }
  ```
- **Response**:
  ```json
  {
    "messageId": "message-123",
    "reactions": {
      "+84123456789": "👍",
      "+84987654321": "❤️"
    }
  }
  ```

### API Integration Example (React)

```javascript
// api/messageReactions.js
export const addMessageReaction = async (conversationId, messageId, reaction, token) => {
  try {
    const response = await fetch(
      `/api/conversations/${conversationId}/messages/${messageId}/reactions`, 
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ reaction })
      }
    );
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to add reaction');
    }
    
    return await response.json();
  } catch (error) {
    console.error('Error adding reaction:', error);
    throw error;
  }
};

export const removeMessageReaction = async (conversationId, messageId, token) => {
  // To remove a reaction, send null or empty string
  return addMessageReaction(conversationId, messageId, null, token);
};
```

## 3. WebSocket Integration

### WebSocket Event Structure

When a reaction is added, updated, or removed, the server sends a WebSocket event with this structure:

```json
{
  "event": "message_reaction",
  "conversationId": "conversation-123",
  "messageId": "message-456",
  "userId": "+84123456789",
  "reaction": "👍" // or null if removed
}
```

### WebSocket Handler Example (React)

```javascript
// hooks/useWebSocketReactions.js
import { useEffect } from 'react';
import { useWebSocket } from './useWebSocket'; // Your WebSocket hook

export const useWebSocketReactions = (setMessages) => {
  const { socket } = useWebSocket();
  
  useEffect(() => {
    if (!socket) return;
    
    const handleMessageReaction = (data) => {
      if (data.event !== 'message_reaction') return;
      
      const { conversationId, messageId, userId, reaction } = data;
      
      setMessages(prevMessages => {
        return prevMessages.map(message => {
          // Only update the specific message that got the reaction
          if (message.messageId !== messageId) return message;
          
          // Create a copy of the current reactions or initialize if none
          const updatedReactions = { ...(message.reactions || {}) };
          
          if (reaction) {
            // Add or update the reaction
            updatedReactions[userId] = reaction;
          } else {
            // Remove the reaction
            delete updatedReactions[userId];
          }
          
          // Return updated message with new reactions
          return {
            ...message,
            reactions: updatedReactions
          };
        });
      });
    };
    
    // Add event listener
    socket.addEventListener('message', (event) => {
      try {
        const data = JSON.parse(event.data);
        handleMessageReaction(data);
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    });
    
    // Clean up
    return () => {
      // Clean up logic if needed
    };
  }, [socket, setMessages]);
};
```

## 4. Complete React Component Example

Here's a complete example of a React component that displays a message with reactions:

```jsx
// components/MessageItem.jsx
import React, { useState } from 'react';
import { addMessageReaction, removeMessageReaction } from '../api/messageReactions';
import EmojiPicker from './EmojiPicker'; // Custom emoji picker component

const MessageItem = ({ 
  message, 
  conversationId, 
  currentUserId, 
  authToken,
  onReactionUpdate
}) => {
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  
  // Handle adding/updating reaction
  const handleReactionClick = async (emoji) => {
    try {
      // If user already reacted with this emoji, remove it
      const userCurrentReaction = message.reactions?.[currentUserId];
      
      if (userCurrentReaction === emoji) {
        // Remove the reaction
        await removeMessageReaction(conversationId, message.messageId, authToken);
      } else {
        // Add or update the reaction
        await addMessageReaction(conversationId, message.messageId, emoji, authToken);
      }
      
      setShowEmojiPicker(false);
    } catch (error) {
      console.error('Error handling reaction:', error);
    }
  };
  
  // Group reactions by emoji
  const getGroupedReactions = () => {
    const grouped = {};
    
    if (message.reactions) {
      Object.entries(message.reactions).forEach(([userId, reaction]) => {
        if (!grouped[reaction]) {
          grouped[reaction] = [];
        }
        grouped[reaction].push(userId);
      });
    }
    
    return grouped;
  };
  
  const groupedReactions = getGroupedReactions();
  const userReaction = message.reactions?.[currentUserId];
  
  return (
    <div className="message-container">
      {/* Message content */}
      <div className="message-bubble">
        <div className="sender">{message.senderId}</div>
        <div className="content">{message.content}</div>
        <div className="timestamp">
          {new Date(message.timestamp).toLocaleTimeString()}
        </div>
        
        {/* Reaction button */}
        <button 
          className="reaction-button"
          onClick={() => setShowEmojiPicker(!showEmojiPicker)}
        >
          😀
        </button>
      </div>
      
      {/* Emoji picker */}
      {showEmojiPicker && (
        <div className="emoji-picker-container">
          <EmojiPicker onEmojiSelect={handleReactionClick} />
        </div>
      )}
      
      {/* Display reactions */}
      {Object.keys(groupedReactions).length > 0 && (
        <div className="reactions-container">
          {Object.entries(groupedReactions).map(([emoji, userIds]) => (
            <div 
              key={emoji}
              className={`reaction-badge ${userIds.includes(currentUserId) ? 'user-reacted' : ''}`}
              onClick={() => handleReactionClick(emoji)}
            >
              <span className="emoji">{emoji}</span>
              <span className="count">{userIds.length}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MessageItem;
```

## 5. Conversation Component Integration

Here's how to integrate the reactions feature into a conversation component:

```jsx
// components/Conversation.jsx
import React, { useState, useEffect } from 'react';
import MessageItem from './MessageItem';
import { fetchMessages } from '../api/messages';
import { useWebSocketReactions } from '../hooks/useWebSocketReactions';

const Conversation = ({ conversationId, currentUserId, authToken }) => {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // Initialize WebSocket reactions handler
  useWebSocketReactions(setMessages);
  
  // Fetch messages for this conversation
  useEffect(() => {
    const loadMessages = async () => {
      try {
        setLoading(true);
        const fetchedMessages = await fetchMessages(conversationId, authToken);
        setMessages(fetchedMessages);
      } catch (error) {
        console.error('Error fetching messages:', error);
      } finally {
        setLoading(false);
      }
    };
    
    loadMessages();
  }, [conversationId, authToken]);
  
  // Handle local reaction updates (optimistic UI)
  const handleReactionUpdate = (messageId, userId, reaction) => {
    setMessages(prevMessages => {
      return prevMessages.map(message => {
        if (message.messageId !== messageId) return message;
        
        const updatedReactions = { ...(message.reactions || {}) };
        
        if (reaction) {
          updatedReactions[userId] = reaction;
        } else {
          delete updatedReactions[userId];
        }
        
        return {
          ...message,
          reactions: updatedReactions
        };
      });
    });
  };
  
  if (loading) {
    return <div>Loading messages...</div>;
  }
  
  return (
    <div className="conversation-container">
      <h2>Conversation</h2>
      
      <div className="messages-list">
        {messages.map(message => (
          <MessageItem
            key={message.messageId}
            message={message}
            conversationId={conversationId}
            currentUserId={currentUserId}
            authToken={authToken}
            onReactionUpdate={handleReactionUpdate}
          />
        ))}
      </div>
    </div>
  );
};

export default Conversation;
```


## 7. Handling Optimistic Updates

For a better user experience, implement optimistic updates to reflect reaction changes immediately before the server response:

```jsx
// Within MessageItem component
const handleReactionClick = async (emoji) => {
  try {
    const userCurrentReaction = message.reactions?.[currentUserId];
    
    // Optimistically update UI
    if (userCurrentReaction === emoji) {
      // Remove reaction optimistically
      onReactionUpdate(message.messageId, currentUserId, null);
    } else {
      // Add/update reaction optimistically
      onReactionUpdate(message.messageId, currentUserId, emoji);
    }
    
    // Send to server
    if (userCurrentReaction === emoji) {
      await removeMessageReaction(conversationId, message.messageId, authToken);
    } else {
      await addMessageReaction(conversationId, message.messageId, emoji, authToken);
    }
    
    setShowEmojiPicker(false);
  } catch (error) {
    console.error('Error handling reaction:', error);
    // Revert optimistic update on error
    onReactionUpdate(message.messageId, currentUserId, userCurrentReaction);
  }
};
```

## 8. Testing the Integration

1. **Test adding a reaction**: 
   - Verify the API call is made with the correct emoji
   - Ensure the UI updates to show the new reaction
   - Confirm other clients receive the WebSocket event

2. **Test updating a reaction**:
   - Change a user's reaction from one emoji to another
   - Verify the previous reaction is removed and new one added

3. **Test removing a reaction**:
   - Click on a user's existing reaction to remove it
   - Verify the API call is made with null reaction
   - Ensure the UI updates to remove the reaction

4. **Test WebSocket event handling**:
   - Open the application in two different browsers/tabs
   - Add/update/remove reactions in one
   - Verify the other one updates accordingly

## 9. Common Issues & Solutions

### Issue: Reactions not showing up in real-time
- Verify WebSocket connection is established
- Check event handler is correctly parsing the message_reaction event
- Ensure your state update logic correctly merges new reactions

### Issue: Emoji picker not working
- Verify the emoji library is correctly installed and imported
- Check CSS z-index to ensure picker is visible above other elements

### Issue: Reaction count incorrect
- Ensure you're correctly grouping reactions by emoji
- Verify the reaction object structure matches expectations

### Issue: Reactions not persisting after page refresh
- Verify Firestore update was successful
- Check that message fetching includes the reactions field

## 10. Future Enhancements

Consider these enhancements to improve the user experience:

1. **Animation**: Add subtle animations when reactions are added/removed
2. **Frequently used emojis**: Track and display user's most frequently used reactions
3. **Reaction details**: Add tooltip/popup showing which users added each reaction
4. **Keyboard shortcuts**: Allow adding reactions via keyboard shortcuts
5. **Reaction limits**: Implement UI feedback if server-side reaction limits are reached
