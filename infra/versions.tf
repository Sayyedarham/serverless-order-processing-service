terraform {
  required_version = ">= 1.7.0"

  # Created once by infra/bootstrap. GitHub Actions and local operators then
  # share this state instead of each run attempting to recreate the stack.
  backend "s3" {
    bucket         = "serverless-orders-terraform-state-293162038789-us-east-1"
    key            = "order-processing/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "serverless-orders-terraform-locks"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "ServerlessOrderProcessing"
      ManagedBy   = "Terraform"
      Environment = var.environment
      Repository  = var.github_repo
    }
  }
}
