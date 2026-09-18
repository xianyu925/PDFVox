$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    python -m PyInstaller --noconfirm --clean packaging\PDFVox.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }

    $smokeTest = Start-Process `
        -FilePath (Join-Path $projectRoot "dist\PDFVox\PDFVox.exe") `
        -ArgumentList "--smoke-test" `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($smokeTest.ExitCode -ne 0) {
        throw "Packaged application smoke test failed with exit code $($smokeTest.ExitCode)"
    }

    $compiler = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if (-not $compiler) {
        $compilerCandidates = @(
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
        )
        $compiler = $compilerCandidates |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1
    }
    if (-not $compiler) {
        throw "ISCC.exe was not found. Install Inno Setup 6."
    }
    $appVersion = python -c "from app.version import __version__; print(__version__)"
    if ($LASTEXITCODE -ne 0 -or -not $appVersion) {
        throw "Unable to read the application version"
    }
    & $compiler "/DMyAppVersion=$appVersion" packaging\PDFVox.iss
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
