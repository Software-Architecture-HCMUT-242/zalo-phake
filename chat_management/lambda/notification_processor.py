import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
import firebase_admin
from firebase_admin import credentials, firestore, messaging

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
      logger.info("Firebase initialized successfully")
    else:
      logger.error("Environment variable FIREBASE_SECRET is not set")
except Exception as e:
  logger.error(f"Failed to initialize Firebase: {str(e)}")

# Initialize Firestore
db = firestore.client()

# Initialize SNS client
try:
  sns = boto3.client(
      'sns',
      region_name=os.environ.get('AWS_REGION', 'ap-southeast-1')
  )
  logger.info("AWS SNS client initialized")
except Exception as e:
  logger.error(f"Failed to initialize SNS client: {str(e)}")
  sns = None

def lambda_handler(event, context):
  """
  AWS Lambda handler for processing SQS messages and sending notifications
  """
  logger.info(f"Received event with {len(event.get('Records', []))} records")

  success_count = 0
  fail_count = 0

  # Process each SQS message
  for record in event.get('Records', []):
    try:
      # Parse the SQS message body
      body = json.loads(record.get('body', '{}'))
      logger.info(f"Processing message type: {body.get('event')}")

      event_type = body.get('event')

      if event_type == 'new_message':
        if process_new_message(body):
          success_count += 1
        else:
          fail_count += 1
      elif event_type == 'group_invitation':
        if process_group_invitation(body):
          success_count += 1
        else:
          fail_count += 1
      elif event_type == 'friend_request':
        if process_friend_request(body):
          success_count += 1
        else:
          fail_count += 1
      else:
        logger.warning(f"Unknown event type: {event_type}")
        fail_count += 1

    except json.JSONDecodeError as e:
      logger.error(f"Invalid JSON in SQS message body: {str(e)}")
      fail_count += 1
    except Exception as e:
      logger.error(f"Unexpected error processing SQS message: {str(e)}")
      fail_count += 1

  logger.info(f"Processed {success_count} messages successfully, {fail_count} failed")

  return {
    'statusCode': 200,
    'body': json.dumps({
      'processed': success_count + fail_count,
      'successful': success_count,
      'failed': fail_count
    })
  }

