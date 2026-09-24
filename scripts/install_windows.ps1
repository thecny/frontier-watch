param(
    [string]$At = '09:17'
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') {
    throw 'This installer requires Windows Task Scheduler.'
}

$projectPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runnerPath = Join-Path $PSScriptRoot 'run_windows.ps1'
$pythonPath = (& python -c 'import sys; print(sys.executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Python was not found. Install Python 3.11+ and make python available on PATH.'
}

$secure = Read-Host 'Enter ServerChan Turbo SendKey (input hidden)' -AsSecureString
if ($secure.Length -eq 0) {
    throw 'SendKey cannot be empty.'
}
$secretDirectory = Join-Path $env:LOCALAPPDATA 'FrontierWatch'
$secretPath = Join-Path $secretDirectory 'sendkey.dpapi'
New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
ConvertFrom-SecureString $secure | Set-Content -LiteralPath $secretPath -Encoding UTF8 -NoNewline

$scheduledTime = [datetime]::ParseExact($At, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ProjectPath "{1}" -PythonPath "{2}" -SecretPath "{3}"' -f $runnerPath, $projectPath, $pythonPath, $secretPath
$action = New-ScheduledTaskAction -Execute (Get-Command powershell.exe).Source -Argument $arguments -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -Daily -At $scheduledTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel LeastPrivilege
Register-ScheduledTask -TaskName 'FrontierWatchDaily' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Installed FrontierWatchDaily for $currentUser at $At each day."
Write-Host 'Keep this Windows user signed in. Missed runs start when the task becomes available.'
Write-Host 'Run FrontierWatchDaily manually in Task Scheduler to verify WeChat delivery.'
