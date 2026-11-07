<#
.SYNOPSIS
    Builds release APKs for owner_app and customer_app with the Payment tab
    changes, pointed at an explicit backend URL.

.DESCRIPTION
    Refuses to run without -ApiBaseUrl: there is no default, because a build
    that silently points at whatever AppConfig.baseUrl's own default is (the
    deployed Render backend) is the exact "looked repointed and was not" bug
    app_config.dart's own comment warns about.

    Uses the repo's own documented build sequence for these Flutter apps
    (carevomd.md, "Release AAB command" section):
        flutter clean
        flutter pub get
        gradlew --stop        (the Gradle daemon OOMs on a release build otherwise)
        flutter build apk --release --dart-define=API_BASE_URL=<url>
    The --dart-define name (API_BASE_URL) is the one both owner_app's and
    customer_app's lib/config/app_config.dart already read — nothing here
    invents a new flag or a new default.

    Does not touch any signing file. It does not read, print, or branch on
    the contents of android/key.properties — only the build commands above
    run, and an app without a key.properties in place builds DEBUG-SIGNED,
    exactly as flutter build apk already does on its own.

.PARAMETER ApiBaseUrl
    MANDATORY. The backend base URL to bake into both builds, e.g.
    http://10.0.2.2:8000/api/v1 (Android emulator) or
    http://192.168.1.50:8000/api/v1 (a phone on the same LAN as a locally
    running backend). There is no default — see DESCRIPTION.

.PARAMETER AllowProduction
    Must be passed, IN ADDITION to -ApiBaseUrl, for any URL containing
    "onrender.com". Without it, the script refuses outright. This mission
    runs against a local backend; a production URL reaching this script at
    all is far more likely to be a copy-paste accident than an intent.

.PARAMETER DryRun
    Prints every command this script would run, and the resolved output
    filenames, without invoking flutter, gradlew, or writing anything. Use
    this to verify the script's behavior safely.

.PARAMETER Apps
    Which app(s) to build. Defaults to both. One of: Owner, Customer, Both.

.EXAMPLE
    # Verify behavior without building anything:
    ./scripts/build_payment_tab_apks.ps1 -ApiBaseUrl http://10.0.2.2:8000/api/v1 -DryRun

.EXAMPLE
    # A real build against a local backend reachable from an Android emulator:
    ./scripts/build_payment_tab_apks.ps1 -ApiBaseUrl http://10.0.2.2:8000/api/v1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ApiBaseUrl,

    [switch]$AllowProduction,

    [switch]$DryRun,

    [ValidateSet('Owner', 'Customer', 'Both')]
    [string]$Apps = 'Both'
)

$ErrorActionPreference = 'Stop'

# ---- 1. Print the URL FIRST, before anything else happens. -----------------
Write-Host "API base URL for this build: $ApiBaseUrl" -ForegroundColor Cyan

# ---- 2. Refuse a production URL unless explicitly allowed. -----------------
if ($ApiBaseUrl -match 'onrender\.com') {
    if (-not $AllowProduction) {
        Write-Error (
            "Refusing: -ApiBaseUrl '$ApiBaseUrl' contains 'onrender.com' " +
            "(the deployed production backend). This mission builds against " +
            "a LOCAL backend only. Pass -AllowProduction if you genuinely " +
            "mean to build against production."
        )
        exit 1
    }
    Write-Host "WARNING: building against a production URL (-AllowProduction was passed)." `
        -ForegroundColor Yellow
}

# ---- 3. Derive a short, filesystem-safe host tag for the output name. ------
function Get-HostTag([string]$Url) {
    try {
        $uri = [Uri]$Url
        $tag = $uri.Host
        if ($uri.Port -gt 0 -and $uri.Port -ne 80 -and $uri.Port -ne 443) {
            $tag = "$tag-$($uri.Port)"
        }
    } catch {
        $tag = 'unknown-host'
    }
    # Filesystem-safe: dots and colons are not welcome in a filename on Windows.
    return ($tag -replace '[^a-zA-Z0-9\-]', '-')
}
$hostTag = Get-HostTag $ApiBaseUrl
Write-Host "Output host tag: $hostTag"

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$repoRoot = Split-Path -Parent $PSScriptRoot

# ---- 4. One app's build sequence, exactly as carevomd.md documents it. -----
function Build-FlutterApk {
    param(
        [string]$AppName,       # 'owner_app' | 'customer_app'
        [string]$OutputLabel    # 'owner' | 'customer', for the renamed artifact
    )

    $appDir = Join-Path $repoRoot $AppName
    if (-not (Test-Path $appDir)) {
        Write-Error "Expected Flutter project at '$appDir' but it does not exist."
        exit 1
    }

    $outDir = Join-Path $repoRoot 'build_output'
    $outFile = Join-Path $outDir "$OutputLabel-payment-tab-$hostTag-$timestamp.apk"

    Write-Host "`n=== $AppName ===" -ForegroundColor Green
    Write-Host "Directory: $appDir"
    Write-Host "Will run, in order:"
    Write-Host "  flutter clean"
    Write-Host "  flutter pub get"
    Write-Host "  gradlew --stop"
    Write-Host "  flutter build apk --release --dart-define=API_BASE_URL=$ApiBaseUrl"
    Write-Host "Expected build artifact: $appDir/build/app/outputs/flutter-apk/app-release.apk"
    Write-Host "Will be copied to: $outFile"

    if ($DryRun) {
        Write-Host "[DryRun] No commands executed." -ForegroundColor Yellow
        return
    }

    Push-Location $appDir
    try {
        flutter clean
        if ($LASTEXITCODE -ne 0) { throw "flutter clean failed in $AppName" }

        flutter pub get
        if ($LASTEXITCODE -ne 0) { throw "flutter pub get failed in $AppName" }

        # Stops the Gradle daemon before a release build — documented in
        # carevomd.md as required, or the daemon OOMs during a release build.
        $gradlewCmd = if ($IsWindows -or $env:OS -eq 'Windows_NT') {
            Join-Path $appDir 'android\gradlew.bat'
        } else {
            Join-Path $appDir 'android/gradlew'
        }
        if (Test-Path $gradlewCmd) {
            & $gradlewCmd --stop
        }

        flutter build apk --release --dart-define="API_BASE_URL=$ApiBaseUrl"
        if ($LASTEXITCODE -ne 0) { throw "flutter build apk failed in $AppName" }

        $builtApk = Join-Path $appDir 'build\app\outputs\flutter-apk\app-release.apk'
        if (-not (Test-Path $builtApk)) {
            throw "Expected artifact not found at $builtApk"
        }
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        Copy-Item $builtApk $outFile -Force
        Write-Host "Built: $outFile" -ForegroundColor Green
    } finally {
        Pop-Location
    }
}

if ($Apps -eq 'Owner' -or $Apps -eq 'Both') {
    Build-FlutterApk -AppName 'owner_app' -OutputLabel 'owner'
}
if ($Apps -eq 'Customer' -or $Apps -eq 'Both') {
    Build-FlutterApk -AppName 'customer_app' -OutputLabel 'customer'
}

if ($DryRun) {
    Write-Host "`nDry run complete. No files were built or written." -ForegroundColor Cyan
}
