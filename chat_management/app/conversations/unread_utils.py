import asyncio
import logging
from typing import Dict, List, Optional

from fastapi import HTTPException, status

from ..firebase import firestore_db

logger = logging.getLogger(__name__)

async def recompute_unread_count(conversation_id: str, user_id: str) -> int:
    """
    Recompute the unread count for a user in a conversation
    This function counts messages that don't have the user in the readBy array
    
    Args:
        conversation_id: The ID of the conversation
        user_id: The ID of the user
        
    Returns:
        int: The actual unread count
        
    Raises:
        Exception: If there's an error accessing Firestore
    """
    try:
        messages_ref = firestore_db.collection('conversations').document(conversation_id).collection('messages')
        all_messages = await asyncio.to_thread(messages_ref.get)
        
        # Count messages that don't have the user in readBy array
        unread_count = 0
        for msg in all_messages:
            msg_data = msg.to_dict()
            read_by = msg_data.get('readBy', [])
            if user_id not in read_by:
                unread_count += 1
        
        # Update the unread count in user_stats
        user_stats_ref = firestore_db.collection('conversations').document(conversation_id) \
                        .collection('user_stats').document(user_id)
        
        user_stats = await asyncio.to_thread(user_stats_ref.get)
        
        if user_stats.exists:
            stored_count = user_stats.to_dict().get('unreadCount', 0)
            # Only update if counts don't match
            if stored_count != unread_count:
                await asyncio.to_thread(user_stats_ref.update, {'unreadCount': unread_count})
                logger.info(f"Fixed unread count for user {user_id} in conversation {conversation_id} from {stored_count} to {unread_count}")
        else:
            # Create new user stats document
            await asyncio.to_thread(user_stats_ref.set, {
                'unreadCount': unread_count,
                'lastReadMessageId': None
            })
            logger.info(f"Created user stats for user {user_id} in conversation {conversation_id} with unread count {unread_count}")
        
        return unread_count
    except Exception as e:
        logger.error(f"Error recomputing unread count: {str(e)}")
        raise e

async def recompute_all_user_unread_counts(user_id: str, specific_conversation_id: Optional[str] = None) -> Dict:
    """
    Recompute unread counts for all conversations a user participates in,
    or for a specific conversation if conversation_id is provided
    
    Args:
        user_id: The ID of the user
        specific_conversation_id: Optional ID of a specific conversation to recompute
        
    Returns:
        dict: Statistics about the recomputation
        
    Raises:
        HTTPException: If the conversation doesn't exist or user is not a participant
        Exception: For database errors
    """
    fixed_counts = 0
    processed_conversations = 0
    results = []
    
    try:
        if specific_conversation_id:
            # Verify the conversation exists
            conversation_ref = firestore_db.collection('conversations').document(specific_conversation_id)
            conversation = await asyncio.to_thread(conversation_ref.get)
            
            if not conversation.exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found"
                )
            
            # Verify the user is a participant
            conversation_data = conversation.to_dict()
            if user_id not in conversation_data.get('participants', []):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not a participant in this conversation"
                )
            
            # Recompute unread count for this conversation
            old_count = 0
            user_stats_ref = conversation_ref.collection('user_stats').document(user_id)
            user_stats = await asyncio.to_thread(user_stats_ref.get)
            
            if user_stats.exists:
                old_count = user_stats.to_dict().get('unreadCount', 0)
            
            new_count = await recompute_unread_count(specific_conversation_id, user_id)
            
            if old_count != new_count:
                fixed_counts += 1
            
            processed_conversations = 1
            results.append({
                'conversation_id': specific_conversation_id,
                'old_count': old_count,
                'new_count': new_count,
                'fixed': old_count != new_count
            })
        else:
            # Get all conversations for the user
            conversations_ref = firestore_db.collection('conversations')
            query = conversations_ref.where('participants', 'array_contains', user_id)
            conversations = await asyncio.to_thread(query.get)
            
            # Process each conversation
            for conversation in conversations:
                conversation_id = conversation.id
                try:
                    # Get current unread count
                    old_count = 0
                    user_stats_ref = firestore_db.collection('conversations').document(conversation_id) \
                                    .collection('user_stats').document(user_id)
                    user_stats = await asyncio.to_thread(user_stats_ref.get)
                    
                    if user_stats.exists:
                        old_count = user_stats.to_dict().get('unreadCount', 0)
                    
                    # Recompute the actual count
                    new_count = await recompute_unread_count(conversation_id, user_id)
                    
                    if old_count != new_count:
                        fixed_counts += 1
                    
                    processed_conversations += 1
                    results.append({
                        'conversation_id': conversation_id,
                        'old_count': old_count,
                        'new_count': new_count,
                        'fixed': old_count != new_count
                    })
                except Exception as e:
                    logger.error(f"Error processing conversation {conversation_id}: {str(e)}")
                    # Continue with next conversation
        
        return {
            'status': 'success',
            'processed_conversations': processed_conversations,
            'fixed_counts': fixed_counts,
            'details': results
        }
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error recomputing unread counts: {str(e)}")
        raise e

