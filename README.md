# Krita Smart Select (Windows & Linux)

A cross-platform **Windows & Linux** edition of [Krita Smart Select](https://github.com/BMFreed/krita-smart-select)
— an AI-assisted lasso selection plugin for Krita 5.3.x that creates soft alpha object
masks locally using **BiRefNet HR Matting**.

> **📦 Pre-built Windows Release Available:** Download **`krita-smart-select-windows-x64-0.1.2.zip`** directly from [**Releases**](https://github.com/hjmeneses/krita-smart-select/releases/latest) — no C++ compilation required.

## Relationship to Upstream

The original project by [BMFreed](https://github.com/BMFreed/krita-smart-select) targets Linux + Krita 5.3.1, and [theCosmicCrafter/krita-smart-select-windows](https://github.com/theCosmicCrafter/krita-smart-select-windows) documented the initial KDE CI Qt5 build setup. This fork completes the Windows port, ships pre-compiled Windows binaries (`kritasmartselect.dll`), fixes Windows Python runtime/process launching, adds a fast incremental C++ build script, and introduces automatic low-VRAM scaling for GPUs with 4–6 GB VRAM.

| | Upstream (`BMFreed`) | This Fork (`hjmeneses`) |
| --- | --- | --- |
| **Platform** | Linux | **Windows 10/11 (x64)** & Linux |
| **Pre-built Release** | Linux `.zip` / `.tar.gz` | **Windows `.zip`** (`krita-smart-select-windows-x64-0.1.2.zip`) |
| **Compiler** | GCC | LLVM-MinGW Clang (UCRT x86_64) / GCC |
| **Qt/Krita deps** | System packages | KDE CI artifact cache + installed Krita 5.3.x ABI |
| **Native artifact** | `kritasmartselect.so` | `kritasmartselect.dll` + Clang runtime DLLs |
| **GPU VRAM Support** | 8 GB+ (`2048×2048`) | **4 GB+ auto-scaling** (`2048×2048` / `1024×1024` / `768×768` FP16 + CPU fallback) |
| **License** | GPL-3.0-only | GPL-3.0-only |

## How It Works

Krita Smart Select is a native canvas tool for **Krita 5.3.x** that creates soft
AI-assisted selections from a user-drawn lasso region.

The tool works like a native lasso selection tool first: draw or adjust the
area around an object, then press **`Select object with AI`** in the Tool Options docker. The background worker runs
`BiRefNet HR Matting` on the selected crop and applies the returned soft alpha as
a standard Krita pixel selection.

## Features

- Native Krita canvas tool and Tool Options integration.
- Replace / add / subtract / intersect selection actions through Krita selection
  semantics (`Shift`, `Alt`, etc.).
- Soft alpha selection masks instead of binary-only cutouts (preserves hair, glass, and semi-transparent edges).
- Managed user-level Python 3.12 runtime for inference dependencies (`%APPDATA%\krita\smart_select\runtime` on Windows).
- Pinned BiRefNet HR Matting model snapshot cache (`%APPDATA%\krita\smart_select\models` on Windows).
- Automatic VRAM-aware resolution scaling (`2048×2048` on 8 GB+ GPUs, `1024×1024` / `768×768` on 4–6 GB GPUs, or CPU fallback).
- Structured logs with OpenTelemetry-compatible field names (emitted to Krita's Qt debug output; see [Troubleshooting](#troubleshooting)).

## Examples

| Before | After |
| --- | --- |
| <img src="docs/assets/examples/glasses-before.png" alt="Lasso region around a man wearing glasses" width="360"> | <img src="docs/assets/examples/glasses-after.png" alt="AI selection result preserving glasses transparency" width="360"> |

Smart Select preserves transparent surfaces and subtle see-through details, such
as eyeglass lenses.

| Before | After |
| --- | --- |
| <img src="docs/assets/examples/hair-before.png" alt="Lasso region around a woman with long hair" width="360"> | <img src="docs/assets/examples/hair-after.png" alt="AI selection result preserving hair detail" width="360"> |

Soft alpha selection keeps fine hair detail instead of reducing the subject to a
hard binary cutout.

| Before | After |
| --- | --- |
| <img src="docs/assets/examples/laptop-before.png" alt="Lasso region around a laptop" width="360"> | <img src="docs/assets/examples/laptop-after.png" alt="AI selection result for the laptop" width="360"> |

| Before | After |
| --- | --- |
| <img src="docs/assets/examples/car-before.png" alt="Lasso region around a car" width="420"> | <img src="docs/assets/examples/car-after.png" alt="AI selection result for the car" width="420"> |

## Requirements & GPU Compatibility

### System Requirements
- **OS:** Windows 10/11 (x64) or Linux (x64).
- **Krita:** **5.3.x** (tested on Krita 5.3.4.1 on Windows and 5.3.1 on Linux).
- **Python 3.12** (exactly 3.12 — the runtime is pinned to it). Newer versions
  such as 3.13–3.15 can stay installed alongside it; the plugin picks 3.12
  automatically. On Windows it is located via the `py` launcher (`py -3.12`),
  then `uv python find 3.12`, then `PATH`.
  - Use a regular python.org / `winget` install. The **Microsoft Store** Python
    is skipped because it redirects writes under `%APPDATA%`.
  - `uv` is optional on Windows (it is still used on Linux).
- **Disk Space:** ~5.5 GB free in `%APPDATA%\krita\smart_select`: the managed
  PyTorch CUDA runtime (~4.7 GB installed) and the `BiRefNet_HR-matting`
  weights (~444 MB).
- **Internet** only for the one-time runtime and model download.

### GPU & VRAM Scaling
| Hardware | Inference Mode | Input Resolution | Typical Speed |
| --- | --- | --- | --- |
| **NVIDIA GPU ≥ 6.5 GB VRAM** (RTX 2070+, 3060+, 4060+) | CUDA FP16 | `2048×2048` (with automatic `1024×1024` OOM fallback) | ~0.5 – 1.5 s |
| **NVIDIA GPU 4 GB – 6 GB VRAM** (GTX 1650 Ti, RTX 3050 Laptop, etc.) | CUDA FP16 | `1024×1024` (with automatic `768×768` OOM fallback) | ~1 – 2.5 s |
| **No NVIDIA GPU / CPU Fallback** | CPU FP32 | `1024×1024` | ~8 – 20 s |

## User Installation (Windows)

1. Install Python 3.12 if you haven't already, and check that it is found:
   ```powershell
   winget install -e --id Python.Python.3.12
   py -3.12 --version   # should print Python 3.12.x
   ```
2. Download **`krita-smart-select-windows-x64-0.1.2.zip`** from the [**Latest Release**](https://github.com/hjmeneses/krita-smart-select/releases/latest).
3. Open Krita and go to **`Tools` → `Scripts` → `Import Python Plugin from File...`**.
4. Select the downloaded `.zip` file and **restart Krita**.
5. Verify that **`Smart Select`** is enabled under **`Settings` → `Configure Krita...` → `Python Plugin Manager`**.
6. In the **Toolbox** (under the *Select* section), choose the **Smart Select** tool.

### ⏳ What to Expect on First Use
- The **very first time** you draw a lasso and click **`Select object with AI`**, the worker automatically creates an isolated Python 3.12 virtual environment under `%APPDATA%\krita\smart_select\runtime`, installs PyTorch + CUDA 12.4 wheels (~2.5 GB download), and downloads the `ZhengPeng7/BiRefNet_HR-matting` checkpoint (~444 MB) into `%APPDATA%\krita\smart_select\models`.
- **This initial setup takes several minutes** depending on your connection. The
  progress bar in Tool Options stays busy meanwhile — do not close Krita.
- **Subsequent selections run locally** with no internet connection. The model is
  unloaded from VRAM after each selection, so every run includes a short model
  load.

### Optional: Pre-install the Runtime and Model

To avoid the wait inside Krita, prepare both with Krita closed. The runtime
steps are in [Runtime Environment → Manual Install](docs/runtime-env.md#manual-install);
the model can then be fetched and verified with the worker's own cache code:

```powershell
$venvPy = "$env:APPDATA\krita\smart_select\runtime\venv\Scripts\python.exe"
& $venvPy -c @"
import os, sys; from pathlib import Path
sys.path.insert(0, r'$env:APPDATA\krita\pykrita\smart_select\worker')
from alpha_model_cache import ModelCache
from alpha_model_registry import default_model_id, get_model_spec
root = Path(os.environ['APPDATA']) / 'krita' / 'smart_select' / 'models'
print(ModelCache(root).ensure_downloaded(get_model_spec(default_model_id()), lambda *a: None).state)
"@
```

It should print `verified`.

### Package Layout Inside the Windows ZIP
```text
smart_select.desktop
smart_select/
  __init__.py
  extension.py
  worker_launcher.py
  SmartSelectTool.action
  lib/
    kritasmartselect.dll
    libc++.dll
    libunwind.dll
    libwinpthread-1.dll
  worker/
    smart_select_worker.py
    birefnet_inference.py
    runtime_env.py
    ...
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `alpha runtime requires Python 3.12…` | No Python 3.12 found. | Install it (see above), check `py -3.12 --version`, restart Krita. |
| `alpha runtime setup failed` | A `pip install` step failed (network, disk space, or an old runtime built from the wrong Python). | Close Krita, delete `%APPDATA%\krita\smart_select\runtime\venv`, retry. Check that `%APPDATA%\krita\smart_select\runtime\venv\pyvenv.cfg` says `version = 3.12.x`. |
| `alpha runtime dependencies are not available` | The venv exists but `torch`/`transformers` fail to import. | Same as above: delete `venv` and let it rebuild. |
| `model download failed` / `model verification failed` | Interrupted or partial download. | Delete `%APPDATA%\krita\smart_select\models\birefnet_hr_matting` and retry. |
| `selection is empty` on every attempt | The GPU returns NaN in FP16 (GTX 16xx). Handled automatically since the FP16 fallback; on older builds this always fails. | Update the plugin. If it persists, check that the lasso covers visible (non-transparent) pixels of the active layer. |
| `alpha extraction ran out of GPU memory` | Lasso crop too large for the GPU. | Use a tighter lasso region; close other GPU-heavy apps. |
| Button stays busy for a long time | First-run setup in progress (see above). | Wait; it only happens once. |

**Check your setup** from PowerShell:

```powershell
Get-Content "$env:APPDATA\krita\smart_select\runtime\runtime.json"   # runtime_version, python_version 3.12, cuda_available
Get-Content "$env:APPDATA\krita\smart_select\runtime\venv\pyvenv.cfg" # version = 3.12.x
Get-ChildItem "$env:APPDATA\krita\smart_select\models" -Recurse -Filter model.safetensors
```

**Logs:** the plugin and worker write `[SmartSelect]` / `[SmartSelectWorker]`
structured lines to Krita's Qt debug output, **not** to `krita.log`. On Windows,
capture them with [DebugView](https://learn.microsoft.com/sysinternals/downloads/debugview)
while reproducing the problem. Runtime install failures are logged as
`runtime.process.failed` with the tail of the `pip` output.

### Uninstall / Full Reset

1. Close Krita.
2. Delete `%APPDATA%\krita\pykrita\smart_select` and `%APPDATA%\krita\pykrita\smart_select.desktop` (the plugin).
3. Delete `%APPDATA%\krita\smart_select` (runtime and model caches, ~5 GB).

To only force a clean runtime rebuild, delete just `%APPDATA%\krita\smart_select\runtime`.

## Building from Source on Windows

We provide two ways to build `kritasmartselect.dll` on Windows:

### Fast Incremental Build (`scripts/fast_build_windows.py` — Recommended)
Once you have extracted [LLVM-MinGW UCRT x86_64](https://github.com/mstorsjo/llvm-mingw/releases) and fetched the KDE CI Qt5/KF5 headers (see [docs/windows/build.md](docs/windows/build.md)), `scripts/fast_build_windows.py` configures CMake to generate export headers and `compile_commands.json`, compiles only the 13 C++ files of `kritasmartselect` + Qt MOC/RCC sources, and links directly against your installed Krita 5.3.x DLLs in **under 15 seconds** (without compiling all of Krita):

```powershell
$env:KRITA_SRC = "F:\krita-work\krita-src"
$env:KRITA_BUILD = "F:\krita-work\build-windows"
$env:KRITA_INSTALL = "F:\krita-work\krita\_install"
$env:LLVM_MINGW = "F:\krita-work\llvm-mingw\llvm-mingw-20261020-ucrt-x86_64"
$env:KRITA_BIN = "C:\Program Files\Krita (x64)\bin"

python scripts\fast_build_windows.py
```

This builds `kritasmartselect.dll` (output in `$env:KRITA_BUILD\bin`) and packages `dist\krita-smart-select-windows-x64-0.1.2.zip`.

To test a local build without re-importing the ZIP, close Krita and copy
`dist\python-plugin\smart_select\*` over `%APPDATA%\krita\pykrita\smart_select\`.
Changes limited to Python files (`worker/`, `python/smart_select/`) need no
C++ rebuild — copy them and restart Krita.

Run the worker unit tests with Python 3.12:

```powershell
$mods = Get-ChildItem tests\worker -Filter test_*.py | ForEach-Object { "tests.worker.$($_.BaseName)" }
py -3.12 -m unittest @mods
```

### Full Source Tree Build
See [docs/windows/build.md](docs/windows/build.md) and `scripts/build-windows.bat` for full Krita tree build instructions, or `scripts/build-krita-5.3.1.sh` for Linux.

## Documentation

- [Windows Build Guide](docs/windows/build.md)
- [Product Scope](docs/product-scope.md)
- [Architecture](docs/architecture.md)
- [Worker Protocol](docs/worker-protocol.md)
- [Snapshot And Temporary Files](docs/snapshot-and-temp-files.md)
- [Models](docs/models.md)
- [Runtime Environment](docs/runtime-env.md)
- [Observability](docs/engineering/observability.md)
- [Typing](docs/engineering/typing.md)
- [Testing](docs/engineering/testing.md)
- [Code Style](docs/engineering/code-style.md)
- [Licensing](docs/licensing.md)
- [Contributing](CONTRIBUTING.md)

## Acknowledgements

Krita Smart Select builds on ideas, APIs and open-source work from:

- **[BMFreed/krita-smart-select](https://github.com/BMFreed/krita-smart-select)** — Original creator of Krita Smart Select.
- **[theCosmicCrafter/krita-smart-select-windows](https://github.com/theCosmicCrafter/krita-smart-select-windows)** — Initial Windows CMake/KDE CI build documentation.
- **[Krita](https://krita.org/)** and the KDE Krita project, whose native tool, selection and plugin APIs make this canvas-integrated workflow possible.
- **[BiRefNet](https://github.com/ZhengPeng7/BiRefNet)**, especially the `ZhengPeng7/BiRefNet_HR-matting` model used for direct soft-alpha extraction.
- **[Krita Vision Tools](https://github.com/Acly/krita-ai-tools)**, which provided a useful reference for ML-assisted Krita tooling.
- **[CorridorKey](https://github.com/nikopueringer/CorridorKey)**, which helped inform the product direction toward alpha-first, plug-and-play matting.

## License

Krita Smart Select is licensed under GPL-3.0-only. See [LICENSE](LICENSE)
and [docs/licensing.md](docs/licensing.md).
