# The identity the app servers use. It lets a server:
#   - pull the container image from ECR,
#   - read the database connection string from Secrets Manager,
#   - write its logs to CloudWatch,
#   - be managed through Systems Manager (no SSH needed).
#
# The role already exists (we created it by hand), so it's imported. See README.md.

data "aws_secretsmanager_secret" "database_url" {
  name = "alphabridge/database-url"
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app_server" {
  name               = "alphabridge-app-ec2"
  description        = "Allows EC2 instances to call AWS services on your behalf."
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

# The instance profile is the container that attaches the role to a server.
resource "aws_iam_instance_profile" "app_server" {
  name = "alphabridge-app-ec2"
  role = aws_iam_role.app_server.name
}

# Pull images from ECR.
resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.app_server.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# Be managed through Systems Manager.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.app_server.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Read the database connection string, and nothing else.
resource "aws_iam_role_policy" "read_db_url" {
  name = "alphabridge-read-db-url"
  role = aws_iam_role.app_server.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = data.aws_secretsmanager_secret.database_url.arn
    }]
  })
}

# Write logs to the app's log group only.
resource "aws_iam_role_policy" "app_logs" {
  name = "alphabridge-app-logs"
  role = aws_iam_role.app_server.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "arn:aws:logs:${var.region}:${var.account_id}:log-group:/alphabridge/app:*"
    }]
  })
}
