# entrypoint.ps1
param(
    [string]$PythonBin = "python",
    [switch]$NoEnv
)

$ErrorActionPreference = "Stop"

# Run setup and capture the state file path
$stateFile = & $PythonBin setup_connection.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "Setup failed"
    exit 1
}

$stateFile = $stateFile.Trim()

if (-not $stateFile) {
    Write-Error "Setup returned empty path"
    exit 1
}

# Load state
if (Test-Path $stateFile) {
    try {
        $jsonContent = Get-Content $stateFile -Raw
        $state = $jsonContent | ConvertFrom-Json
    } catch {
        Write-Error "Failed to parse state file: $_"
        exit 1
    }

    # Apply environment variables
    if (-not $NoEnv -and $state.env) {
        foreach ($prop in $state.env.PSObject.Properties) {
            $name = $prop.Name
            $value = $prop.Value
            if ($name) {
                Set-Item -Path "Env:$name" -Value $value
            }
        }
    }

    # Change directory
    if ($state.directory) {
        if (Test-Path $state.directory) {
            Set-Location $state.directory
        } else {
            Write-Warning "Directory to change to not found: $($state.directory)"
        }
    }

    # Clean up state file
    Remove-Item $stateFile -Force -ErrorAction SilentlyContinue
}

# Start background keep-alive process
$keepAliveProc = Start-Process $PythonBin `
    -ArgumentList "keepalive.py", $PID `
    -WindowStyle Hidden `
    -PassThru

Write-Host "Connected. Keep-alive running (PID: $($keepAliveProc.Id))"
Write-Host "Type 'exit' to disconnect."