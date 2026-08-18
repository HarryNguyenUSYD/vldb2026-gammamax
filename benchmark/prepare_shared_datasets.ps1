$ErrorActionPreference = 'Stop'

# Compatibility entry point. Current benchmark datasets already contain clean
# CSVs; refresh metadata, manifests, and C++ oracles without replacing them.
$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
& $python (Join-Path $PSScriptRoot 'regenerate_dataset_info.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
