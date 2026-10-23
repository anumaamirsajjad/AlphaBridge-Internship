# The AWS account and region every resource is created in.
#
# default_tags adds these tags to every resource, so costs and cleanup can be found by project.

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "alphabridge"
      ManagedBy = "terraform"
    }
  }
}
