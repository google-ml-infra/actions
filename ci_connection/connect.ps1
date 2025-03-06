param(
    [string]$FilePath
)

# Bootstraps Python setup
if (Test-Path $FilePath) {
    $directory = Split-Path -Path $FilePath -Parent
    Set-Location -Path $PSScriptRoot
    . $FilePath
}

python notify_connection.py
