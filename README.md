# DynamoDB Latency Test for ECS Fargate

This application continuously tests DynamoDB connectivity and reports round trip times, designed for fault injection testing with 800ms latency.

## Setup Steps

### 1. Create DynamoDB Table

Create a DynamoDB table for the application to read from:

```bash
aws dynamodb create-table \
  --table-name MyTestTable \
  --attribute-definitions AttributeName=id,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

Optionally, add some test data:

```bash
aws dynamodb put-item \
  --table-name MyTestTable \
  --item '{"id": {"S": "test1"}, "data": {"S": "Sample data 1"}}' \
  --region us-east-1

aws dynamodb put-item \
  --table-name MyTestTable \
  --item '{"id": {"S": "test2"}, "data": {"S": "Sample data 2"}}' \
  --region us-east-1
```

### 2. Create IAM Roles

**Task Execution Role** (ecsTaskExecutionRole):
```bash
aws iam create-role --role-name ecsTaskExecutionRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

**Task Role** (ecsTaskRole) - for DynamoDB and SSM access:
```bash
aws iam create-role --role-name ecsTaskRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam put-role-policy --role-name ecsTaskRole \
  --policy-name DynamoDBAndSSMAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "dynamodb:Scan",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:DescribeTable"
        ],
        "Resource": "arn:aws:dynamodb:us-east-1:064250592128:table/MyTestTable"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ssm:CreateActivation",
          "ssm:DeleteActivation",
          "ssm:DeregisterManagedInstance",
          "ssm:AddTagsToResource"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": "iam:PassRole",
        "Resource": "arn:aws:iam::064250592128:role/SSMManagedInstanceRole"
      }
    ]
  }'
```

**SSM Managed Instance Role** (SSMManagedInstanceRole):
```bash
aws iam create-role --role-name SSMManagedInstanceRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ssm.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy --role-name SSMManagedInstanceRole \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

aws iam put-role-policy --role-name SSMManagedInstanceRole \
  --policy-name AssumeRole \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::064250592128:role/SSMManagedInstanceRole"
    }]
  }'
```

**FIS Experiment Role** (fisExperimentRole):
```bash
aws iam create-role --role-name fisExperimentRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "fis.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam put-role-policy --role-name fisExperimentRole \
  --policy-name FISECSAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "ecs:ListTasks",
          "ecs:DescribeTasks",
          "ecs:ListContainerInstances"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ssm:SendCommand",
          "ssm:ListCommands",
          "ssm:CancelCommand",
          "ssm:GetCommandInvocation"
        ],
        "Resource": "*"
      }
    ]
  }'
```

### 3. Create CloudWatch Log Group

```bash
aws logs create-log-group --log-group-name /ecs/dynamodb-latency-test
```

### 4. Build and Push Docker Image

```bash
# Create ECR repository
aws ecr create-repository --repository-name fis-latency-test-to-ddb --region us-east-1

# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 064250592128.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build -t fis-latency-test-to-ddb .
docker tag fis-latency-test-to-ddb:latest 064250592128.dkr.ecr.us-east-1.amazonaws.com/fis-latency-test-to-ddb:latest
docker push 064250592128.dkr.ecr.us-east-1.amazonaws.com/fis-latency-test-to-ddb:latest
```

### 5. Register Task Definition

The task definition is already configured for:
- Account: 064250592128
- Region: us-east-1
- Cluster: FIS

```bash
aws ecs register-task-definition --region us-east-1 --cli-input-json file://task-definition.json
```

### 6. Run the Task

```bash
aws ecs run-task \
  --cluster FIS \
  --launch-type FARGATE \
  --task-definition dynamodb-latency-test \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-074e81a195f80085b,subnet-0ba641874c881911e,	
subnet-0a8a02552b56e8441],securityGroups=[sg-063a086776564b8ce],assignPublicIp=ENABLED}" \
  --region us-east-1
```

Note: Replace subnet-xxx and sg-xxx with your actual subnet and security group IDs.

### 7. Create Network Load Balancer (NLB) and ECS Service

**Step 7.1: Create Target Group**

