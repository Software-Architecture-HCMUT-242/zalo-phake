import json
import logging
import os
import boto3
import firebase_admin
from firebase_admin import credentials, firestore, messaging
from datetime import datetime, timezone

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize Firebase Admin SDK with credentials from environment
try:
  firebase_app = None
  if not firebase_admin._apps:
    cert_json = os.environ.get('FIREBASE_SECRET')
    if cert_json:
      cert_dict = json.loads(cert_json)
      cred = credentials.Certificate(cert_dict)
      firebase_app = firebase_admin.initialize_app(
          credential=cred,
          options={"databaseURL": os.environ.get('FIREBASE_DB_URL')}
      )
    else:
      logger.error("Environment variable FIREBASE_SECRET is not set")
except Exception as e:
  logger.error(f"Failed to initialize Firebase: {str(e)}")

# Initialize Firestore
db = firestore.client()

def lambda_handler(event, context):
  """
  AWS Lambda handler for processing SQS messages and sending notifications
  """
  logger.info("Received event: " + json.dumps(event))

  # Process each SQS message
  for record in event.get('Records', []):
    try:
      # Parse the SQS message body
      body = json.loads(record.get('body', '{}'))
      logger.info(f"Processing message: {body}")

      event_type = body.get('event')

      if event_type == 'new_message':
        process_new_message(body)
      elif event_type == 'group_invitation':
        process_group_invitation(body)
      elif event_type == 'friend_request':
        process_friend_request(body)
      else:
        logger.warning(f"Unknown event type: {event_type}")

    except json.JSONDecodeError:
      logger.error("Invalid JSON in SQS message body")
    except Exception as e:
      logger.error(f"Error processing message: {str(e)}")

  return {
    'statusCode': 200,
    'body': json.dumps('Message processing completed')
  }

def process_new_message(message_data):
  """
  Process a new chat message and send notifications to offline users
  """
  chat_id = message_data.get('chatId')
  message_id = message_data.get('messageId')
  sender_id = message_data.get('senderId')
  content = message_data.get('content')
  participants = message_data.get('participants', [])

  if not (chat_id and message_id and sender_id and content and participants):
    logger.error(f"Invalid message data: {message_data}")
    return

  # Get chat details for notification
  try:
    chat_ref = db.collection('chats').document(chat_id)
    chat = chat_ref.get()

    if not chat.exists:
      logger.error(f"Chat {chat_id} not found")
      return

    # Get sender name
    sender_ref = db.collection('users').document(sender_id)
    sender = sender_ref.get()
    sender_name = sender_id
    if sender.exists:
      sender_data = sender.to_dict()
      sender_name = sender_data.get('name', sender_id)

    # Send notifications to all participants except sender
    for participant_id in participants:
      if participant_id == sender_id:
        continue

      # Check if user is online
      user_ref = db.collection('users').document(participant_id)
      user = user_ref.get()

      if not user.exists:
        continue

      user_data = user.to_dict()
      is_online = user_data.get('isOnline', False)

      # If user is offline, send push notification
      if not is_online:
        # Check notification preferences
        should_notify = check_notification_preferences(participant_id, 'message')

        if should_notify:
          # Send push notification
          send_push_notification(
              participant_id,
              sender_name,
              content[:100] + ('...' if len(content) > 100 else ''),
              {
                'chatId': chat_id,
                'messageId': message_id,
                'senderId': sender_id
              }
          )

        # Store notification in database regardless of push preference
        store_notification(
            participant_id,
            'message',
            sender_name,
            content,
            {
              'chatId': chat_id,
              'messageId': message_id,
              'senderId': sender_id
            }
        )
  except Exception as e:
    logger.error(f"Error processing new message: {str(e)}")

def process_group_invitation(message_data):
  """
  Process a group invitation and send notifications
  """
  # Implementation for group invitations
  pass

def process_friend_request(message_data):
  """
  Process a friend request and send notifications
  """
  # Implementation for friend requests
  pass

def check_notification_preferences(user_id, notification_type):
  """
  Check if user has enabled notifications for this type
  """
  try:
    pref_ref = db.collection('notification_preferences').document(user_id)
    pref = pref_ref.get()

    if pref.exists:
      pref_data = pref.to_dict()

      # Check global push setting
      push_enabled = pref_data.get('pushEnabled', True)
      if not push_enabled:
        return False

      # Check mute until time
      mute_until = pref_data.get('muteUntil')
      if mute_until and datetime.now(timezone.utc) < mute_until:
        return False

      # Check specific notification type
      if notification_type == 'message':
        return pref_data.get('messageNotifications', True)
      elif notification_type == 'group_invitation':
        return pref_data.get('groupNotifications', True)
      elif notification_type == 'friend_request':
        return pref_data.get('friendRequestNotifications', True)
      elif notification_type == 'system':
        return pref_data.get('systemNotifications', True)

      return True

    # Default to enabled if no preferences found
    return True

  except Exception as e:
    logger.error(f"Error checking notification preferences: {str(e)}")
    return True  # Default to enabled if error

def send_push_notification(user_id, title, body, data=None):
  """
  Send push notification to a user's devices
  """
  try:
    # Get user's device tokens
    tokens_ref = db.collection('device_tokens').where('userId', '==', user_id)
    tokens = tokens_ref.stream()

    device_tokens = {}
    for token_doc in tokens:
      token_data = token_doc.to_dict()
      device_type = token_data.get('deviceType')
      token = token_data.get('token')

      if device_type and token:
        if device_type not in device_tokens:
          device_tokens[device_type] = []
        device_tokens[device_type].append(token)

    # Send notifications through FCM for each platform
    for platform, tokens in device_tokens.items():
      for token in tokens:
        try:
          message = messaging.Message(
              notification=messaging.Notification(
                  title=title,
                  body=body
              ),
              data=data,
              token=token
          )

          response = messaging.send(message)
          logger.info(f"Successfully sent FCM message: {response}")
        except Exception as e:
          logger.error(f"Error sending FCM message to {token}: {str(e)}")
          # If token is invalid, remove it
          if "Registration token not valid" in str(e):
            db.collection('device_tokens').document(token_doc.id).delete()
            logger.info(f"Deleted invalid token: {token}")

  except Exception as e:
    logger.error(f"Error sending push notification: {str(e)}")

def store_notification(user_id, type, title, body, data=None):
  """
  Store notification in Firestore for retrieval when user comes online
  """
  try:
    from datetime import datetime, timezone
    import uuid

    notification_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    notification_data = {
      'notificationId': notification_id,
      'userId': user_id,
      'type': type,
      'title': title,
      'body': body,
      'data': data,
      'isRead': False,
      'createdAt': now
    }

    # Store in Firestore
    db.collection('notifications').document(notification_id).set(notification_data)

    # Update user's unread notification count
    user_ref = db.collection('users').document(user_id)
    user = user_ref.get()

    if user.exists:
      user_data = user.to_dict()
      unread_count = user_data.get('unreadNotifications', 0)
      user_ref.update({'unreadNotifications': unread_count + 1})

    logger.info(f"Stored notification {notification_id} for user {user_id}")
    return notification_id

  except Exception as e:
    logger.error(f"Error storing notification: {str(e)}")
    return None