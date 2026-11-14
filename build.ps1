$ErrorActionPreference = "Stop"
Push-Location -LiteralPath $PSScriptRoot
try {
    python -m PyInstaller --noconfirm --clean PokemonRedSaveEditor.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller exit code $LASTEXITCODE"
    }
    python tools/package_release.py
    if ($LASTEXITCODE -ne 0) {
        throw "Release packaging exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
