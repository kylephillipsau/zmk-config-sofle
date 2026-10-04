# Build sofle-status for Windows, put it in ~/.local/bin, and start its agent now and at every
# sign-in (HKCU\Software\Microsoft\Windows\CurrentVersion\Run, "Sofle Status"). The agent logs to
# %LOCALAPPDATA%\sofle-status\sofle-status.log.
#
#   powershell -ExecutionPolicy Bypass -File host\windows\install.ps1
$ErrorActionPreference = 'Stop'
$bin = Join-Path $HOME '.local\bin'
$agent = Join-Path $bin 'sofle-status-agent.exe'

cargo build --release --manifest-path (Join-Path $PSScriptRoot 'Cargo.toml')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# The agent holds its program open, so stop it first.
Get-Process sofle-status-agent -ErrorAction SilentlyContinue | Stop-Process -Force -PassThru |
    Wait-Process -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force $bin | Out-Null
foreach ($name in 'sofle-status.exe', 'sofle-status-agent.exe') {
    $target = Join-Path $bin $name
    # Windows can't replace a program while it runs (a hook, say), but it can rename it.
    if (Test-Path $target) { Move-Item $target "$target.old" -Force }
    Copy-Item (Join-Path $PSScriptRoot "target\release\$name") $target
}
Remove-Item (Join-Path $bin '*.exe.old') -ErrorAction SilentlyContinue

Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' 'Sofle Status' "`"$agent`""
Start-Process $agent
"installed $bin\sofle-status.exe; the agent is running and starts at every sign-in"

$settings = Join-Path $HOME '.claude\settings.json'
if (-not (Test-Path $settings) -or -not (Select-String -Path $settings -Pattern 'sofle-status' -Quiet)) {
    "Claude Code doesn't run sofle-status yet: add the hooks and status line in KYLES_SOFLE.md to $settings"
}
