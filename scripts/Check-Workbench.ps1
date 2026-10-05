$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskPort = 8765
$launcherState = Join-Path $taskRoot 'data\launcher.json'
if (Test-Path -LiteralPath $launcherState) { $taskPort = (Get-Content -LiteralPath $launcherState -Raw | ConvertFrom-Json).port }
$taskBaseUrl = 'http://127.0.0.1:' + $taskPort
$runtimePaths = @('.venv\Scripts\python.exe', 'modules\video-parser\venv\Scripts\python.exe', 'modules\scraper\media_crawler\.venv\Scripts\python.exe', 'data\video-helper\runtime\.venv\Scripts\python.exe')
if (Test-Path -LiteralPath (Join-Path $taskRoot 'runtime\python311\python.exe')) {
    $runtimePaths = @('runtime\python311\python.exe', 'runtime\video313\python.exe', 'runtime\media311\python.exe')
}
$runtimes = foreach ($path in $runtimePaths) {
    [pscustomobject]@{ Runtime = $path; Available = Test-Path -LiteralPath (Join-Path $taskRoot $path) }
}
try {
    $health = Invoke-RestMethod -Uri ($taskBaseUrl + '/api/health') -TimeoutSec 5
    $modules = Invoke-RestMethod -Uri ($taskBaseUrl + '/api/workbench/status') -TimeoutSec 5
    $tasks = Invoke-RestMethod -Uri ($taskBaseUrl + '/api/tasks') -TimeoutSec 5
    $summary = [pscustomobject]@{ ProjectRoot = $taskRoot; ServiceReady = $health.ok; ScraperRunning = $modules.scraper.running; VideoAvailable = $modules.video.available; ActiveTasks = @($tasks.items).Count; Runtimes = @($runtimes) }
    $summary | ConvertTo-Json -Depth 4
} catch {
    [pscustomobject]@{ ProjectRoot = $taskRoot; ServiceReady = $false; Error = 'Local workbench service is not ready. Start Start-Workbench.cmd and retry.'; Runtimes = @($runtimes) } | ConvertTo-Json -Depth 4
    exit 1
}
