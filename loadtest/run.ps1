# Runs the load test against the API gateway address from Terraform, so no URL is typed by hand.
# Set the API key first, in this window only:  $env:API_KEY = "<key>"
# Needs the terraform AWS profile (see the cheat sheet in PROJECT_CONTEXT.md).

if (-not $env:API_KEY) {
    throw 'Set $env:API_KEY first.'
}

$infra = Join-Path $PSScriptRoot "..\infra"
$env:BASE_URL = (terraform -chdir="$infra" output -raw api_url).Trim()
Write-Host "Testing $env:BASE_URL"

k6 run --env BASE_URL=$env:BASE_URL --env API_KEY=$env:API_KEY (Join-Path $PSScriptRoot "transactions.js")
