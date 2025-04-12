import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Union
import asyncio

from ..aws import sqs_client
from ..aws.config import settings

logger = logging.getLogger(__name__)

def serialize_datetime(obj: Any) -> Any:
  """
  Helper function to serialize datetime objects to ISO format strings.

  Args:
      obj: The object to serialize

  Returns:
      Serialized object
  """
  if isinstance(obj, datetime):
    return obj.isoformat()
  raise TypeError(f"Type {type(obj)} not serializable")

async def send_to_sqs(
    event_type: str,
    payload: Dict[str, Any],
    delay_seconds: int = 0,
    message_group_id: Optional[str] = None
) -> bool:
  """
  Send a message to the SQS queue with proper formatting and error handling.

  Args:
      event_type: Type of event (new_message, group_invitation, etc.)
      payload: Dictionary with event data
      delay_seconds: Delay before message becomes visible (0-900 seconds)
      message_group_id: Optional group ID for FIFO queues

  Returns:
      bool: True if message was sent successfully, False otherwise
  """
  if not sqs_client:
    logger.warning("SQS client not initialized, message not sent")
    return False

  try:
    # Add event type to payload
    message_data = payload.copy()
    message_data['event'] = event_type

    # Add timestamp if not present
    if 'timestamp' not in message_data:
      message_data['timestamp'] = datetime.utcnow().isoformat()

    # Add unique message ID if not present
    if 'messageId' not in message_data:
      message_data['messageId'] = str(uuid.uuid4())

    # Prepare message attributes if needed
    message_attributes = None
    if message_group_id or settings.aws_sqs_message_group_id:
      # This suggests we're using a FIFO queue, so add appropriate attributes
      message_group_id = message_group_id or settings.aws_sqs_message_group_id
      message_attributes = {
        'MessageGroupId': {
          'DataType': 'String',
          'StringValue': message_group_id
        },
        'MessageDeduplicationId': {
          'DataType': 'String',
          'StringValue': message_data['messageId']  # Use the message ID for deduplication
        }
      }

    # Ensure payload size is within limits
    json_payload = json.dumps(message_data, default=serialize_datetime)
    if len(json_payload.encode('utf-8')) > settings.aws_sqs_max_message_size:
      logger.error(f"Message payload exceeds SQS size limit of {settings.aws_sqs_max_message_size} bytes")
      return False

    # Send message to SQS
    response = sqs_client.send_message(
        queue_url=settings.aws_sqs_queue_url,
        message_body=json_payload,
        delay_seconds=delay_seconds,
        message_attributes=message_attributes
    )

    logger.info(f"Successfully sent {event_type} message to SQS, MessageId: {response.get('MessageId')}")
    return True

  except Exception as e:
    logger.error(f"Error sending message to SQS: {str(e)}")
    return False

async def send_chat_message_notification(
    chat_id: str,
    message_id: str,
    sender_id: str,
    content: str,
    message_type: str,
    participants: list,
    delay_seconds: int = 0
) -> bool:
  """
  Send a chat message notification to the SQS queue.

  Args:
      chat_id: The chat ID
      message_id: The message ID
      sender_id: The sender's ID
      content: The message content
      message_type: The message type (text, image, etc.)
      participants: List of participant IDs
      delay_seconds: Delay before message becomes visible

  Returns:
      bool: True if message was sent successfully, False otherwise
  """
  payload = {
    'chatId': chat_id,
    'messageId': message_id,
    'senderId': sender_id,
    'content': content,
    'messageType': message_type,
    'participants': participants,
    'timestamp': datetime.utcnow().isoformat()
  }

  return await send_to_sqs('new_message', payload, delay_seconds)

async def send_group_invitation_notification(
    group_id: str,
    group_name: str,
    sender_id: str,
    invitee_id: str,
    delay_seconds: int = 0
) -> bool:
  """
  Send a group invitation notification to the SQS queue.

  Args:
      group_id: The group ID
      group_name: The name of the group
      sender_id: The ID of the user sending the invitation
      invitee_id: The ID of the invited user
      delay_seconds: Delay before message becomes visible

  Returns:
      bool: True if message was sent successfully, False otherwise
  """
  payload = {
    'groupId': group_id,
    'groupName': group_name,
    'senderId': sender_id,
    'inviteeId': invitee_id,
    'timestamp': datetime.utcnow().isoformat()
  }

  return await send_to_sqs('group_invitation', payload, delay_seconds)

async def send_friend_request_notification(
    sender_id: str,
    recipient_id: str,
    delay_seconds: int = 0
) -> bool:
  """
  Send a friend request notification to the SQS queue.

  Args:
      sender_id: The ID of the user sending the request
      recipient_id: The ID of the recipient
      delay_seconds: Delay before message becomes visible

  Returns:
      bool: True if message was sent successfully, False otherwise
  """
  payload = {
    'senderId': sender_id,
    'recipientId': recipient_id,
    'timestamp': datetime.utcnow().isoformat()
  }

  return await send_to_sqs('friend_request', payload, delay_seconds)

def is_sqs_available() -> bool:
  """
  Check if SQS functionality is available.

  Returns:
      bool: True if SQS client is initialized and ready, False otherwise
  """
  return sqs_client is not None and settings.aws_sqs_queue_url != ''