# Install vosk 0.3.50 from GitHub source (not PyPI).
# Tag v0.3.50 has no published win_amd64 wheel — we build it locally with Docker
# (official alphacep MinGW/Kaldi Dockerfile). First image build can take hours.
#
# Override: VOSK_GITHUB_REF, VOSK_FORCE_REBUILD=1

function Get-EnvOrDotEnv {
    param(
        [string]$ProjectRoot,
        [string]$Name
    )
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv -and $fromEnv.Trim()) {
        return $fromEnv.Trim()
    }
    $envFile = Join-Path $ProjectRoot ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match "^\s*$Name=(.+)$") {
                return $Matches[1].Trim()
            }
        }
    }
    return $null
}

function Get-VoskGitHubRef {
    param([string]$ProjectRoot)
    $ref = Get-EnvOrDotEnv -ProjectRoot $ProjectRoot -Name "VOSK_GITHUB_REF"
    if ($ref) { return $ref }
    return "v0.3.50"
}

function Get-Flag {
    param(
        [string]$ProjectRoot,
        [string]$Name
    )
    $raw = Get-EnvOrDotEnv -ProjectRoot $ProjectRoot -Name $Name
    if (-not $raw) { return $false }
    return $raw.ToLower() -in @("1", "true", "yes", "on")
}

function Test-DockerAvailable {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) { return $false }
    & docker info 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Get-CachedVoskWheel {
    param(
        [string]$ProjectRoot,
        [string]$Ref
    )
    $version = $Ref.TrimStart("v")
    $wheelhouse = Join-Path $ProjectRoot "third_party\vosk-api\wheelhouse"
    if (-not (Test-Path $wheelhouse)) { return $null }
    $exact = Get-ChildItem -Path $wheelhouse -Filter "vosk-$version-*.whl" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($exact) { return $exact.FullName }
    # Accept any vosk wheel if version is embedded differently
    $any = Get-ChildItem -Path $wheelhouse -Filter "vosk-*.whl" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($any) { return $any.FullName }
    return $null
}

function Build-VoskWheelWithDocker {
    param(
        [Parameter(Mandatory)] [string]$ProjectRoot,
        [Parameter(Mandatory)] [string]$Ref
    )

    if (-not (Test-DockerAvailable)) {
        throw @"
vosk $Ref requires a local Docker wheel build (no win_amd64 asset on GitHub).
Install Docker Desktop, start it (Linux containers), then re-run install.ps1 / fix.ps1.
"@
    }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        throw "git is required to clone alphacep/vosk-api@$Ref"
    }

    $thirdParty = Join-Path $ProjectRoot "third_party"
    $srcDir = Join-Path $thirdParty "vosk-api"
    $wheelhouse = Join-Path $srcDir "wheelhouse"
    $buildScriptHost = Join-Path $ProjectRoot "build-vosk-wheel-win.sh"

    if (-not (Test-Path $buildScriptHost)) {
        throw "Missing $buildScriptHost"
    }

    New-Item -ItemType Directory -Force -Path $thirdParty | Out-Null

    if (Test-Path $srcDir) {
        Write-Host "Updating vosk-api checkout at $srcDir (ref $Ref)..."
        Push-Location $srcDir
        try {
            & git fetch --depth 1 origin "refs/tags/${Ref}:refs/tags/${Ref}" 2>$null
            & git fetch --depth 1 origin $Ref 2>$null
            & git checkout -f $Ref
            if ($LASTEXITCODE -ne 0) {
                throw "git checkout $Ref failed"
            }
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "Cloning alphacep/vosk-api@$Ref ..."
        & git clone --depth 1 --branch $Ref "https://github.com/alphacep/vosk-api.git" $srcDir
        if ($LASTEXITCODE -ne 0) {
            throw "git clone vosk-api@$Ref failed"
        }
    }

    Copy-Item -Force $buildScriptHost (Join-Path $srcDir "build-vosk-wheel-win.sh")

    $imageTag = "jarvis-kaldi-win:latest"
    $dockerfile = Join-Path $srcDir "travis/Dockerfile.win"
    if (-not (Test-Path $dockerfile)) {
        throw "Dockerfile not found: $dockerfile"
    }

    Write-Host ""
    Write-Host "Building Docker image $imageTag (first time builds Kaldi — can take 1–3+ hours)..."
    & docker build --file $dockerfile --tag $imageTag (Join-Path $srcDir "travis")
    if ($LASTEXITCODE -ne 0) {
        throw "docker build of Kaldi/MinGW image failed"
    }

    if (Test-Path $wheelhouse) {
        Remove-Item -Recurse -Force $wheelhouse
    }
    New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null

    $mountPath = $srcDir -replace '\\', '/'
    if ($mountPath -match '^([A-Za-z]):') {
        $drive = $Matches[1].ToLower()
        $mountPath = "/$drive" + $mountPath.Substring(2)
    }

    Write-Host "Cross-compiling libvosk.dll and packing wheel for $Ref ..."
    & docker run --rm -v "${mountPath}:/io" $imageTag bash /io/build-vosk-wheel-win.sh
    if ($LASTEXITCODE -ne 0) {
        throw "Docker vosk wheel build failed"
    }

    $wheel = Get-ChildItem -Path $wheelhouse -Filter "vosk-*.whl" | Select-Object -First 1
    if (-not $wheel) {
        throw "No vosk-*.whl produced in $wheelhouse"
    }
    Write-Host "Built local wheel: $($wheel.FullName)"
    return $wheel.FullName
}

function Install-VoskFromGitHub {
    param(
        [Parameter(Mandatory)] [string]$PythonExe,
        [Parameter(Mandatory)] [string]$ProjectRoot
    )

    $ref = Get-VoskGitHubRef -ProjectRoot $ProjectRoot
    $forceRebuild = Get-Flag -ProjectRoot $ProjectRoot -Name "VOSK_FORCE_REBUILD"
    $version = $ref.TrimStart("v")

    Write-Host "Target vosk: $ref (GitHub source build, not PyPI)"

    $wheelPath = $null
    if (-not $forceRebuild) {
        $wheelPath = Get-CachedVoskWheel -ProjectRoot $ProjectRoot -Ref $ref
        if ($wheelPath) {
            Write-Host "Using cached local wheel: $wheelPath"
        }
    }

    if (-not $wheelPath) {
        Write-Host "Building vosk $ref wheel via Docker (no published win_amd64 wheel for this tag)..."
        $wheelPath = Build-VoskWheelWithDocker -ProjectRoot $ProjectRoot -Ref $ref
    }

    Write-Host "Installing vosk from $wheelPath"
    & $PythonExe -m pip install --upgrade --force-reinstall $wheelPath
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed to install vosk from $wheelPath"
    }

    $check = & $PythonExe -c "import vosk; print(getattr(vosk, '__version__', 'unknown'))"
    Write-Host "vosk import OK, version reported: $check"
    if ($check -and ($check -notmatch [regex]::Escape($version)) -and ($check -ne "unknown")) {
        Write-Host "WARNING: expected version containing '$version', got '$check'"
    }
}
