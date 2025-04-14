import asyncio
import logging
import os

from app.config import get_prefix
from app.dependencies import decode_token
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from .aws.elasticache.pubsub import start_pubsub_listener  # Updated import to use chat_management service
from .conversations import all_router as conversations_routers
from .notifications.router import router as notifications_router
from .ws.api_endpoints import router as ws_api_router
from .ws.router import router as ws_router

# import all you need from fastapi-pagination

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

origins = [
    "*"
]

# Print all environment variables
for key, value in os.environ.items():
    print(f"{key}: {value}")

logger = logging.getLogger(__name__)


API_VERSION = '/api/v1'
PREFIX = get_prefix(API_VERSION)

logger.info(f"Start HTTP server with prefix: {PREFIX}")

app = FastAPI(root_path=PREFIX)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for monitoring and deployment verification
    """
    return {"status": "healthy", "version": "1.0.0"}

@app.get("/whoami", tags=["Dev test"])
async def whoami(current_user: dict = Depends(decode_token)):
    return current_user


# app.include_router(chats_router)
for router in conversations_routers:
    app.include_router(router)
# app.include_router(messages_router)
# app.include_router(groups_router)
app.include_router(notifications_router)
app.include_router(ws_router)
app.include_router(ws_api_router)


@app.on_event("startup")
async def startup_event():
    """
    Run on application startup to initialize background tasks and services
    """
    # Start chat_management service PubSub listener for WebSocket message distribution across instances
    asyncio.create_task(start_pubsub_listener())
    logger.info("Started chat_management service PubSub listener for WebSocket message distribution")
    
    # Initialize health check document in Firestore if it doesn't exist
    from .firebase import firestore_db
    health_ref = firestore_db.collection('system').document('health')
    if not health_ref.get().exists:
        health_ref.set({
            'status': 'healthy',
            'created_at': firestore_db.SERVER_TIMESTAMP
        })
        logger.info("Initialized health check document in Firestore")
    
    # Log instance information
    instance_id = os.environ.get("INSTANCE_ID", "local")
    logger.info(f"Server instance {instance_id} started successfully")