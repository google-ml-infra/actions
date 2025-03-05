param(
    [string]$FilePath
)

# Bootstraps Python setup
if (Test-Path $FilePath) {
    . $FilePath
}

python notify_connection.py
