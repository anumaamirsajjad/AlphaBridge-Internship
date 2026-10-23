# The load balancer: the single public entry point for the API.
#
#   Listener (port 80) -> target group (port 8000 on the app servers, checked at /docs)
#
# All three already exist (we created them by hand), so they're imported. See README.md.

resource "aws_lb" "api" {
  name               = "alphabridge-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = data.aws_subnets.default.ids
}

resource "aws_lb_target_group" "app" {
  name        = "alphabridge-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "instance"

  # Keeps the old server in service this long after it's removed, so in-flight requests finish.
  # This prevents 502 errors during a deploy.
  deregistration_delay = 60

  health_check {
    path                = "/docs"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 5
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "forward"

    forward {
      target_group {
        arn    = aws_lb_target_group.app.arn
        weight = 1
      }

      stickiness {
        enabled  = false
        duration = 3600
      }
    }
  }
}
