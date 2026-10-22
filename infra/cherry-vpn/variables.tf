variable "project_id" {
  description = "Existing dedicated, disposable Cherry Servers project; never the applications project."
  type        = number

  validation {
    condition     = var.project_id > 0 && floor(var.project_id) == var.project_id
    error_message = "project_id must be a positive integer."
  }
}

variable "plan" {
  description = "Only the two smallest shared x86 VM generations are permitted in this experiment."
  type        = string
  default     = "B1-1-1gb-20s-shared"

  validation {
    condition     = contains(["B1-1-1gb-20s-shared", "B2-1-1gb-20s-shared"], var.plan)
    error_message = "Budget test permits only 1 vCPU / 1 GB RAM / 20 GB shared VPS plans."
  }
}

variable "region" {
  description = "Explicit region selection after checking stock and regional reachability."
  type        = string

  validation {
    condition     = length(trimspace(var.region)) > 0
    error_message = "Choose a region from the live plan catalogue."
  }
}

variable "ssh_public_key_path" {
  description = "Local path to a dedicated administrator PUBLIC key. Private keys stay outside OpenTofu."
  type        = string
}
