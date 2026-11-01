# Lets the GitHub Actions pipeline log in to AWS without stored keys.
#
#   GitHub identity provider  -> trusted by AWS once, for all repos
#   Deploy role               -> can be assumed only by a push to the main branch of this repo
#   Deploy permissions        -> ECR push, launch template versions, and instance refresh
#
# The provider and role already exist (we created them by hand), so they're imported.

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["ab9d0263244dd0326eb67015705a667e79cfe998"]
}

data "aws_iam_policy_document" "github_deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only a push to main in this repo may assume the role. Nothing else, including other branches.
    # The subject uses GitHub's immutable format, which includes the owner's and repo's numeric IDs.
    # The plain "owner/repo" form is rejected for this repository.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:anumaamirsajjad@151608625/alphabridge-internship@1428348870:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "alphabridge-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_deploy_trust.json
}

# The role the pipeline uses to run Terraform. It has full admin rights, so it can be assumed only
# by a push to main (the same trust as the deploy role). Pull requests never get this role.
resource "aws_iam_role" "github_terraform" {
  name               = "alphabridge-github-terraform"
  description        = "Used by the pipeline to run Terraform on pushes to main."
  assume_role_policy = data.aws_iam_policy_document.github_deploy_trust.json
}

resource "aws_iam_role_policy_attachment" "github_terraform_admin" {
  role       = aws_iam_role.github_terraform.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# What the deploy may do: push images, update the server recipe, and refresh the servers.
resource "aws_iam_role_policy" "github_deploy" {
  name = "alphabridge-github-deploy-policy"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
          "ecr:BatchGetImage",
        ]
        Resource = aws_ecr_repository.api.arn
      },
      {
        Sid      = "ReadLaunchTemplate"
        Effect   = "Allow"
        Action   = "ec2:DescribeLaunchTemplateVersions"
        Resource = "*"
      },
      {
        Sid      = "NewLaunchTemplateVersion"
        Effect   = "Allow"
        Action   = "ec2:CreateLaunchTemplateVersion"
        Resource = aws_launch_template.app.arn
      },
      {
        Sid      = "RefreshServers"
        Effect   = "Allow"
        Action   = "autoscaling:StartInstanceRefresh"
        Resource = aws_autoscaling_group.app.arn
      },
      {
        Sid      = "WatchRefresh"
        Effect   = "Allow"
        Action   = "autoscaling:DescribeInstanceRefreshes"
        Resource = "*"
      },
      {
        Sid      = "PassServerRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.app_server.arn
      },
    ]
  })
}
