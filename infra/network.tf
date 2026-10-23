# Looks up the default VPC and its subnets, so the other files can use them.
# Nothing is created here. The default VPC already holds the database, the load balancer, and the app servers.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
