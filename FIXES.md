# Detailed Fixes Applied to the lambda troubleshooting task

## Summary

This document provides a comprehensive breakdown of all issues found in the original broken Terraform and Lambda code, along with the fixes applied.

---

## Issue #1: Deprecated S3 Bucket ACL Configuration

### Problem
```hcl
resource "aws_s3_bucket" "my_bucket" {
  bucket = "my-super-cool-bucket"
  acl    = "private"  # ❌ This is deprecated
}
```

### Error Message
```
Error: Conflicting configuration arguments
"acl": conflicts with acl
```

### Root Cause
AWS Provider v4.0+ removed the `acl` parameter from `aws_s3_bucket` resource. 

### Fix Applied
```hcl
resource "aws_s3_bucket" "lambda_bucket" {
  bucket = "lambda-deployment-${random_id.bucket_suffix.hex}"
}
```

### Files Changed
- `terraform/main.tf` lines 29-30

---

## Issue #2: Lambda Deployment Package Never Created

### Problem
```hcl
resource "aws_lambda_function" "my_lambda" {
  s3_bucket = aws_s3_bucket.my_bucket.bucket
  s3_key    = "lambda_function_payload.zip"  # ❌ This doesn't exist!
}
```

### Error Message
```
Error: error creating Lambda Function: InvalidParameterValueException: 
S3 object does not exist
```

### Root Cause
Terraform expected `lambda_function_payload.zip` to already exist in S3, but nothing created or uploaded it.

### Fix Applied
```hcl
# Step 1: Create ZIP file from Lambda source
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/lambda_function_payload.zip"
}

# Step 2: Upload ZIP to S3
resource "aws_s3_object" "lambda_package" {
  bucket = aws_s3_bucket.lambda_bucket.id
  key    = "lambda_function_payload.zip"
  source = data.archive_file.lambda_zip.output_path
  etag   = filemd5(data.archive_file.lambda_zip.output_path)
}

# Step 3: Lambda now references the uploaded package
resource "aws_lambda_function" "fixed_lambda" {
  s3_bucket = aws_s3_bucket.lambda_bucket.id
  s3_key    = aws_s3_object.lambda_package.key  # ✅ Now exists
}
```

### Files Changed
- `terraform/main.tf` lines 72-86, 141-144

---

## Issue #3: IAM Role Has Zero Permissions

### Problem
```hcl
resource "aws_iam_role" "iam_for_lambda" {
  name = "iam_for_lambda"
  assume_role_policy = jsonencode({...})
  # ❌ No policies attached! Lambda can't do anything!
}
```

### Error Message
Lambda executes but:
```
User: arn:aws:sts::123456789012:assumed-role/iam_for_lambda/my_lambda 
is not authorized to perform: s3:PutObject on resource
```

### Root Cause
IAM role only had trust policy (who can assume it) but no permission policies (what it can do).

### Fix Applied
```hcl
# Basic Lambda execution (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.iam_for_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Custom S3 access policy
resource "aws_iam_role_policy" "lambda_s3_policy" {
  name = "lambda_s3_access"
  role = aws_iam_role.iam_for_lambda.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.lambda_bucket.arn,
        "${aws_s3_bucket.lambda_bucket.arn}/*"
      ]
    }]
  })
}
```

### Files Changed
- `terraform/main.tf` lines 111-138

---

## Issue #4: No CloudWatch Logs Access

### Problem
Lambda couldn't write logs, making debugging impossible.

### Error Message (in Lambda execution)
```
Unable to write to CloudWatch Logs
```

### Root Cause
Missing `AWSLambdaBasicExecutionRole` policy which grants:
- `logs:CreateLogGroup`
- `logs:CreateLogStream`
- `logs:PutLogEvents`

### Fix Applied
```hcl
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.iam_for_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Also explicitly create log group
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = 7
}
```

### Files Changed
- `terraform/main.tf` lines 111-114, 172-174

---

## Issue #5: Non-Unique S3 Bucket Name

### Problem
```hcl
resource "aws_s3_bucket" "my_bucket" {
  bucket = "my-super-cool-bucket"  # ❌ Probably taken globally
}
```

### Error Message
```
Error: Error creating S3 bucket: BucketAlreadyExists: 
The requested bucket name is not available
```

### Root Cause
S3 bucket names are globally unique across all AWS accounts. "my-super-cool-bucket" is likely already taken.

### Fix Applied
```hcl
# Generate random suffix
resource "random_id" "bucket_suffix" {
  byte_length = 8
}

resource "aws_s3_bucket" "lambda_bucket" {
  bucket = "lambda-deployment-${random_id.bucket_suffix.hex}"  # ✅ Unique
}
```

### Files Changed
- `terraform/main.tf` lines 23-26, 29-30

---

## Issue #6: No Lambda Error Handling

### Problem
```python
def handler(event, context):
    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }
    # ❌ No try-catch, no error handling
    # ❌ Doesn't use S3 at all
```

### Root Cause
Lambda had no error handling. If anything went wrong, unclear what failed.

### Fix Applied
```python
def handler(event, context):
    try:
        bucket_name = os.environ.get('BUCKET_NAME')
        
        if not bucket_name:
            raise ValueError("BUCKET_NAME environment variable not set")
        
        # Write to S3
        s3.put_object(
            Bucket=bucket_name,
            Key=f"lambda-executions/{datetime.utcnow().strftime('%Y-%m-%d/%H-%M-%S')}.json",
            Body=json.dumps(response_data, indent=2),
            ContentType='application/json'
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Success!'})
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
```