def process_new_message(message_data):
  """
  Process a new chat message and send notifications to offline users

  Args:
      message_data (dict): The message data from SQS

  Returns:
      bool: True if processing was successful, False otherwise
  """
  try:
    # Extract necessary data
    chat_id = message_data.get('chatId')
    message_id = message_data.get('messageId')
    sender_id = message_data.get('senderId')
    content = message_data.get('content')
    participants = message_data.get('participants', [])

    # Validate required fields
    if not all([chat_id, message_id, sender_id, content, participants]):
      logger.error(f"Missing required fields in message data: {message_data}")
      return False

    logger.info(f"Processing new message notification for chat {chat_id}")

    # Get chat details for notification context
    chat_ref = db.collection('chats').document(chat_id)
    chat = chat_ref.get()

    if not chat.exists:
      logger.error(f"Chat {chat_id} not found")
      return False

    # Get sender details
    sender_ref = db.collection('users').document(sender_id)
    sender = sender_ref.get()
    sender_name = sender_id  # Default to sender ID if name not found

    if sender.exists:
      sender_data = sender.to_dict()
      sender_name = sender_data.get('name', sender_id)

    # Track successful notifications
    notification_success = True

    # Send notifications to all participants except sender
    for participant_id in participants:
      if participant_id == sender_id:
        continue  # Skip sender

      # Check if user is online
      user_ref = db.collection('users').document(participant_id)
      user = user_ref.get()

      if not user.exists:
        logger.warning(f"User {participant_id} not found, skipping notification")
        continue

      user_data = user.to_dict()
      is_online = user_data.get('isOnline', False)

      # If user is offline, send push notification
      if not is_online:
        # Check notification preferences
        should_notify = check_notification_preferences(participant_id, 'message')

        if should_notify:
          # Send push notification
          notification_success = notification_success and send_push_notification(
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

    return notification_success

  except Exception as e:
    logger.error(f"Error processing new message: {str(e)}")
    return False

def process_group_invitation(message_data):
  """
  Process a group invitation notification

  Args:
      message_data (dict): The message data from SQS

  Returns:
      bool: True if processing was successful, False otherwise
  """
  try:
    # Extract necessary data
    group_id = message_data.get('groupId')
    sender_id = message_data.get('senderId')
    invitee_id = message_data.get('inviteeId')
    group_name = message_data.get('groupName', 'a group')

    # Validate required fields
    if not all([group_id, sender_id, invitee_id]):
      logger.error(f"Missing required fields in group invitation data: {message_data}")
      return False

    logger.info(f"Processing group invitation notification for group {group_id}")

    # Get sender details
    sender_ref = db.collection('users').document(sender_id)
    sender = sender_ref.get()
    sender_name = sender_id  # Default to sender ID if name not found

    if sender.exists:
      sender_data = sender.to_dict()
      sender_name = sender_data.get('name', sender_id)

    # Check if user is online
    user_ref = db.collection('users').document(invitee_id)
    user = user_ref.get()

    if not user.exists:
      logger.warning(f"User {invitee_id} not found, skipping notification")
      return False

    user_data = user.to_dict()
    is_online = user_data.get('isOnline', False)

    # Prepare notification content
    title = f"{sender_name}"
    body = f"invited you to join {group_name}"

    # If user is offline, send push notification
    if not is_online:
      # Check notification preferences
      should_notify = check_notification_preferences(invitee_id, 'group_invitation')

      if should_notify:
        # Send push notification
        send_push_notification(
            invitee_id,
            title,
            body,
            {
              'groupId': group_id,
              'senderId': sender_id,
              'type': 'group_invitation'
            }
        )

    # Store notification in database
    store_notification(
        invitee_id,
        'group_invitation',
        title,
        body,
        {
          'groupId': group_id,
          'senderId': sender_id
        }
    )

    return True

  except Exception as e:
    logger.error(f"Error processing group invitation: {str(e)}")
    return False

def process_friend_request(message_data):
  """
  Process a friend request notification

  Args:
      message_data (dict): The message data from SQS

  Returns:
      bool: True if processing was successful, False otherwise
  """
  try:
    # Extract necessary data
    sender_id = message_data.get('senderId')
    recipient_id = message_data.get('recipientId')

    # Validate required fields
    if not all([sender_id, recipient_id]):
      logger.error(f"Missing required fields in friend request data: {message_data}")
      return False

    logger.info(f"Processing friend request notification from {sender_id} to {recipient_id}")

    # Get sender details
    sender_ref = db.collection('users').document(sender_id)
    sender = sender_ref.get()
    sender_name = sender_id  # Default to sender ID if name not found

    if sender.exists:
      sender_data = sender.to_dict()
      sender_name = sender_data.get('name', sender_id)

    # Check if recipient is online
    user_ref = db.collection('users').document(recipient_id)
    user = user_ref.get()

    if not user.exists:
      logger.warning(f"User {recipient_id} not found, skipping notification")
      return False

    user_data = user.to_dict()
    is_online = user_data.get('isOnline', False)

    # Prepare notification content
    title = f"{sender_name}"
    body = "sent you a friend request"

    # If user is offline, send push notification
    if not is_online:
      # Check notification preferences
      should_notify = check_notification_preferences(recipient_id, 'friend_request')

      if should_notify:
        # Send push notification
        send_push_notification(
            recipient_id,
            title,
            body,
            {
              'senderId': sender_id,
              'type': 'friend_request'
            }
        )

    # Store notification in database
    store_notification(
        recipient_id,
        'friend_request',
        title,
        body,
        {
          'senderId': sender_id
        }
    )

    return True

  except Exception as e:
    logger.error(f"Error processing friend request: {str(e)}")
    return False

def check_notification_preferences(user_id, notification_type):
  """
  Check if user has enabled notifications for this type

  Args:
      user_id (str): The user ID
      notification_type (str): The type of notification (message, group_invitation, etc.)

  Returns:
      bool: True if notifications should be sent, False otherwise
  """
  try:
    # Get user's notification preferences
    pref_ref = db.collection('notification_preferences').document(user_id)
    pref = pref_ref.get()

    if pref.exists:
      pref_data = pref.to_dict()

      # Check global push setting
      push_enabled = pref_data.get('pushEnabled', True)
      if not push_enabled:
        logger.info(f"Push notifications disabled for user {user_id}")
        return False

      # Check mute until time
      mute_until = pref_data.get('muteUntil')
      if mute_until and isinstance(mute_until, datetime) and datetime.now(timezone.utc) < mute_until:
        logger.info(f"Notifications muted for user {user_id} until {mute_until}")
        return False
      elif mute_until and isinstance(mute_until, firestore.Timestamp) and datetime.now(timezone.utc) < mute_until.datetime():
        logger.info(f"Notifications muted for user {user_id} until {mute_until.datetime()}")
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

    # Default to enabled if no preferences found
    return True

  except Exception as e:
    logger.error(f"Error checking notification preferences for user {user_id}: {str(e)}")
    return True  # Default to enabled in case of error

def send_push_notification(user_id, title, body, data=None):
  """
  Send push notification to a user's devices

  Args:
      user_id (str): The user ID
      title (str): The notification title
      body (str): The notification body
      data (dict, optional): Additional data to include with the notification

  Returns:
      bool: True if at least one notification was sent successfully, False otherwise
  """
  try:
    logger.info(f"Sending push notification to user {user_id}")

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
        device_tokens[device_type].append((token, token_doc.id))

    if not device_tokens:
      logger.info(f"No device tokens found for user {user_id}")
      return False

    success = False

    # Send notifications through appropriate channels based on device type
    for platform, tokens in device_tokens.items():
      for token_info in tokens:
        token, doc_id = token_info
        try:
          # For iOS and Android, use Firebase Cloud Messaging
          if platform in ['ios', 'android']:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body
                ),
                data=data or {},
                token=token
            )

            response = messaging.send(message)
            logger.info(f"Successfully sent FCM message to {platform} device: {response}")
            success = True

          # For web, use AWS SNS if available
          elif platform == 'web' and sns:
            sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
            if not sns_topic_arn:
              logger.warning("SNS_TOPIC_ARN environment variable not set")
              continue

            payload = {
              'default': f"{title}: {body}",
              'GCM': json.dumps({
                'notification': {
                  'title': title,
                  'body': body
                },
                'data': data or {}
              })
            }

            response = sns.publish(
                TopicArn=sns_topic_arn,
                Message=json.dumps(payload),
                MessageStructure='json'
            )

            logger.info(f"Successfully sent SNS message: {response}")
            success = True

        except messaging.ApiCallError as fcm_error:
          logger.error(f"Firebase messaging error: {str(fcm_error)}")

          # Handle invalid token errors
          if hasattr(fcm_error, 'code') and fcm_error.code in [
            'registration-token-not-registered',
            'invalid-argument',
            'invalid-registration-token'
          ]:
            logger.info(f"Removing invalid token: {token}")
            db.collection('device_tokens').document(doc_id).delete()

        except Exception as e:
          logger.error(f"Error sending push notification to {platform} device: {str(e)}")

    return success

  except Exception as e:
    logger.error(f"Error in send_push_notification: {str(e)}")
    return False

