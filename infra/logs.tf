# CloudWatch log groups.
#   /alphabridge/app   receives the API container logs from the app servers.
#   /alphabridge/apigw receives the API Gateway access logs.
#
# Both groups already exist (we created them by hand), so they're imported. Logs are kept for
# 7 days, so storage cost stays low.

resource "aws_cloudwatch_log_group" "app" {
  name              = "/alphabridge/app"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "apigw" {
  name              = "/alphabridge/apigw"
  retention_in_days = 7
}
