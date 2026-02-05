# DynamoDB Latency Test for ECS Fargate

This application continuously tests DynamoDB connectivity and reports round trip times, designed for fault injection testing with 800ms latency.

## Setup Steps

### 1. Create IAM Roles

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
        "Action": ["dynamodb:ListTables", "dynamodb:DescribeTable"],
        "Resource": "*"
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

### 2. Create CloudWatch Log Group

```bash
aws logs create-log-group --log-group-name /ecs/dynamodb-latency-test
```

### 3. Build and Push Docker Image

```bash
# Create ECR repository
aws ecr create-repository --repository-name dynamodb-test --region us-east-1

# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 064250592128.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build -t dynamodb-test .
docker tag dynamodb-test:latest 064250592128.dkr.ecr.us-east-1.amazonaws.com/dynamodb-test:latest
docker push 064250592128.dkr.ecr.us-east-1.amazonaws.com/dynamodb-test:latest
```

### 4. Register Task Definition

The task definition is already configured for:
- Account: 064250592128
- Region: us-east-1
- Cluster: FIS

### 5. Register Task Definition

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

### 6. Run the Task

```bash
aws ecs run-task \
  --cluster FIS \
  --launch-type FARGATE \
  --task-definition dynamodb-latency-test \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}"
```

Note: Replace subnet-xxx and sg-xxx with your actual subnet and security group IDs.

### 7. View Logs

```bash
aws logs tail /ecs/dynamodb-latency-test --follow
```

## Fault Injection Testing with AWS FIS

### Create FIS Experiment Template

The `fis-experiment-template.json` file is ready to use. Just replace TASK_ID with your actual task ID after running the task.

To get your task ID after running the task:
```bash
aws ecs list-tasks --cluster FIS --query 'taskArns[0]' --output text
```

### Run the Experiment

```bash
# Create the experiment template
TEMPLATE_ID=$(aws fis create-experiment-template \
  --cli-input-json file://fis-experiment-template.json \
  --query 'experimentTemplate.id' \
  --output text)

# Start the experiment
EXPERIMENT_ID=$(aws fis start-experiment \
  --experiment-template-id $TEMPLATE_ID \
  --query 'experiment.id' \
  --output text)

echo "Experiment started: $EXPERIMENT_ID"

# Monitor the experiment
aws fis get-experiment --id $EXPERIMENT_ID
```

### Monitor Results

Watch the CloudWatch logs to see the latency impact:

```bash
aws logs tail /ecs/dynamodb-latency-test --follow --filter-pattern "Round trip"
```

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
| `CONNECTION_TIMEOUT` | 5.0 | Connection timeout in seconds (time to establish connection) |
| `READ_TIMEOUT` | 5.0 | Read timeout in seconds (time to receive response) |
| `TEST_INTERVAL` | 5 | Seconds between each DynamoDB connection test |

### Timeout Configuration Examples

**Scenario 1: Reproduce timeout errors with 800ms latency injection**
```json
"environment": [
  {
    "name": "CONNECTION_TIMEOUT",
    "value": "0.5"
  },
  {
    "name": "READ_TIMEOUT",
    "value": "0.5"
  }
]
```
Result: With 800ms injected latency, requests will timeout (500ms < 800ms)

**Scenario 2: Allow requests to succeed despite latency**
```json
"environment": [
  {
    "name": "CONNECTION_TIMEOUT",
    "value": "2.0"
  },
  {
    "name": "READ_TIMEOUT",
    "value": "2.0"
  }
]
```
Result: With 800ms injected latency, requests will succeed (2000ms > 800ms)

**Scenario 3: Test edge cases**
```json
"environment": [
  {
    "name": "CONNECTION_TIMEOUT",
    "value": "0.85"
  },
  {
    "name": "READ_TIMEOUT",
    "value": "0.85"
  }
]
```
Result: With 800ms latency + 50ms jitter, some requests succeed, some timeout

### Current Configuration

The task definition is configured with:
- `CONNECTION_TIMEOUT`: 0.5 seconds (500ms)
- `READ_TIMEOUT`: 0.5 seconds (500ms)
- `TEST_INTERVAL`: 5 seconds

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