def store_notification(user_id, type, title, body, data=None):
  """
  Store notification in Firestore for retrieval when user comes online

  Args:
      user_id (str): The user ID
      type (str): The notification type
      title (str): The notification title
      body (str): The notification body
      data (dict, optional): Additional data to include with the notification

  Returns:
      str: The notification ID if successful, None otherwise
  """
  try:
    notification_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    notification_data = {
      'notificationId': notification_id,
      'userId': user_id,
      'type': type,
      'title': title,
      'body': body,
      'data': data or {},
      'isRead': False,
      'createdAt': now
    }

    # Store in Firestore
    db.collection('notifications').document(notification_id).set(notification_data)

    # Update user's unread notification count
    user_ref = db.collection('users').document(user_id)
    transaction = db.transaction()

    @firestore.transactional
    def update_unread_count(transaction, user_ref):
      user_doc = user_ref.get(transaction=transaction)
      if user_doc.exists:
        user_data = user_doc.to_dict()
        unread_count = user_data.get('unreadNotifications', 0)
        transaction.update(user_ref, {'unreadNotifications': unread_count + 1})

    try:
      update_unread_count(transaction, user_ref)
      logger.info(f"Updated unread count for user {user_id}")
    except Exception as e:
      logger.error(f"Error updating unread count: {str(e)}")

    logger.info(f"Stored notification {notification_id} for user {user_id}")
    return notification_id

  except Exception as e:
    logger.error(f"Error storing notification: {str(e)}")
    return None