### Files Changed
`lambda/handler.py` entire file


## Issue #7: Outdated Python Runtime

### Problem
`runtime = "python3.8"`  # ❌ Approaching EOL

### Root Cause
Python 3.8 is nearing end-of-life. Best practice is to use latest stable.

### Fix Applied
`runtime = "python3.12"`  # stable version

### Files Changed
`terraform/main.tf` line 146


## Issue #8: Missing Resource Dependencies

### Problem
Terraform might create Lambda before IAM policies are attached, causing Lambda to fail on first execution.

### Root Cause
No explicit dependency management.

### Fix Applied
```hcl
resource "aws_lambda_function" "fixed_lambda" {
  # ...
  depends_on = [
    aws_s3_object.lambda_package,
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_iam_role_policy.lambda_s3_policy
  ]
}
```

### Files Changed
`terraform/main.tf` lines 159-163


## Issue #9: Missing Terraform Provider Configuration

### Problem
No required providers block or version constraints.

### Root Cause
Could lead to version compatibility issues.

### Fix Applied
```hcl
terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}
```

### Files Changed

`terraform/main.tf` lines 1-17


## Issue #10: No Outputs

### Problem
No way to know Lambda function name, S3 bucket, or how to test.

### Fix Applied
Created `outputs.tf` with:

- Lambda function name
- Lambda ARN
- S3 bucket name
- Test command

### Files Changed

`terraform/outputs.tf` (new file)


## Testing Evidence
#### Before Fixes
```bash
$ terraform apply
```
- Error: Conflicting configuration arguments
- Error: S3 object does not exist
- Error: Lambda execution failed: Access Denied

#### After Fixes
```bash
$ terraform apply
Apply complete! Resources: 11 added, 0 changed, 0 destroyed.

$ aws lambda invoke --function-name spintech-lambda --payload '{}' response.json
{
    "StatusCode": 200,
    "ExecutedVersion": "$LATEST"
}

$ cat response.json
{
  "statusCode": 200,
  "body": "{\"message\": \"Success!\" ...}"
}
```
---

## Issue #11: S3 Bucket ACL Not Supported

### Problem
```hcl
resource "aws_s3_bucket_acl" "lambda_bucket_acl" {
  acl    = "private"
  bucket = aws_s3_bucket.lambda_bucket.id
}
```

### Error Message
```
Error: creating S3 Bucket ACL: AccessControlListNotSupported: 
The bucket does not allow ACLs
```

### Root Cause
AWS changed the default S3 bucket settings. New buckets created after April 2023 have:
- ACLs disabled by default
- Bucket owner enforced object ownership
- ACLs are no longer the recommended way to control access

### Fix Applied
**Removed** the `aws_s3_bucket_acl` resource entirely. Security is now provided by:

1. **Public Access Block**:
```hcl
resource "aws_s3_bucket_public_access_block" "lambda_bucket_pab" {
  bucket = aws_s3_bucket.lambda_bucket.id
  
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

2. **IAM Policies** - controls who can access:
```hcl
resource "aws_iam_role_policy" "lambda_s3_policy" {
  # Lambda role gets specific S3 permissions
}
```

3. **Encryption** - for security:
```hcl
resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_bucket_encryption" {
  bucket = aws_s3_bucket.lambda_bucket.id
  
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
```

### Best Practice
Instead of ACLs, use:
- **Bucket policies** for bucket-level access
- **IAM policies** for user/role access
- **Public Access Block** to prevent public exposure

### Files Changed
- `terraform/main.tf` line 35-38 (removed)
- Added encryption configuration for better security

### Testing
```bash
# Verify that this bucket is private
aws s3api get-public-access-block \
  --bucket lambda-deployment-XXXX

# Should show all blocks enabled
```
---

## Summary of All Issues Fixed

## Summary of Issues and Fixes (Table Format)

| Issue # | Problem Summary                           | Root Cause                                                | Fix Applied                                                         |
| ------- | ----------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------- |
| 1       | Deprecated S3 bucket ACL (`acl` argument) | AWS provider v4+ removed ACL support from `aws_s3_bucket` | Removed ACL, used modern bucket config                              |
| 2       | Lambda deployment ZIP did not exist in S3 | No archive created or uploaded before Lambda creation     | Added `archive_file` + `aws_s3_object` to build and upload ZIP      |
| 3       | IAM role had no permissions               | Only trust policy defined, no access policies             | Attached AWSLambdaBasicExecutionRole + custom S3 policy             |
| 4       | Lambda couldn’t write CloudWatch logs     | Missing logging permissions                               | Added log access policy + created CloudWatch Log Group              |
| 5       | Bucket name not unique                    | S3 bucket names must be globally unique                   | Added `random_id` to generate unique bucket names                   |
| 6       | Lambda lacked error handling              | No try/except, unclear failures                           | Added proper exception handling + S3 write logic                    |
| 7       | Outdated Python runtime                   | Using Python 3.8 (near EOL)                               | Updated to Python 3.12                                              |
| 8       | Missing resource dependencies             | Lambda created before IAM/S3 objects ready                | Added `depends_on` block to enforce resource ordering               |
| 9       | No Terraform provider versions            | Risk of provider incompatibility                          | Added `required_providers` + Terraform version constraints          |
| 10      | No Terraform outputs                      | Hard to test & reference resources                        | Added outputs for Lambda name, ARN, bucket, test command            |
| 11      | S3 Bucket ACL not supported               | ACL operations no longer allowed on new buckets           | Removed ACL resource and added Public Access Block + SSE encryption |
