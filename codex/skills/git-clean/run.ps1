param(
    [Parameter(Mandatory = $true, Position = 0)][ValidateSet('audit', 'sync', 'report')][string]$Script,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)

$ErrorActionPreference = 'Stop'

$git = (Get-Command git -ErrorAction Stop).Source
$dir = Split-Path -Parent $git
$bash = $null
while ($dir) {
    $cand = Join-Path $dir 'bin\bash.exe'
    if (Test-Path $cand) { $bash = $cand; break }
    $parent = Split-Path -Parent $dir
    if ($parent -eq $dir) { break }
    $dir = $parent
}
if (-not $bash) {
    Write-Error 'Nie znaleziono Git Bash (bin\bash.exe obok git.exe). Zainstaluj Git for Windows.'
    exit 2
}

# Polskie znaki: bash.exe pisze UTF-8, konsola PS 5.1 domyślnie czyta OEM.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'

$sh = (Join-Path $PSScriptRoot "$Script.sh") -replace '\\', '/'
# Git's Unix helpers may be missing from the inherited Windows PATH.
# Positional parameters preserve spaces and shell metacharacters in paths/arguments.
& $bash -c 'export PATH="/usr/bin:/bin:$PATH"; exec bash "$@"' -- $sh @Rest
exit $LASTEXITCODE