async def find_inconsistent_unread_counts() -> List[Dict]:
    """
    Scan all conversations and find inconsistencies between stored unread counts
    and actual unread message counts.
    
    This is a maintenance function to identify problems in the database.
    
    Returns:
        List[Dict]: List of inconsistencies found
    """
    inconsistencies = []
    
    try:
        # Get all conversations
        conversations_ref = firestore_db.collection('conversations')
        conversations = await asyncio.to_thread(conversations_ref.get)
        
        for conversation in conversations:
            conversation_id = conversation.id
            conversation_data = conversation.to_dict()
            participants = conversation_data.get('participants', [])
            
            # Check each participant
            for user_id in participants:
                try:
                    # Get stored unread count
                    user_stats_ref = firestore_db.collection('conversations').document(conversation_id) \
                                   .collection('user_stats').document(user_id)
                    user_stats = await asyncio.to_thread(user_stats_ref.get)
                    
                    if not user_stats.exists:
                        # User stats don't exist, this is an inconsistency
                        inconsistencies.append({
                            'conversation_id': conversation_id,
                            'user_id': user_id,
                            'type': 'missing_user_stats',
                            'stored_count': None,
                            'actual_count': None  # Will be computed later
                        })
                        continue
                    
                    stored_count = user_stats.to_dict().get('unreadCount', 0)
                    
                    # Count actual unread messages
                    messages_ref = firestore_db.collection('conversations').document(conversation_id) \
                                 .collection('messages')
                    all_messages = await asyncio.to_thread(messages_ref.get)
                    
                    actual_unread_count = 0
                    for msg in all_messages:
                        msg_data = msg.to_dict()
                        read_by = msg_data.get('readBy', [])
                        if user_id not in read_by:
                            actual_unread_count += 1
                    
                    # Check if counts match
                    if stored_count != actual_unread_count:
                        inconsistencies.append({
                            'conversation_id': conversation_id,
                            'user_id': user_id,
                            'type': 'count_mismatch',
                            'stored_count': stored_count,
                            'actual_count': actual_unread_count
                        })
                        
                except Exception as e:
                    logger.error(f"Error checking conversation {conversation_id} for user {user_id}: {str(e)}")
                    # Continue with next user
        
        return inconsistencies
    except Exception as e:
        logger.error(f"Error finding inconsistencies: {str(e)}")
        raise e

async def repair_all_unread_counts() -> Dict:
    """
    Find and fix all unread count inconsistencies in the database
    
    Returns:
        Dict: Statistics about the repair operation
    """
    try:
        # Find all inconsistencies
        inconsistencies = await find_inconsistent_unread_counts()
        
        fixed_count = 0
        details = []
        
        # Fix each inconsistency
        for item in inconsistencies:
            conversation_id = item['conversation_id']
            user_id = item['user_id']
            
            try:
                # Recompute and update
                new_count = await recompute_unread_count(conversation_id, user_id)
                fixed_count += 1
                details.append({
                    'conversation_id': conversation_id,
                    'user_id': user_id,
                    'old_count': item.get('stored_count'),
                    'new_count': new_count,
                    'type': item.get('type', 'unknown')
                })
            except Exception as e:
                logger.error(f"Error fixing inconsistency for conversation {conversation_id}, user {user_id}: {str(e)}")
                # Continue with next inconsistency
        
        return {
            'status': 'success',
            'total_inconsistencies': len(inconsistencies),
            'fixed_count': fixed_count,
            'details': details
        }
    except Exception as e:
        logger.error(f"Error repairing unread counts: {str(e)}")
        raise e