```bash
# Create target group for ECS service
aws elbv2 create-target-group \
  --name dynamodb-test-tg \
  --protocol TCP \
  --port 80 \
  --vpc-id vpc-03630343ff89a1161 \
  --target-type ip \
  --health-check-enabled \
  --health-check-protocol HTTP \
  --health-check-path /health \
  --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 2 \
  --region us-east-1

# Note the TargetGroupArn from the output
```

**Step 7.2: Create Security Group for NLB**

```bash
# Create security group for NLB
aws ec2 create-security-group \
  --group-name dynamodb-test-nlb-sg \
  --description "Security group for DynamoDB test NLB - restrict access" \
  --vpc-id vpc-03630343ff89a1161 \
  --region us-east-1

# Note the GroupId from the output (e.g., sg-xxxxx)

# Allow HTTP access from your IP only (replace YOUR_IP with your actual IP)
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 80 \
  --cidr YOUR_IP/32 \
  --region us-east-1

# Optional: Allow access from your office/VPN CIDR range
# aws ec2 authorize-security-group-ingress \
#   --group-id sg-xxxxx \
#   --protocol tcp \
#   --port 80 \
#   --cidr 10.0.0.0/8 \
#   --region us-east-1

# Get your current public IP
curl -s https://checkip.amazonaws.com
```

**Step 7.3: Create Network Load Balancer with Security Group**

```bash
# Create NLB with security group (use at least 2 subnets in different AZs)
aws elbv2 create-load-balancer \
  --name dynamodb-test-nlb \
  --type network \
  --scheme internet-facing \
  --subnets subnet-074e81a195f80085b subnet-0ba641874c881911e \
  --security-groups sg-xxxxx \
  --region us-east-1

# Note the LoadBalancerArn from the output
```

**Important Notes:**
- NLB security groups are only supported for NLBs created after August 2023
- If you get an error about security groups not being supported, remove the `--security-groups` parameter and use security groups on the ECS tasks instead
- Replace `YOUR_IP/32` with your actual IP address (get it from `curl https://checkip.amazonaws.com`)

**Step 7.4: Create Listener**

```bash
# Create listener to forward traffic to target group
# Replace the ARNs with actual values from previous commands
aws elbv2 create-listener \
  --load-balancer-arn arn:aws:elasticloadbalancing:us-east-1:064250592128:loadbalancer/net/dynamodb-test-nlb/7897fc06ba9f2b32 \
  --protocol TCP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:us-east-1:064250592128:targetgroup/dynamodb-test-tg/8bbecc9680ab0a36 \
  --region us-east-1
```

**Step 7.5: Create ECS Service with NLB**

```bash
# Create ECS service with load balancer integration
# Replace target group ARN with actual value
aws ecs create-service \
  --cluster FIS \
  --service-name dynamodb-test-service \
  --task-definition dynamodb-latency-test \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-074e81a195f80085b,subnet-0ba641874c881911e,subnet-0a8a02552b56e8441],securityGroups=[sg-063a086776564b8ce],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:us-east-1:064250592128:targetgroup/dynamodb-test-tg/8bbecc9680ab0a36,containerName=fis-latency-test-to-ddb-app,containerPort=80" \
  --health-check-grace-period-seconds 60 \
  --region us-east-1
```

**Step 7.6: Get NLB DNS Name**

```bash
# Get the DNS name to access your service
aws elbv2 describe-load-balancers \
  --names dynamodb-test-nlb \
  --query 'LoadBalancers[0].DNSName' \
  --output text \
  --region us-east-1
```

**Update NLB Security Group (if needed):**

```bash
# Add another IP address to allowed list
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 80 \
  --cidr ANOTHER_IP/32 \
  --region us-east-1

# Remove an IP address from allowed list
aws ec2 revoke-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 80 \
  --cidr OLD_IP/32 \
  --region us-east-1

# View current security group rules
aws ec2 describe-security-groups \
  --group-ids sg-xxxxx \
  --query 'SecurityGroups[0].IpPermissions' \
  --region us-east-1
```

**Update Service (if needed):**

