<#
.SYNOPSIS
    Package the Windows release ZIP for Krita Smart Select.

.DESCRIPTION
    Assembles the installable plugin layout matching Krita's Python Plugin Importer:
      smart_select.desktop
      smart_select/
        __init__.py
        extension.py
        worker_launcher.py
        SmartSelectTool.action
        worker/
          *.py
        lib/
          kritasmartselect.dll
          libc++.dll
          libunwind.dll
          libwinpthread-1.dll
#>
param(
    [Parameter(Mandatory)]
    [string]$Version,

    [Parameter(Mandatory)]
    [string]$BuildDir,

    [string]$RuntimeDlls
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path "$PSScriptRoot\.."
$DistDir = Join-Path $RootDir "dist"
$PluginRoot = Join-Path $DistDir "python-plugin"
$StageDir = Join-Path $PluginRoot "smart_select"

if (Test-Path $PluginRoot) { Remove-Item -Recurse -Force $PluginRoot }
New-Item -ItemType Directory -Path "$StageDir\lib" -Force | Out-Null
New-Item -ItemType Directory -Path "$StageDir\worker" -Force | Out-Null

# Copy desktop descriptor to ZIP root
Copy-Item "$RootDir\python\smart_select.desktop" $PluginRoot

# Copy Python files
Copy-Item "$RootDir\python\smart_select\*.py" $StageDir

# Copy worker Python files
Copy-Item "$RootDir\worker\*.py" "$StageDir\worker\"

# Copy action file into package and actions folder
Copy-Item "$RootDir\plugin\SmartSelectTool.action" $StageDir
$ActionDir = Join-Path $DistDir "actions"
New-Item -ItemType Directory -Path $ActionDir -Force | Out-Null
Copy-Item "$RootDir\plugin\SmartSelectTool.action" $ActionDir

# Copy native DLL
$NativeDllCandidates = @(
    (Join-Path $BuildDir "bin\kritasmartselect.dll"),
    (Join-Path $BuildDir "bin\libkritasmartselect.dll"),
    (Join-Path $BuildDir "plugins\tools\krita-smart-select\kritasmartselect.dll"),
    (Join-Path $BuildDir "plugins\tools\krita-smart-select\libkritasmartselect.dll")
)
$NativeDll = $NativeDllCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $NativeDll) {
    Write-Error "Native DLL not found in $BuildDir"
    exit 1
}
Copy-Item $NativeDll "$StageDir\lib\kritasmartselect.dll"

# Copy Clang runtime DLLs
if (-not $RuntimeDlls) {
    $RuntimeDlls = $env:LLVM_MINGW + "\x86_64-w64-mingw32\bin"
}

foreach ($dll in @("libc++.dll", "libunwind.dll", "libwinpthread-1.dll")) {
    $src = Join-Path $RuntimeDlls $dll
    if (Test-Path $src) {
        Copy-Item $src "$StageDir\lib\"
    } else {
        Write-Warning "Runtime DLL not found: $src"
    }
}

# Create ZIP with forward-slash paths for Krita's importer
$ZipName = "krita-smart-select-windows-x64-$Version.zip"
$ZipPath = Join-Path $DistDir $ZipName
if (Test-Path $ZipPath) { Remove-Item $ZipPath }

python -c "
import pathlib, zipfile
root = pathlib.Path(r'$PluginRoot')
out = pathlib.Path(r'$ZipPath')
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in sorted(root.rglob('*')):
        if p.is_file():
            zf.write(p, p.relative_to(root).as_posix())
"

Write-Host "## Package created: $ZipPath"
