# The public API gateway (REST API). It forwards every request to the load balancer.
#
#   Client -> API Gateway (prod stage) -> load balancer -> app servers
#
# This gateway is created by Terraform, not imported. Its address comes from the Terraform output
# (see outputs.tf), so no URL is typed by hand. The gateways created earlier by hand are removed
# during cleanup.

locals {
  # The load balancer's address, read from Terraform. Nothing is typed in.
  load_balancer_url = "http://${aws_lb.api.dns_name}"
}

resource "aws_api_gateway_rest_api" "api" {
  name = "alphabridge-rest-api"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# The catch-all path: /{proxy+} matches every path below the root, such as /version1/transactions.
resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "NONE"

  request_parameters = {
    "method.request.path.proxy" = true
  }
}

resource "aws_api_gateway_integration" "proxy" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "ANY"
  uri                     = "${local.load_balancer_url}/{proxy}"
  connection_type         = "INTERNET"

  request_parameters = {
    "integration.request.path.proxy" = "method.request.path.proxy"
  }
}

# The root path (/) is handled separately, since the proxy path does not match it.
resource "aws_api_gateway_method" "root" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = aws_api_gateway_rest_api.api.root_resource_id
  http_method   = "ANY"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "root" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_rest_api.api.root_resource_id
  http_method             = aws_api_gateway_method.root.http_method
  type                    = "HTTP_PROXY"
  integration_http_method = "ANY"
  uri                     = "${local.load_balancer_url}/"
  connection_type         = "INTERNET"
}

# A new deployment is made whenever the routes change, so the stage always runs the current routes.
resource "aws_api_gateway_deployment" "api" {
  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeploy = sha1(jsonencode([
      aws_api_gateway_resource.proxy.id,
      aws_api_gateway_method.proxy.id,
      aws_api_gateway_integration.proxy.id,
      aws_api_gateway_method.root.id,
      aws_api_gateway_integration.root.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  rest_api_id   = aws_api_gateway_rest_api.api.id
  deployment_id = aws_api_gateway_deployment.api.id
  stage_name    = "prod"
}
