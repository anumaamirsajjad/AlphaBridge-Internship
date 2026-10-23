# The container registry that holds every version of the API image.
#
# This repository already existed (we created it by hand), so it's imported into Terraform
# rather than recreated. That keeps the images. See README.md for the import command.

resource "aws_ecr_repository" "api" {
  name                 = "alphabridge-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  # Lets terraform destroy remove the repository even if it still holds images, at cleanup.
  force_delete = true
}
