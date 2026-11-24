# ConverData en AWS (CN-01): una pila por entorno. Se ejecuta con ../despliegue.sh, que pasa el backend y el tfvars.
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # bucket, key y region llegan con -backend-config (despliegue.sh). El bloqueo es el nativo de S3, sin DynamoDB.
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      app        = "converdata"
      env        = var.environment
      managed-by = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}
