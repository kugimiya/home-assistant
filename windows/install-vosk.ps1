# Shared: install vosk from GitHub Releases (not PyPI).
function Get-VoskGitHubRef {
    param([string]$ProjectRoot)

    if ($env:VOSK_GITHUB_REF) {
        return $env:VOSK_GITHUB_REF.Trim()
    }
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*VOSK_GITHUB_REF=(.+)$') {
                return $Matches[1].Trim()
            }
        }
    }
    return "v0.3.50"
}

function Get-VoskGitHubWheelUrl {
    param([string]$Ref)

    $version = $Ref.TrimStart("v")
    return "https://github.com/alphacep/vosk-api/releases/download/$Ref/vosk-$version-py3-none-win_amd64.whl"
}

function Install-VoskFromGitHub {
    param(
        [Parameter(Mandatory)] [string]$PythonExe,
        [Parameter(Mandatory)] [string]$ProjectRoot
    )

    $ref = Get-VoskGitHubRef -ProjectRoot $ProjectRoot
    $wheel = Get-VoskGitHubWheelUrl -Ref $ref
    Write-Host "Installing vosk from GitHub release $ref (not PyPI)"
    Write-Host "  $wheel"
    & $PythonExe -m pip install --upgrade $wheel
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed to install vosk from GitHub ($ref)"
    }
}
