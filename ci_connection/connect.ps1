param(
    [string]$FilePath
)

# Bootstraps Python setup
if (Test-Path $FilePath) {
    $directory = Split-Path -Path $FilePath -Parent
    cd $directory
    . $FilePath
}

python notify_connection.py
