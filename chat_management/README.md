# Zalo-Phake

A chat management backend service built with FastAPI, Firebase, and AWS.

## Overview

This project provides a scalable backend service for a chat application, supporting individual and group chats. It uses Firebase Firestore for data storage and AWS services for deployment and additional functionality.

## Features

- **Individual Chat Management**: Create and manage one-on-one conversations
- **Group Chat Management**: Create, update, and delete group chats
- **Member Administration**: Add/remove members from groups, promote/demote admin status
- **Message Handling**: Send, retrieve, and manage messages
- **Real-time Notifications**: Using WebSockets for real-time updates
- **Pagination**: Efficient data retrieval with pagination support

## Architecture & Flow

### Data Storage
- Firebase Firestore is used as the primary database
- Chat data is organized in collections for chats, messages, and users
- Real-time updates are supported through Firebase's real-time capabilities

### Authentication
- JWT-based authentication for production use
- Development mode supports Vietnamese phone number validation for easier testing

### API Layers
1. **Router Layer**: FastAPI routes for handling HTTP requests
2. **Service Layer**: Business logic processing
3. **Data Layer**: Firebase Firestore interactions

### Message Flow
1. User creates a chat or sends to an existing chat
2. Message is stored in Firestore
3. Notifications are sent to participants
4. Recipients can retrieve messages with pagination

## Development Setup

### Prerequisites
- Python 3.10+
- Docker and Docker Compose
- Firebase account and credentials

### Local Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/zalo-phake.git
cd zalo-phake
```

2. Install dependencies:
```bash
cd chat_management
pip install -r requirements.txt
```

3. Start local services (if needed):
```bash
docker compose -f chat_management/local/docker-compose.yml up -d
```

4. Run the application:
```bash
cd chat_management
uvicorn app.main:app --reload --log-config app/conf/log_conf.yaml --host 0.0.0.0 --port 3000
```

5. Access the API documentation at: http://localhost:3000/docs

### Authentication for Development

During development, the system uses a simplified authentication approach:

- Add a valid Vietnamese phone number (e.g., "+84912345678") in the Authorization header
- Example curl command:
  ```bash
  curl -X GET "http://localhost:3000/api/v1/chats" -H "Authorization: Bearer +84912345678"
  ```
- This bypasses proper JWT authentication for easier testing

## API Endpoints

### Chat Management
- `GET /api/v1/chats` - Get user's chat list
- `POST /api/v1/chats` - Create a new chat

### Group Management
- `POST /api/v1/groups` - Create a new group
- `PUT /api/v1/groups/{group_id}` - Update a group
- `DELETE /api/v1/groups/{group_id}` - Delete a group
- `GET /api/v1/groups/{group_id}` - Get group details
- Various endpoints for member and admin management

### Message Management
- `POST /api/v1/messages` - Send a message
- `GET /api/v1/chats/{chat_id}/messages` - Get messages from a specific chat

## Environment Variables

- `AWS_REGION`: AWS region (default: ap-southeast-1)
- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key
- `SQS_URL`: AWS SQS URL for message queueing
- `FIREBASE_SECRET`: Firebase credentials secret

## Deployment

The application is configured for deployment to AWS ECS using Fargate:

- Task definition is in `deployments/task-definition.json`
- CI/CD automation can be built around this configuration

## License

[Add appropriate license information]