```bash
# Update service with new task definition or desired count
aws ecs update-service \
  --cluster FIS \
  --service dynamodb-test-service \
  --task-definition dynamodb-latency-test \
  --desired-count 3 \
  --region us-east-1
```

**Delete Service (if needed):**

```bash
# Scale down to 0 first
aws ecs update-service \
  --cluster FIS \
  --service dynamodb-test-service \
  --desired-count 0 \
  --region us-east-1

# Then delete the service
aws ecs delete-service \
  --cluster FIS \
  --service dynamodb-test-service \
  --region us-east-1
```

**Important Notes:**
- Replace vpc-xxx with your actual VPC ID
- The security group (sg-063a086776564b8ce) must allow inbound traffic on port 80
- Use at least 2 subnets in different availability zones for NLB
- The application currently doesn't expose an HTTP endpoint on port 80, so you may want to add a Flask/FastAPI web server with a health check endpoint for the NLB to properly route traffic
- For fault injection testing on services, you can target all tasks in the service instead of individual task ARNs

### 8. View Logs

```bash
aws logs tail /ecs/dynamodb-latency-test --follow
```

## Fault Injection Testing with AWS FIS

AWS FIS allows you to inject network latency to test how your application handles slow DynamoDB connections.

### Prerequisites

1. Ensure your ECS task definition has `enableFaultInjection: true` (already configured)
2. Ensure your ECS task definition has `pidMode: task` (already configured)
3. The SSM agent sidecar container is running (already configured)
4. The fisExperimentRole has proper permissions (already configured)

### Option 1: Target Specific Tasks (fis-experiment-template.json)

Use this when you want to test specific task ARNs.

**Get your task ARNs:**
```bash
# List all tasks in the service
aws ecs list-tasks \
  --cluster FIS \
  --service-name dynamodb-test-service \
  --region us-east-1

# Or get a specific task ARN
aws ecs list-tasks \
  --cluster FIS \
  --service-name dynamodb-test-service \
  --query 'taskArns[0]' \
  --output text \
  --region us-east-1
```

**Update the template:**
Edit `fis-experiment-template.json` and replace `TASK_ID` with your actual task ID.

**Create and run the experiment:**
```bash
# Create the experiment template
TEMPLATE_ID=$(aws fis create-experiment-template \
  --cli-input-json file://fis-experiment-template.json \
  --query 'experimentTemplate.id' \
  --output text \
  --region us-east-1)

echo "Template ID: $TEMPLATE_ID"

# Start the experiment
EXPERIMENT_ID=$(aws fis start-experiment \
  --experiment-template-id $TEMPLATE_ID \
  --query 'experiment.id' \
  --output text \
  --region us-east-1)

echo "Experiment started: $EXPERIMENT_ID"
```

### Option 2: Target All Tasks in Service (fis-experiment-template-service.json)

Use this to automatically target all tasks in the `dynamodb-test-service` service.

**Create and run the experiment:**
```bash
# Create the experiment template
TEMPLATE_ID=$(aws fis create-experiment-template \
  --cli-input-json file://fis-experiment-template-service.json \
  --query 'experimentTemplate.id' \
  --output text \
  --region us-east-1)

echo "Template ID: $TEMPLATE_ID"

# Start the experiment
EXPERIMENT_ID=$(aws fis start-experiment \
  --experiment-template-id $TEMPLATE_ID \
  --query 'experiment.id' \
  --output text \
  --region us-east-1)

echo "Experiment started: $EXPERIMENT_ID"
```

### Monitor the Experiment

**Check experiment status:**
```bash
aws fis get-experiment \
  --id $EXPERIMENT_ID \
  --region us-east-1
```

**Watch the application logs to see latency impact:**
```bash
aws logs tail /ecs/dynamodb-latency-test --follow --filter-pattern "Round trip"
```

**Test the interactive endpoint during the experiment:**
```bash
# Replace with your NLB DNS name
curl http://dynamodb-test-nlb-7897fc06ba9f2b32.elb.us-east-1.amazonaws.com/test
```

### Expected Behavior

