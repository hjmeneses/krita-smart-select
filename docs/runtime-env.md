# Runtime Environment

Smart Select uses a managed user-level runtime for BiRefNet inference. The
plugin source tree must remain free of runtime installs and model checkpoints.

## Cache Layout

Primary location comes from Krita user data via C++ `QStandardPaths`:

```text
<krita-app-data>/smart_select/
  models/
    birefnet_hr_matting/
      snapshot/
        model.safetensors
        config.json
        *.py
      model.json
  runtime/
    venv/
    pip-cache/
    runtime.json
```

Fallback:

```text
~/.local/share/krita-smart-select/
  models/
  runtime/
```

## Runtime Version

Current runtime:

```text
birefnet-runtime-v1
```

If `runtime.json` has a different runtime version, the worker recreates the
managed venv. It does not delete model caches.

## Runtime Python

The runtime requires Python 3.12 (`RUNTIME_PYTHON_VERSION`). The worker imports
torch from the managed venv into its own interpreter, so the worker itself must
run on 3.12 and the venv is created from that interpreter.

`worker_launcher.py` re-execs the worker on 3.12, trying in order:

1. Windows `py -3.12`;
2. `uv python find 3.12` (`uv` from `PATH`, `~/.local/bin` or `~/.cargo/bin`);
3. `python3.12`/`python3`/`python` on `PATH` whose version is 3.12.

On Windows the loader always uses the launcher, regardless of `uv`. If no 3.12
is found the worker still starts and `ensure_runtime` fails before creating the
venv with `RuntimePythonMismatch` (log event `runtime.python.mismatch`), so a
newer host Python (for example 3.15, which has no CUDA torch wheels) never
produces a half-installed venv.

## Manual Install

The runtime can be prebuilt outside Krita (Krita closed). It is accepted as
long as `venv/` is built from Python 3.12 with the packages in
`worker/runtime_manifest.py` and `runtime.json` carries the current
`runtime_version` and `"python_version": "3.12"`:

```powershell
$root = "$env:APPDATA\krita\smart_select\runtime"
py -3.12 -m venv "$root\venv"
uv pip install --python "$root\venv\Scripts\python.exe" `
  --index-url https://download.pytorch.org/whl/cu124 "torch>=2.5.1,<3" "torchvision>=0.20.1,<1"
uv pip install --python "$root\venv\Scripts\python.exe" <PYTHON_PACKAGES from runtime_manifest.py>
```

The worker validates imports on the next run and rewrites `runtime.json`.

## Dependencies

Runtime installs:

- PyTorch/torchvision from CUDA 12.4 wheel index;
- `numpy`;
- `pillow`;
- `transformers`;
- `huggingface-hub`;
- `safetensors`;
- `timm`;
- `kornia`;
- `einops`;
- `scipy`;
- `scikit-image`;
- `accelerate`.

## Validation

Validation imports:

- `torch`;
- `PIL.Image`;
- `torchvision.transforms`;
- `transformers.AutoModelForImageSegmentation`;
- `huggingface_hub.snapshot_download`;
- `safetensors`.

CUDA availability is reported but not required. Device policy is CUDA first,
CPU only when CUDA is unavailable, and CUDA OOM is returned as a user-safe error
without silent CPU retry.

## GPU Precision

CUDA inference runs in FP16 by default. FP16 is skipped up front on GPUs known
to overflow in half precision (currently any name containing `GTX 16`, e.g. GTX
1650/1660), which otherwise return an all-NaN mask that surfaces as
`selection is empty`. As a safety net for any other GPU, an FP16 prediction
containing NaN is re-run in FP32 and FP16 stays disabled for the rest of the
worker process (log event `alpha_model.predict.fp16_nan`). BF16 is not an
option: BiRefNet's deformable convolution has no BF16 kernel.

## GPU Memory Policy

The worker keeps the on-disk runtime and model snapshot caches, but unloads the
CUDA BiRefNet model and clears the PyTorch CUDA allocator cache after each
lasso job. This avoids VRAM growth inside Krita after repeated selections. The
tradeoff is that the next selection reloads the model from the verified local
snapshot.

## Security

BiRefNet uses Hugging Face custom code through `trust_remote_code=True`. This is
allowed only for the pinned curated repo/revision in `docs/models.md`.
User-provided model repos are out of scope.
