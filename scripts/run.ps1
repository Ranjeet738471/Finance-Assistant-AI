param(
    [ValidateSet("backend", "frontend", "all")]
    [string]$Target = "all",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Create it with: python -m venv .venv"
}

Set-Location $ProjectRoot

function Start-Backend {
    & $Python -m uvicorn backend.main:app --host 127.0.0.1 --port $Port
}

function Start-Frontend {
    & $Python frontend\app.py
}

switch ($Target) {
    "backend" {
        Start-Backend
    }
    "frontend" {
        Start-Frontend
    }
    "all" {
        $backend = Start-Process -FilePath $Python `
            -ArgumentList "-m uvicorn backend.main:app --host 127.0.0.1 --port $Port" `
            -WorkingDirectory $ProjectRoot `
            -PassThru

        try {
            Write-Host "Backend started on http://127.0.0.1:$Port (PID $($backend.Id))"
            Write-Host "Starting Gradio frontend..."
            Start-Frontend
        }
        finally {
            if (-not $backend.HasExited) {
                Stop-Process -Id $backend.Id
                Write-Host "Backend stopped."
            }
        }
    }
}