**Normal (no fault injection):**
- Round trip time: ~10-50ms
- Health checks: PASSED (200)
- `/test` endpoint: Returns success in ~10-50ms

**During 800ms latency injection:**
- Round trip time: ~800-850ms
- With CONNECTION_TIMEOUT_MS=500 and READ_TIMEOUT_MS=500: Timeout errors
- Health checks: FAILED (503) after 30 seconds of failures
- `/test` endpoint: Returns 500 with timeout error

**Experiment Parameters:**
- **duration**: PT5M (5 minutes)
- **delayMilliseconds**: 800 (adds 800ms delay)
- **jitterMilliseconds**: 50 (adds random 0-50ms variation)
- **sources**: DYNAMODB (only affects DynamoDB traffic)
- **useEcsFaultInjectionEndpoints**: true (uses ECS Fault Injection APIs)

### Stop an Experiment Early

```bash
aws fis stop-experiment \
  --id $EXPERIMENT_ID \
  --region us-east-1
```

### List All Experiment Templates

```bash
aws fis list-experiment-templates --region us-east-1
```

### Delete an Experiment Template

```bash
aws fis delete-experiment-template \
  --id $TEMPLATE_ID \
  --region us-east-1
```

## Troubleshooting

Expected behavior:
- Normal: ~10-50ms round trip time
- With 800ms injection: ~800-850ms round trip time
- The experiment runs for 5 minutes (PT5M duration)

### Alternative: Target by Tags

Instead of specific task ARNs, you can target tasks by tags:

```json
"targets": {
  "myTasks": {
    "resourceType": "aws:ecs:task",
    "resourceTags": {
      "Environment": "test"
    },
    "filters": [
      {
        "path": "Cluster",
        "values": ["FIS"]
      }
    ],
    "selectionMode": "ALL"
  }
}
```


## Environment Variables

The application supports the following environment variables for timeout configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `TABLE_NAME` | MyTestTable | Name of the DynamoDB table to read from |
| `CONNECTION_TIMEOUT_MS` | 5000 | Connection timeout in milliseconds (time to establish connection) |
| `READ_TIMEOUT_MS` | 5000 | Read timeout in milliseconds (time to receive response) |
| `TEST_INTERVAL_SECONDS` | 5 | Seconds between each DynamoDB connection test |

### Timeout Configuration Examples

**Scenario 1: Reproduce timeout errors with 800ms latency injection**
```json
"environment": [
  {
    "name": "CONNECTION_TIMEOUT_MS",
    "value": "500"
  },
  {
    "name": "READ_TIMEOUT_MS",
    "value": "500"
  }
]
```
Result: With 800ms injected latency, requests will timeout (500ms < 800ms)

**Scenario 2: Allow requests to succeed despite latency**
```json
"environment": [
  {
    "name": "CONNECTION_TIMEOUT_MS",
    "value": "2000"
  },
  {
    "name": "READ_TIMEOUT_MS",
    "value": "2000"
  }
]
```
Result: With 800ms injected latency, requests will succeed (2000ms > 800ms)

**Scenario 3: Test edge cases**
```json
"environment": [
  {
    "name": "CONNECTION_TIMEOUT_MS",
    "value": "850"
  },
  {
    "name": "READ_TIMEOUT_MS",
    "value": "850"
  }
]
```
Result: With 800ms latency + 50ms jitter, some requests succeed, some timeout

### Current Configuration

The task definition is configured with:
- `CONNECTION_TIMEOUT_MS`: 500ms
- `READ_TIMEOUT_MS`: 500ms
- `TEST_INTERVAL_SECONDS`: 5 seconds

This means when you inject 800ms latency, the application will experience timeout errors, simulating real-world connection failures.

### Testing Different Scenarios

To test different timeout behaviors, update the environment variables in `task-definition.json` and re-register the task definition:

```bash
# Edit task-definition.json to change timeout values
# Then re-register
aws ecs register-task-definition --cli-input-json file://task-definition.json

# Run new task with updated configuration
aws ecs run-task \
  --cluster FIS \
  --launch-type FARGATE \
  --task-definition dynamodb-latency-test \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```
