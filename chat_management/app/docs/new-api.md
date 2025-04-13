# Chat Management (Remove All)

* Remove: GET /chats

* Remove: POST /chats

* Remove: GET /chats/{chat_id}/messages (Replaced under /conversations)

* Remove: POST /chats/{chat_id}/messages (Replaced under /conversations)

* Remove: POST /chats/{chat_id}/messages/{message_id}/read (Replaced under /conversations)

# Group Management (Remove All)
- Remove: POST /groups (Functionality merged into POST /conversations)

* Remove: PUT /groups/{group_id} (Replaced by PUT /conversations/{conversation_id} for metadata)

* Remove: DELETE /groups/{group_id} (Replaced by DELETE /conversations/{conversation_id})

* Remove: POST /groups/{group_id}/members (Replaced under /conversations)

* Remove: DELETE /groups/{group_id}/members/{phone_number} (Replaced under /conversations)

* Remove: POST /groups/{group_id}/admins (Replaced under /conversations)

* Remove: DELETE /groups/{group_id}/admins/{phone_number} (Replaced under /conversations)

* Remove: GET /groups/{group_id} (Replaced by GET /conversations/{conversation_id})

# Conversation Management (Add/Modify)

GET /conversations (Keep from conversations/router.py)

    Function: List all conversations (1-on-1 and group) for the user.
POST /conversations (Keep from conversations/router.py)

    Function: Create a new 1-on-1 or group conversation.

GET /conversations/{conversation_id} (Add New)

    Function: Get details of a specific conversation (1-on-1 or group).

    Note: Adapt logic from get_group in groups/router.py.

PUT /conversations/{conversation_id} (Add New)

    Function: Update conversation metadata (name, description, picture). Only applicable if is_group is true. Requires admin privileges.

    Request Body: { "name"?: "string", "description"?: "string", "group_picture"?: "string" }

    Note: Adapt logic from update_group in groups/router.py, but exclude member list updates.

DELETE /conversations/{conversation_id} (Add New)

    Function: Leave a conversation (if member) or delete a group conversation (if admin and is_group is true).

    Note: Combine logic from remove_member (for self-removal) and delete_group (for admin deletion) from groups/router.py.

# Member Management (Add New - Option 2)
POST /conversations/{conversation_id}/members (Add New)

    Function: Add a member to a group conversation. Requires admin privileges. Checks is_group.

    Request Body: { "user_id": "string" }

    Note: Adapt logic from add_member in groups/router.py.

DELETE /conversations/{conversation_id}/members/{user_id} (Add New)

    Function: Remove a member from a group conversation. Requires admin privileges or self-removal. Checks is_group.

    Note: Adapt logic from remove_member in groups/router.py.

PUT /conversations/{conversation_id}/members/{user_id}/role (Add New)

    Function: Change a member's role (ADMIN/MEMBER) in a group conversation. Requires admin privileges. Checks is_group.

    Request Body: { "role": "ADMIN" | "MEMBER" }

    Note: Adapt logic from add_admin and remove_admin in groups/router.py.

# Message Management (Modify Paths)
GET /conversations/{conversation_id}/messages (Modify Path)

    Function: Get messages for a conversation.

    Note: Update path in messages/router.py from /chats/... to /conversations/....

POST /conversations/{conversation_id}/messages (Modify Path)

    Function: Send a message to a conversation.
    
    Note: Update path in messages/router.py.

POST /conversations/{conversation_id}/messages/{message_id}/read (Modify Path)

    Function: Mark a message as read.
    
    Note: Update path in messages/router.py.

# WebSocket (Modify Event Payloads)
WSS /ws/{user_id} (Keep Endpoint Path As Is)

    Function: Handles real-time WebSocket connections.
    
    Event Payloads (Modify):
    
    Events like new_message, typing, message_read should now include conversation_id in their payload instead of chat_id. Update the broadcasting logic in messages/router.py and ws/websocket_manager.py accordingly.