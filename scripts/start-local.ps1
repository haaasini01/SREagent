$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendRoot = Join-Path $projectRoot "frontend"
$python = Get-Command python -ErrorAction Stop
$npm = Get-Command npm.cmd -ErrorAction Stop
$docker = Get-Command docker -ErrorAction Stop

if (-not (Test-Path (Join-Path $frontendRoot "node_modules"))) {
    throw "Frontend dependencies are missing. Run 'npm ci' from the frontend folder first."
}

$env:PYTHONPATH = Join-Path $projectRoot "backend"
& $python.Source -c "import fastapi, httpx, langgraph, langchain_ollama, mcp, psycopg"
if ($LASTEXITCODE -ne 0) {
    throw "Backend dependencies are missing. Run 'python -m pip install -e .' from the project folder."
}

Push-Location $projectRoot
try {
    & $docker.Source compose up -d --build db sandbox
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose could not start the database and telemetry sandbox."
    }

    Start-Process `
        -FilePath $python.Source `
        -ArgumentList @(
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            "backend",
            "--reload"
        ) `
        -WorkingDirectory $projectRoot

    Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList @("/k", "npm run dev -- --host 127.0.0.1") `
        -WorkingDirectory $frontendRoot
}
finally {
    Pop-Location
}

Write-Host "Database and sandbox started with Docker Compose."
Write-Host "Backend and frontend opened in separate terminal windows."
Write-Host "Dashboard: http://localhost:5173"
Write-Host "API docs:  http://localhost:8000/docs"
Write-Host "Ollama must be running locally to analyze an incident."
