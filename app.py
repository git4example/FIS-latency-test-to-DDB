import boto3
import time
import logging
import os
from datetime import datetime
from botocore.config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get configuration from environment variables
CONNECTION_TIMEOUT = float(os.getenv('CONNECTION_TIMEOUT', '5.0'))  # seconds
READ_TIMEOUT = float(os.getenv('READ_TIMEOUT', '5.0'))  # seconds
TEST_INTERVAL = int(os.getenv('TEST_INTERVAL', '5'))  # seconds between tests

logger.info(f"Configuration: CONNECTION_TIMEOUT={CONNECTION_TIMEOUT}s, READ_TIMEOUT={READ_TIMEOUT}s, TEST_INTERVAL={TEST_INTERVAL}s")

# Configure boto3 client with custom timeouts
boto_config = Config(
    connect_timeout=CONNECTION_TIMEOUT,
    read_timeout=READ_TIMEOUT,
    retries={'max_attempts': 0}  # Disable retries to see immediate timeout behavior
)

# Initialize DynamoDB client with timeout configuration
dynamodb = boto3.client('dynamodb', region_name='us-east-1', config=boto_config)

def test_dynamodb_connection():
    """Test DynamoDB connection and measure round trip time"""
    start_time = time.time()
    try:
        # Simple ListTables operation to test connectivity
        response = dynamodb.list_tables(Limit=1)
        
        end_time = time.time()
        round_trip_ms = (end_time - start_time) * 1000
        
        logger.info(f"SUCCESS - Round trip time: {round_trip_ms:.2f}ms - Tables count: {len(response.get('TableNames', []))}")
        return True
        
    except Exception as e:
        end_time = time.time()
        round_trip_ms = (end_time - start_time) * 1000
        error_type = type(e).__name__
        
        # Log different error types with appropriate severity
        if 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
            logger.error(f"TIMEOUT - Round trip time: {round_trip_ms:.2f}ms - Error type: {error_type} - Message: {str(e)}")
        else:
            logger.error(f"FAILED - Round trip time: {round_trip_ms:.2f}ms - Error type: {error_type} - Message: {str(e)}")
        return False

def main():
    logger.info("Starting DynamoDB connection test application")
    logger.info(f"Configured for fault injection testing with {CONNECTION_TIMEOUT}s connection timeout")
    logger.info(f"Expected behavior: Timeouts will occur when injected latency > {CONNECTION_TIMEOUT * 1000}ms")
    
    test_count = 0
    success_count = 0
    failure_count = 0
    
    while True:
        test_count += 1
        result = test_dynamodb_connection()
        
        if result:
            success_count += 1
        else:
            failure_count += 1
        
        # Log summary every 10 tests
        if test_count % 10 == 0:
            success_rate = (success_count / test_count) * 100
            logger.info(f"SUMMARY - Total: {test_count}, Success: {success_count}, Failed: {failure_count}, Success Rate: {success_rate:.1f}%")
        
        time.sleep(TEST_INTERVAL)

if __name__ == "__main__":
    main()
