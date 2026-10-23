# The database: a private PostgreSQL instance on RDS, reachable only from the app servers.
#
# It already exists (we created it by hand), so it's imported. Every setting below matches the
# existing database. A setting that differs would make Terraform rebuild the database, which would
# delete the data. So changing a value here needs a careful check of the plan first.
#
# The master password is not stored here. It was set by hand, and Terraform ignores it.

resource "aws_db_subnet_group" "default" {
  name        = "default-vpc-0738d256b33c2c81b"
  description = "Created from the RDS Management Console"
  subnet_ids  = data.aws_subnets.default.ids
}

resource "aws_db_instance" "main" {
  identifier     = "alphabridge"
  engine         = "postgres"
  engine_version = "18.3"
  instance_class = "db.t4g.micro"

  allocated_storage     = 20
  max_allocated_storage = 1000
  storage_type          = "gp2"
  storage_encrypted     = true
  port                  = 5432
  username              = "postgres"

  db_subnet_group_name   = aws_db_subnet_group.default.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 1
  backup_window           = "17:52-18:22"
  maintenance_window      = "fri:11:48-fri:12:18"
  copy_tags_to_snapshot   = true

  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  deletion_protection = false
  skip_final_snapshot = true

  lifecycle {
    # The password was set by hand. Terraform must not change it.
    ignore_changes = [password]
  }
}
