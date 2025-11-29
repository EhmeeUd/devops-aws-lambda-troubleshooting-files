import json
import os
import boto3
from datetime import datetime

# Initialize S3 client
s3 = boto3.client('s3')

def handler(event, context):
    """
    Lambda function handler that:
    1. Responds with a success message
    2. Writes data to S3 bucket
    3. Includes proper error handling
    """
    try:
        # Get bucket name from environment variable
        bucket_name = os.environ.get('BUCKET_NAME')
        
        if not bucket_name:
            raise ValueError("BUCKET_NAME environment variable not set")
        
        # Create response data
        response_data = {
            'message': 'Hello from Lambda!',
            'timestamp': datetime.utcnow().isoformat(),
            'event': event,
            'bucket': bucket_name
        }
        
        # Write data to S3 to test access
        s3_key = f"lambda-executions/{datetime.utcnow().strftime('%Y-%m-%d/%H-%M-%S')}.json"
        
        s3.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json.dumps(response_data, indent=2),
            ContentType='application/json'
        )
        
        print(f"Successfully wrote data to s3://{bucket_name}/{s3_key}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Success!',
                'data': response_data,
                's3_location': f"s3://{bucket_name}/{s3_key}"
            }, indent=2),
            'headers': {
                'Content-Type': 'application/json'
            }
        }
        
    except Exception as e:
        error_message = f"Error: {str(e)}"
        print(error_message)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': error_message
            }),
            'headers': {
                'Content-Type': 'application/json'
            }
        }