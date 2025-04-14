import json
import logging
import os
import socket
from typing import Dict, Any, List

import boto3

logger = logging.getLogger(__name__)

class ChatManagementClient:
    """
    Client for AWS Elastic Solution chat_management service
    Replaces Redis functionality for WebSocket cross-instance communication and state management
    """
    def __init__(self):
        """
        Initialize chat_management client with connection settings from environment variables
        """
        # Get ElastiCache configuration from environment variables
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.instance_id = os.getenv("INSTANCE_ID", socket.gethostname())
        
        # AWS credentials
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
        
        # ElastiCache/chat_management service configurations
        self.service_endpoint = os.getenv("CHAT_MANAGEMENT_ENDPOINT", "")
        
        try:
            # Initialize the AWS ElastiCache client
            self.client = boto3.client(
                'elasticache',
                region_name=self.region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key
            )
            
            # Create a boto3 resource for the chat management service
            self.chat_management = boto3.resource(
                'dynamodb',  # Using DynamoDB as the underlying storage
                region_name=self.region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key
            )
            
            # Initialize connection status
            logger.info(f"chat_management client initialized for instance {self.instance_id}")
            self._test_connection()
        except Exception as e:
            logger.error(f"Failed to initialize chat_management client: {str(e)}")
            self.client = None
            
    def _test_connection(self) -> bool:
        """Test the connection to the chat_management service"""
        try:
            # Simple test operation
            self.client.describe_cache_engine_versions(
                Engine='redis',
                MaxRecords=1
            )
            logger.info("Successfully connected to AWS ElastiCache")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to AWS ElastiCache: {str(e)}")
            return False
    
    def is_connected(self) -> bool:
        """
        Check if the chat_management service connection is active
        """
        if not self.client:
            return False
        
        try:
            return self._test_connection()
        except Exception:
            return False
    
    async def publish(self, channel: str, data: Dict[str, Any]) -> bool:
        """
        Publish a message to a channel
        
        Args:
            channel: The channel to publish to
            data: The data to publish (will be JSON serialized)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning(f"Cannot publish to {channel}: chat_management service not connected")
            return False
        
        try:
            # Convert dict to JSON string
            json_data = json.dumps(data)
            
            # Structure for storing message in the messaging table
            message_item = {
                'channel': channel,
                'message': json_data,
                'timestamp': self._get_current_timestamp(),
                'instance_id': self.instance_id
            }
            
            # Send message to the messaging table
            table = self.chat_management.Table('chat_messages')
            table.put_item(Item=message_item)
            
            logger.debug(f"Published message to channel {channel}")
            return True
                
        except Exception as e:
            logger.error(f"Error publishing to {channel}: {str(e)}")
            return False
    
    async def subscribe(self, channel: str) -> bool:
        """
        Subscribe this instance to a channel
        
        Args:
            channel: The channel to subscribe to
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning(f"Cannot subscribe to {channel}: chat_management service not connected")
            return False
        
        try:
            # Add this instance to the channel's subscribers
            table = self.chat_management.Table('channel_subscriptions')
            item = {
                'channel': channel,
                'instance_id': self.instance_id,
                'timestamp': self._get_current_timestamp()
            }
            
            table.put_item(Item=item)
            
            logger.info(f"Instance {self.instance_id} subscribed to channel {channel}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to {channel}: {str(e)}")
            return False
    
    async def unsubscribe(self, channel: str) -> bool:
        """
        Unsubscribe this instance from a channel
        
        Args:
            channel: The channel to unsubscribe from
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning(f"Cannot unsubscribe from {channel}: chat_management service not connected")
            return False
        
        try:
            # Remove this instance from the channel's subscribers
            table = self.chat_management.Table('channel_subscriptions')
            table.delete_item(
                Key={
                    'channel': channel,
                    'instance_id': self.instance_id
                }
            )
            
            logger.info(f"Instance {self.instance_id} unsubscribed from channel {channel}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from {channel}: {str(e)}")
            return False
    
    async def get_channel_subscribers(self, channel: str) -> List[str]:
        """
        Get all instances subscribed to a channel
        
        Args:
            channel: The channel to get subscribers for
            
        Returns:
            List[str]: List of instance IDs subscribed to the channel
        """
        if not self.is_connected():
            logger.warning(f"Cannot get subscribers for {channel}: chat_management service not connected")
            return []
        
        try:
            table = self.chat_management.Table('channel_subscriptions')
            response = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('channel').eq(channel)
            )
            
            subscribers = [item['instance_id'] for item in response.get('Items', [])]
            return subscribers
        except Exception as e:
            logger.error(f"Error getting subscribers for {channel}: {str(e)}")
            return []
    
    async def add_user_to_conversation(self, user_id: str, conversation_id: str) -> bool:
        """
        Associate a user with a conversation (for tracking which users belong to which conversations)
        
        Args:
            user_id: The user ID
            conversation_id: The conversation ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning(f"Cannot add user {user_id} to conversation {conversation_id}: chat_management service not connected")
            return False
        
        try:
            table = self.chat_management.Table('user_conversations')
            item = {
                'user_id': user_id,
                'conversation_id': conversation_id,
                'timestamp': self._get_current_timestamp()
            }
            
            table.put_item(Item=item)
            
            logger.debug(f"Added user {user_id} to conversation {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding user {user_id} to conversation {conversation_id}: {str(e)}")
            return False
    
    async def remove_user_from_conversation(self, user_id: str, conversation_id: str) -> bool:
        """
        Remove a user's association with a conversation
        
        Args:
            user_id: The user ID
            conversation_id: The conversation ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning(f"Cannot remove user {user_id} from conversation {conversation_id}: chat_management service not connected")
            return False
        
        try:
            table = self.chat_management.Table('user_conversations')
            table.delete_item(
                Key={
                    'user_id': user_id,
                    'conversation_id': conversation_id
                }
            )
            
            logger.debug(f"Removed user {user_id} from conversation {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing user {user_id} from conversation {conversation_id}: {str(e)}")
            return False
    
    async def get_user_conversations(self, user_id: str) -> List[str]:
        """
        Get all conversations a user is part of
        
        Args:
            user_id: The user ID
            
        Returns:
            List[str]: List of conversation IDs the user is part of
        """
        if not self.is_connected():
            logger.warning(f"Cannot get conversations for user {user_id}: chat_management service not connected")
            return []
        
        try:
            table = self.chat_management.Table('user_conversations')
            response = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('user_id').eq(user_id)
            )
            
            conversations = [item['conversation_id'] for item in response.get('Items', [])]
            return conversations
        except Exception as e:
            logger.error(f"Error getting conversations for user {user_id}: {str(e)}")
            return []
    
    async def track_user_connection(self, user_id: str, connection_id: str, metadata: Dict[str, Any] = None) -> bool:
        """
        Track a user's connection to this instance
        
        Args:
            user_id: The user ID
            connection_id: The unique connection ID
            metadata: Optional metadata about the connection
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning(f"Cannot track connection for user {user_id}: chat_management service not connected")
            return False
        
        try:
            if metadata is None:
                metadata = {}
                
            table = self.chat_management.Table('user_connections')
            item = {
                'user_id': user_id,
                'connection_id': connection_id,
                'instance_id': self.instance_id,
                'timestamp': self._get_current_timestamp(),
                'metadata': metadata
            }
            
            table.put_item(Item=item)
            
            logger.debug(f"Tracked connection {connection_id} for user {user_id} on instance {self.instance_id}")
            return True
        except Exception as e:
            logger.error(f"Error tracking connection for user {user_id}: {str(e)}")
            return False
    
    async def remove_user_connection(self, user_id: str, connection_id: str) -> bool:
        """
        Remove a tracked user connection
        
        Args:
            user_id: The user ID
            connection_id: The unique connection ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning(f"Cannot remove connection for user {user_id}: chat_management service not connected")
            return False
        
        try:
            table = self.chat_management.Table('user_connections')
            table.delete_item(
                Key={
                    'user_id': user_id,
                    'connection_id': connection_id
                }
            )
            
            logger.debug(f"Removed connection {connection_id} for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing connection for user {user_id}: {str(e)}")
            return False
    
    async def get_user_connections(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all connections for a user across all instances
        
        Args:
            user_id: The user ID
            
        Returns:
            List[Dict[str, Any]]: List of connection data for the user
        """
        if not self.is_connected():
            logger.warning(f"Cannot get connections for user {user_id}: chat_management service not connected")
            return []
        
        try:
            table = self.chat_management.Table('user_connections')
            response = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('user_id').eq(user_id)
            )
            
            connections = response.get('Items', [])
            return connections
        except Exception as e:
            logger.error(f"Error getting connections for user {user_id}: {str(e)}")
            return []
    
    async def get_connection_stats(self) -> Dict[str, Any]:
        """
        Get statistics about user connections across all instances
        
        Returns:
            Dict[str, Any]: Connection statistics
        """
        if not self.is_connected():
            logger.warning("Cannot get connection stats: chat_management service not connected")
            return {
                "error": "Service not connected",
                "connected": False
            }
        
        try:
            # Get stats from the user_connections table
            table = self.chat_management.Table('user_connections')
            
            # Count total connections (for demonstration)
            scan_response = table.scan(Select='COUNT')
            total_connections = scan_response.get('Count', 0)
            
            # Get unique user count (for demonstration)
            # In a real implementation, this would use more efficient approaches
            response = table.scan(ProjectionExpression='user_id')
            unique_users = len(set([item['user_id'] for item in response.get('Items', [])]))
            
            # Get connections for this instance
            instance_connections = []
            scan_kwargs = {
                'FilterExpression': boto3.dynamodb.conditions.Attr('instance_id').eq(self.instance_id)
            }
            response = table.scan(**scan_kwargs)
            instance_connections.extend(response.get('Items', []))
            
            # Continue scanning if we have more items (pagination)
            while 'LastEvaluatedKey' in response:
                scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
                response = table.scan(**scan_kwargs)
                instance_connections.extend(response.get('Items', []))
            
            return {
                "connected": True,
                "instance_id": self.instance_id,
                "total_connections": total_connections,
                "unique_users": unique_users,
                "instance_connection_count": len(instance_connections),
                "timestamp": self._get_current_timestamp()
            }
        except Exception as e:
            logger.error(f"Error getting connection stats: {str(e)}")
            return {
                "error": str(e),
                "connected": False,
                "instance_id": self.instance_id,
                "timestamp": self._get_current_timestamp()
            }
    
    def _get_current_timestamp(self) -> int:
        """Get current timestamp in milliseconds"""
        import time
        return int(time.time() * 1000)

# Singleton instance
chat_management_client = ChatManagementClient()
