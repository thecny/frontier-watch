param(
    [Parameter(Mandatory = $true)][string]$ProjectPath,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [string]$SecretPath = (Join-Path $env:LOCALAPPDATA 'FrontierWatch\sendkey.dpapi'),
    [switch]$Sample
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') {
    throw 'This runner requires Windows DPAPI.'
}
if (-not (Test-Path -LiteralPath $SecretPath -PathType Leaf)) {
    throw 'ServerChan credential file is missing. Run scripts\install_windows.ps1 first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectPath 'frontier_watch') -PathType Container)) {
    throw 'The project path does not contain frontier_watch.'
}

$encrypted = (Get-Content -LiteralPath $SecretPath -Raw).Trim()
$secure = ConvertTo-SecureString $encrypted
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$exitCode = 1
try {
    $env:SERVERCHAN_SENDKEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $env:PUSH_CHANNEL = 'serverchan'
    $env:PYTHONIOENCODING = 'utf-8'
    Push-Location -LiteralPath $ProjectPath
    try {
        if ($Sample) {
            & $PythonPath -m frontier_watch --sample
        } else {
            & $PythonPath -m frontier_watch
        }
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    Remove-Item Env:SERVERCHAN_SENDKEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}
exit $exitCode
