import asyncio
import logging
import os
import signal
import sys

from .service import NotificationConsumerService

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("notification_consumer")

# Global flag for graceful shutdown
should_exit = False

def signal_handler(sig, frame):
    """Handle termination signals for graceful shutdown"""
    global should_exit
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    should_exit = True

async def main():
    """Main entry point for the notification consumer service"""
    global should_exit
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Starting Notification Consumer Service")
    
    try:
        # Initialize the notification consumer service
        service = NotificationConsumerService()
        
        # Start processing notifications
        consumer_task = asyncio.create_task(service.start_processing())
        
        # Monitor for shutdown signal
        while not should_exit:
            await asyncio.sleep(1)
            
        # Cancel the consumer task for graceful shutdown
        logger.info("Shutting down, cancelling tasks...")
        consumer_task.cancel()
        
        try:
            await consumer_task
        except asyncio.CancelledError:
            logger.info("Consumer task cancelled successfully")
            
    except Exception as e:
        logger.error(f"Error in main process: {str(e)}")
        sys.exit(1)
        
    logger.info("Notification Consumer Service has shut down gracefully")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Service stopped by keyboard interrupt")
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        sys.exit(1)
