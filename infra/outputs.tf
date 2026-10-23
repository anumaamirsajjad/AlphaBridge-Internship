# Values other tools need. The load test and the pipeline read these, so no URL is typed by hand.

output "api_url" {
  description = "The public address of the API, through the gateway. Use this for the load test."
  value       = aws_api_gateway_stage.prod.invoke_url
}

output "load_balancer_dns" {
  description = "The load balancer's address, for checking the app directly."
  value       = aws_lb.api.dns_name
}
