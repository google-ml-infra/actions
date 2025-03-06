param(
    [string]$FilePath
)

# Bootstraps Python setup
if (Test-Path $FilePath) {
    $directory = Split-Path -Path $FilePath -Parent
    . $FilePath
}

Set-Location -Path $PSScriptRoot
python notify_connection.py
