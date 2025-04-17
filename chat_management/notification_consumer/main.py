import json
import logging
import logging.config
import os
import signal
import sys
import time
from typing import Dict

import tenacity
from pythonjsonlogger import jsonlogger

from config import settings
from event_processor import EventProcessor
from firebase_client import FirebaseClient
from sqs_client import SQSClient

# Configure logging
def setup_logging():
    """Configure logging for the application."""
    log_level = getattr(logging, settings.log_level.upper())
    
    # Create JSON formatter for structured logging
    class CustomJsonFormatter(jsonlogger.JsonFormatter):
        def add_fields(self, log_record, record, message_dict):
            super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
            log_record['service'] = settings.service_name
            log_record['environment'] = settings.environment
            log_record['timestamp'] = time.strftime(
                '%Y-%m-%dT%H:%M:%S.%fZ', time.gmtime()
            )
    
    # Configure logging
    handler = logging.StreamHandler()
    handler.setFormatter(CustomJsonFormatter('%(timestamp)s %(levelname)s %(service)s %(environment)s %(name)s %(message)s'))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers to avoid duplicates
    for h in root_logger.handlers:
        root_logger.removeHandler(h)
    
    root_logger.addHandler(handler)
    
    # Set specific logger levels
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

# Create logger
logger = logging.getLogger(__name__)

# Handle graceful shutdown
running = True

def signal_handler(sig, frame):
    """Handle termination signals for graceful shutdown."""
    global running
    logger.info("Shutdown signal received, finishing current batch...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class NotificationConsumer:
    """Main notification consumer service."""
    
    def __init__(self):
        """Initialize the notification consumer service."""
        self.sqs_client = SQSClient()
        self.firebase_client = FirebaseClient()
        self.event_processor = EventProcessor(
            firebase_client=self.firebase_client,
            sqs_client=self.sqs_client
        )
        logger.info("Notification Consumer Service initialized")
    
    def process_messages(self, max_messages: int = None) -> int:
        """
        Process a batch of messages from the queue.
        
        Args:
            max_messages: Maximum number of messages to process (1-10)
            
        Returns:
            Number of messages processed successfully
        """
        # Use default if not specified
        max_messages = max_messages or settings.sqs_max_messages
        
        # Receive messages
        messages = self.sqs_client.receive_messages(
            queue_url=settings.main_queue_url,
            max_messages=max_messages
        )
        
        if not messages:
            return 0
        
        # Process each message
        success_count = 0
        for message in messages:
            if self.event_processor.process_event(message):
                success_count += 1
        
        logger.info(f"Processed {len(messages)} messages, {success_count} successful")
        return success_count
    
    def process_retry_messages(self, max_messages: int = None) -> int:
        """
        Process a batch of messages from the retry queue.
        
        Args:
            max_messages: Maximum number of messages to process (1-10)
            
        Returns:
            Number of messages processed successfully
        """
        # Use default if not specified
        max_messages = max_messages or settings.sqs_max_messages
        
        # Receive messages
        messages = self.sqs_client.receive_messages(
            queue_url=settings.retry_queue_url,
            max_messages=max_messages
        )
        
        if not messages:
            return 0
        
        # Process each message
        success_count = 0
        for message in messages:
            if self.event_processor.process_event(message):
                success_count += 1
        
        logger.info(f"Processed {len(messages)} retry messages, {success_count} successful")
        return success_count
    
    def run(self):
        """Run the consumer service in an infinite loop."""
        logger.info("Starting Notification Consumer Service")
        
        try:
            # Main processing loop
            while running:
                try:
                    # Process messages from main queue
                    main_count = self.process_messages()
                    
                    # Process messages from retry queue if no main messages
                    if main_count == 0:
                        retry_count = self.process_retry_messages()
                        
                        # If no messages from either queue, briefly sleep to avoid hammering SQS
                        if retry_count == 0:
                            time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error in message processing loop: {str(e)}")
                    time.sleep(5)  # Sleep before retrying after error
            
            logger.info("Notification Consumer Service shutdown gracefully")
            
        except Exception as e:
            logger.critical(f"Fatal error in Notification Consumer Service: {str(e)}")
            return 1
        
        return 0

def main():
    """Main entry point for the application."""
    # Configure logging
    setup_logging()
    
    # Log startup information
    logger.info(f"Starting Notification Consumer Service in {settings.environment} environment")
    
    # Create and run consumer
    consumer = NotificationConsumer()
    exit_code = consumer.run()
    
    return exit_code

if __name__ == "__main__":
    sys.exit(main())