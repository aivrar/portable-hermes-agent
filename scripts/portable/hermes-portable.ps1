param(
    [string]$Root = "",
    [switch]$Status,
    [switch]$Desktop,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$HermesArgs
)

$ErrorActionPreference = "Stop"

function Resolve-PortableRoot {
    param([string]$Value)
    if ($Value) {
        return (Resolve-Path -LiteralPath $Value).Path
    }
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}

function New-PortableDirectory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Test-PythonCandidate {
    param(
        [string]$Command,
        [string[]]$Arguments = @()
    )
    try {
        & $Command @Arguments -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            return @{ Command = $Command; Arguments = $Arguments }
        }
    } catch {
        return $null
    }
    return $null
}

function Resolve-HermesPython {
    param([string]$PortableRoot)

    $pathCandidates = @(
        (Join-Path $PortableRoot "venv\Scripts\python.exe"),
        (Join-Path $PortableRoot ".venv\Scripts\python.exe"),
        (Join-Path $PortableRoot "python_embedded\python.exe")
    )
    foreach ($candidate in $pathCandidates) {
        if (Test-Path -LiteralPath $candidate) {
            $resolved = Test-PythonCandidate -Command $candidate
            if ($resolved) { return $resolved }
        }
    }

    $commands = @(
        @{ Command = "py"; Arguments = @("-3.13") },
        @{ Command = "py"; Arguments = @("-3.12") },
        @{ Command = "py"; Arguments = @("-3.11") },
        @{ Command = "python"; Arguments = @() },
        @{ Command = "python3"; Arguments = @() }
    )
    foreach ($candidate in $commands) {
        if (Get-Command $candidate.Command -ErrorAction SilentlyContinue) {
            $resolved = Test-PythonCandidate -Command $candidate.Command -Arguments $candidate.Arguments
            if ($resolved) { return $resolved }
        }
    }

    throw "Hermes portable requires Python >=3.11,<3.14. Install Python or place python.exe under $PortableRoot\python_embedded\."
}

$PortableRoot = Resolve-PortableRoot -Value $Root
$HermesHome = Join-Path $PortableRoot ".hermes"

New-PortableDirectory $HermesHome
New-PortableDirectory (Join-Path $HermesHome "logs")
New-PortableDirectory (Join-Path $HermesHome "plugins")
New-PortableDirectory (Join-Path $HermesHome "skills")
New-PortableDirectory (Join-Path $HermesHome "extensions")

$env:HERMES_HOME = $HermesHome

$python = Resolve-HermesPython -PortableRoot $PortableRoot
Push-Location $PortableRoot
try {
    if ($Status) {
        & $python.Command @($python.Arguments) -m hermes_cli.main portable status --root $PortableRoot
    } elseif ($Desktop) {
        $desktopArgs = @("desktop", "--hermes-root", $PortableRoot, "--cwd", $PortableRoot) + $HermesArgs
        & $python.Command @($python.Arguments) -m hermes_cli.main @desktopArgs
    } else {
        & $python.Command @($python.Arguments) -m hermes_cli.main @HermesArgs
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
