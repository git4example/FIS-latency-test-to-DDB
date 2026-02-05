import boto3
import time
import logging
import os
import threading
from datetime import datetime
from botocore.config import Config
from flask import Flask, jsonify

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get configuration from environment variables
TABLE_NAME = os.getenv('TABLE_NAME', 'MyTestTable')
CONNECTION_TIMEOUT = float(os.getenv('CONNECTION_TIMEOUT', '5.0'))  # seconds
READ_TIMEOUT = float(os.getenv('READ_TIMEOUT', '5.0'))  # seconds
TEST_INTERVAL = int(os.getenv('TEST_INTERVAL', '5'))  # seconds between tests

logger.info(f"Configuration: TABLE_NAME={TABLE_NAME}, CONNECTION_TIMEOUT={CONNECTION_TIMEOUT}s, READ_TIMEOUT={READ_TIMEOUT}s, TEST_INTERVAL={TEST_INTERVAL}s")

# Configure boto3 client with custom timeouts
boto_config = Config(
    connect_timeout=CONNECTION_TIMEOUT,
    read_timeout=READ_TIMEOUT,
    retries={'max_attempts': 0}  # Disable retries to see immediate timeout behavior
)

# Initialize DynamoDB client with timeout configuration
dynamodb = boto3.client('dynamodb', region_name='us-east-1', config=boto_config)

# Initialize Flask app for health checks
app = Flask(__name__)

# Global variables for health status
last_success_time = None
last_error = None
total_tests = 0
success_count = 0
failure_count = 0

def test_dynamodb_connection():
    """Test DynamoDB connection by reading from the table"""
    global last_success_time, last_error, total_tests, success_count, failure_count
    
    start_time = time.time()
    try:
        # Scan the table to read items (limit to 10 items for efficiency)
        response = dynamodb.scan(
            TableName=TABLE_NAME,
            Limit=10
        )
        
        end_time = time.time()
        round_trip_ms = (end_time - start_time) * 1000
        
        item_count = len(response.get('Items', []))
        scanned_count = response.get('ScannedCount', 0)
        
        logger.info(f"SUCCESS - Round trip time: {round_trip_ms:.2f}ms - Table: {TABLE_NAME} - Items read: {item_count} - Scanned: {scanned_count}")
        
        last_success_time = datetime.now()
        last_error = None
        return True
        
    except Exception as e:
        end_time = time.time()
        round_trip_ms = (end_time - start_time) * 1000
        error_type = type(e).__name__
        
        # Log different error types with appropriate severity
        if 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
            logger.error(f"TIMEOUT - Round trip time: {round_trip_ms:.2f}ms - Table: {TABLE_NAME} - Error type: {error_type} - Message: {str(e)}")
        else:
            logger.error(f"FAILED - Round trip time: {round_trip_ms:.2f}ms - Table: {TABLE_NAME} - Error type: {error_type} - Message: {str(e)}")
        
        last_error = str(e)
        return False

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for load balancer"""
    global last_success_time, last_error, total_tests, success_count, failure_count
    
    # Consider healthy if we had a successful test in the last 30 seconds
    is_healthy = last_success_time and (datetime.now() - last_success_time).total_seconds() < 30
    
    status_code = 200 if is_healthy else 503
    
    response = {
        "status": "healthy" if is_healthy else "unhealthy",
        "last_success": last_success_time.isoformat() if last_success_time else None,
        "last_error": last_error,
        "total_tests": total_tests,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": f"{(success_count / total_tests * 100):.1f}%" if total_tests > 0 else "0%"
    }
    
    return jsonify(response), status_code

@app.route('/test', methods=['GET'])
def test_now():
    """Interactive endpoint to trigger a DynamoDB test on demand"""
    start_time = time.time()
    
    try:
        # Scan the table to read items (limit to 10 items for efficiency)
        response = dynamodb.scan(
            TableName=TABLE_NAME,
            Limit=10
        )
        
        end_time = time.time()
        round_trip_ms = (end_time - start_time) * 1000
        
        item_count = len(response.get('Items', []))
        scanned_count = response.get('ScannedCount', 0)
        
        result = {
            "status": "success",
            "table": TABLE_NAME,
            "round_trip_ms": round(round_trip_ms, 2),
            "items_returned": item_count,
            "items_scanned": scanned_count,
            "timestamp": datetime.now().isoformat(),
            "configuration": {
                "connection_timeout": CONNECTION_TIMEOUT,
                "read_timeout": READ_TIMEOUT
            }
        }
        
        logger.info(f"INTERACTIVE TEST - SUCCESS - Round trip time: {round_trip_ms:.2f}ms - Items: {item_count}")
        return jsonify(result), 200
        
    except Exception as e:
        end_time = time.time()
        round_trip_ms = (end_time - start_time) * 1000
        error_type = type(e).__name__
        
        result = {
            "status": "failed",
            "table": TABLE_NAME,
            "round_trip_ms": round(round_trip_ms, 2),
            "error_type": error_type,
            "error_message": str(e),
            "timestamp": datetime.now().isoformat(),
            "configuration": {
                "connection_timeout": CONNECTION_TIMEOUT,
                "read_timeout": READ_TIMEOUT
            }
        }
        
        logger.error(f"INTERACTIVE TEST - FAILED - Round trip time: {round_trip_ms:.2f}ms - Error: {error_type} - {str(e)}")
        return jsonify(result), 500

@app.route('/', methods=['GET'])
def root():
    """Root endpoint with service info"""
    return jsonify({
        "service": "DynamoDB Latency Test",
        "table": TABLE_NAME,
        "endpoints": {
            "health": "/health",
            "stats": "/stats",
            "test": "/test - Run an interactive DynamoDB test"
        }
    })

@app.route('/stats', methods=['GET'])
def stats():
    """Statistics endpoint"""
    global last_success_time, last_error, total_tests, success_count, failure_count
    
    return jsonify({
        "total_tests": total_tests,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": f"{(success_count / total_tests * 100):.1f}%" if total_tests > 0 else "0%",
        "last_success": last_success_time.isoformat() if last_success_time else None,
        "last_error": last_error,
        "configuration": {
            "table_name": TABLE_NAME,
            "connection_timeout": CONNECTION_TIMEOUT,
            "read_timeout": READ_TIMEOUT,
            "test_interval": TEST_INTERVAL
        }
    })

def run_tests():
    """Run DynamoDB tests in background thread"""
    global total_tests, success_count, failure_count
    
    logger.info("Starting DynamoDB connection test application")
    logger.info(f"Reading from table: {TABLE_NAME}")
    logger.info(f"Configured for fault injection testing with {CONNECTION_TIMEOUT}s connection timeout")
    logger.info(f"Expected behavior: Timeouts will occur when injected latency > {CONNECTION_TIMEOUT * 1000}ms")
    
    while True:
        total_tests += 1
        result = test_dynamodb_connection()
        
        if result:
            success_count += 1
        else:
            failure_count += 1
        
        # Log summary every 10 tests
        if total_tests % 10 == 0:
            success_rate = (success_count / total_tests) * 100
            logger.info(f"SUMMARY - Total: {total_tests}, Success: {success_count}, Failed: {failure_count}, Success Rate: {success_rate:.1f}%")
        
        time.sleep(TEST_INTERVAL)

if __name__ == "__main__":
    # Start DynamoDB testing in background thread
    test_thread = threading.Thread(target=run_tests, daemon=True)
    test_thread.start()
    
    # Start Flask web server
    logger.info("Starting Flask web server on port 80")
    app.run(host='0.0.0.0', port=80, debug=False)
