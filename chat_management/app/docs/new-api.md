# Removed APIs (from original design):

GET /api/chats: Replaced by GET /api/conversations

POST /api/chats: Functionality merged into POST /api/conversations.

GET /api/chats/messages: Replaced by GET /api/conversations/{conversation_id}/messages

POST /api/chats/messages: Replaced by POST /api/conversations/{conversation_id}/messages.
POST /api/groups: Functionality merged into POST /api/conversations.
PUT /api/groups/: Replaced by PUT /api/conversations/{conversation_id}.
DELETE /api/groups/: Replaced by DELETE /api/conversations/{conversation_id}.

# Added APIs (in the new unified design):

GET /api/conversations: Retrieves both 1-on-1 and group conversations for the user.
POST /api/conversations: Creates both 1-on-1 and group conversations based on input (participants, name).
GET /api/conversations/{conversation_id}: Retrieves details for any specific conversation (1-on-1 or group).
PUT /api/conversations/{conversation_id}: Updates any conversation (though primarily used for group management like adding/removing members, changing name).
DELETE /api/conversations/{conversation_id}: Allows leaving/deleting any conversation (with appropriate logic/permissions).
GET /api/conversations/{conversation_id}/messages: New path structure for fetching messages.
POST /api/conversations/{conversation_id}/messages: New path structure for sending messages.

# Modified Functionality (Existing Concepts with Changes):

Message Handling: The concept of sending/receiving messages remains, but the specific endpoints (GET/POST .../messages) now operate under the /api/conversations/{conversation_id}/ path and handle both chat types.

Group Management Concepts: The functionality of managing groups (adding/removing members, changing names) is now handled by the general PUT /api/conversations/{conversation_id} endpoint, which internally checks if it's a group (is_group: true) and if the user has permission.

