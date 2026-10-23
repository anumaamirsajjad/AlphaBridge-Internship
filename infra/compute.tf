# The app servers: the recipe for each server (launch template), and the group that keeps
# the right number of them running and registered with the load balancer (auto scaling group).
#
# Both already exist (we created them by hand), so they're imported. See README.md.

# The latest Amazon Linux 2023 image. It's looked up each time, so a new image can't go unnoticed.
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

resource "aws_launch_template" "app" {
  name          = "alphabridge-app-lt"
  image_id      = data.aws_ami.al2023.id
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.app_server.name
  }

  # Each server gets a public address, so it can reach ECR and Secrets Manager.
  # Its firewall is the app group, which only accepts traffic from the load balancer.
  network_interfaces {
    device_index                = 0
    associate_public_ip_address = true
    security_groups             = [aws_security_group.app.id]
  }

  user_data = base64encode(templatefile("${path.module}/templates/app-user-data.sh.tftpl", {
    region    = var.region
    registry  = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com"
    image_tag = var.image_tag
    log_group = aws_cloudwatch_log_group.app.name
  }))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "alphabridge-app"
    }
  }
}

resource "aws_autoscaling_group" "app" {
  name                = "alphabridge-asg"
  min_size            = var.app_server_count
  desired_capacity    = var.app_server_count
  max_size            = var.app_server_max
  vpc_zone_identifier = data.aws_subnets.default.ids

  # Points at the newest recipe version. When the recipe changes, this changes too, which starts the refresh below.
  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }

  # Replaces the servers one at a time. At least half stay in service, and each new server gets
  # 120 seconds to start before the next one is replaced. This is what keeps a deploy from dropping requests.
  instance_refresh {
    strategy = "Rolling"

    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 120
    }
  }

  # The load balancer decides a server is healthy, and replaces it if it isn't.
  target_group_arns         = [aws_lb_target_group.app.arn]
  health_check_type         = "ELB"
  health_check_grace_period = 300

  tag {
    key                 = "Name"
    value               = "alphabridge-app"
    propagate_at_launch = true
  }
}
