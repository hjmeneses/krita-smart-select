from __future__ import annotations

import gc
import importlib
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alpha_model_registry import ModelSpec
from observability import log_event
from runtime_env import RuntimeReady


class BiRefNetInferenceError(RuntimeError):
    pass


class InferenceOutOfMemory(BiRefNetInferenceError):
    pass


class InferenceFailed(BiRefNetInferenceError):
    pass


@dataclass(frozen=True)
class BiRefNetResult:
    crop_alpha: bytes
    width: int
    height: int
    device: str
    torch_version: str | None
    cuda_available: bool
    duration_ms: int


_MODEL_CACHE: dict[tuple[str, str, str, bool], Any] = {}


def release_runtime_memory() -> None:
    model_count = len(_MODEL_CACHE)
    torch: Any | None = None
    cuda_available = False
    allocated_before: int | None = None
    reserved_before: int | None = None
    allocated_after: int | None = None
    reserved_after: int | None = None

    try:
        torch = importlib.import_module("torch")
        cuda_available = bool(torch.cuda.is_available())
        if cuda_available:
            allocated_before = int(torch.cuda.memory_allocated())
            reserved_before = int(torch.cuda.memory_reserved())
    except Exception:
        torch = None

    models = list(_MODEL_CACHE.values())
    _MODEL_CACHE.clear()
    for cached_model in models:
        with suppress(Exception):
            cached_model.to("cpu")
    del models
    if "cached_model" in locals():
        del cached_model
    gc.collect()

    if torch is not None and cuda_available:
        with suppress(Exception):
            torch.cuda.empty_cache()
        with suppress(Exception):
            torch.cuda.ipc_collect()
        try:
            allocated_after = int(torch.cuda.memory_allocated())
            reserved_after = int(torch.cuda.memory_reserved())
        except Exception:
            pass

    log_event(
        "alpha_model.memory.released",
        component="birefnet",
        **{
            "model.cache.entries": model_count,
            "cuda.available": cuda_available,
            "cuda.memory.allocated_before": allocated_before,
            "cuda.memory.reserved_before": reserved_before,
            "cuda.memory.allocated_after": allocated_after,
            "cuda.memory.reserved_after": reserved_after,
        },
    )


def _candidate_attempts(
    torch: Any, cuda_available: bool, default_resolution: int
) -> list[tuple[str, int]]:
    if not cuda_available:
        return [("cpu", min(default_resolution, 1024))]

    total_vram_gb = 8.0
    with suppress(Exception):
        props = torch.cuda.get_device_properties(0)
        total_vram_gb = float(props.total_memory) / (1024.0**3)

    if total_vram_gb < 6.5:
        return [
            ("cuda", min(default_resolution, 1024)),
            ("cuda", 768),
            ("cpu", 1024),
        ]
    return [
        ("cuda", default_resolution),
        ("cuda", 1024),
        ("cpu", 1024),
    ]


def predict_alpha(
    spec: ModelSpec,
    snapshot_dir: Path,
    _runtime_ready: RuntimeReady,
    crop_image_array: object,
) -> BiRefNetResult:
    torch = importlib.import_module("torch")
    image_module = importlib.import_module("PIL.Image")
    numpy_module = importlib.import_module("numpy")
    transforms = importlib.import_module("torchvision.transforms")

    cuda_available = bool(torch.cuda.is_available())
    crop_image = image_module.fromarray(crop_image_array).convert("RGB")
    width, height = crop_image.size

    attempts = _candidate_attempts(torch, cuda_available, spec.input_resolution)
    prediction: Any = None
    used_device = "cpu"
    duration_ms = 0
    last_exc: Exception | None = None

    for attempt_device, attempt_res in attempts:
        try:
            half = attempt_device == "cuda" and _fp16_supported(torch)
            model = _load_model(spec, snapshot_dir, attempt_device, half)
            image_tensor = _preprocess_image(crop_image, attempt_res, transforms)
            image_tensor = image_tensor.unsqueeze(0).to(attempt_device)
            if half:
                image_tensor = image_tensor.half()

            log_event(
                "alpha_model.predict.start",
                component="birefnet",
                **{
                    "model.id": spec.id,
                    "device.type": attempt_device,
                    "input.resolution": attempt_res,
                    "model.precision": "fp16" if half else "fp32",
                    "image.width": width,
                    "image.height": height,
                },
            )
            started = time.monotonic()
            with torch.inference_mode():
                prediction = model(image_tensor)[-1].sigmoid().detach().cpu()
                if half and _has_nan(torch, prediction):
                    # Some GPUs (notably GTX 16xx) overflow in FP16 and return an
                    # all-NaN mask, which ends up as an empty selection. Retry in
                    # FP32 and stop using FP16 for the rest of this worker's life.
                    model = image_tensor = prediction = None
                    _mark_fp16_unsupported(spec, attempt_device)
                    model = _load_model(spec, snapshot_dir, attempt_device, False)
                    image_tensor = _preprocess_image(crop_image, attempt_res, transforms)
                    image_tensor = image_tensor.unsqueeze(0).to(attempt_device)
                    prediction = model(image_tensor)[-1].sigmoid().detach().cpu()
            duration_ms = round((time.monotonic() - started) * 1000)
            used_device = attempt_device
            break
        except RuntimeError as exc:
            last_exc = exc
            if "out of memory" in str(exc).lower():
                release_runtime_memory()
                continue
            raise InferenceFailed("alpha extraction failed") from exc
        except Exception as exc:
            raise InferenceFailed("alpha extraction failed") from exc

    if prediction is None:
        if last_exc is not None and "out of memory" in str(last_exc).lower():
            raise InferenceOutOfMemory("alpha extraction ran out of GPU memory") from last_exc
        raise InferenceFailed("alpha extraction failed")

    pred = prediction[0].squeeze().float()
    pred_image = transforms.ToPILImage()(pred)
    resampling = getattr(image_module, "Resampling", image_module).BILINEAR
    pred_image = pred_image.resize((width, height), resampling)
    alpha_array = numpy_module.asarray(pred_image, dtype=numpy_module.uint8)
    alpha_bytes = alpha_array.reshape(width * height).tobytes()
    log_event(
        "alpha_model.predict.result",
        component="birefnet",
        **{
            "model.id": spec.id,
            "device.type": used_device,
            "duration_ms": duration_ms,
            "image.width": width,
            "image.height": height,
        },
    )
    return BiRefNetResult(
        crop_alpha=alpha_bytes,
        width=width,
        height=height,
        device=used_device,
        torch_version=str(torch.__version__),
        cuda_available=cuda_available,
        duration_ms=duration_ms,
    )


def runtime_result_payload(result: BiRefNetResult) -> dict[str, object]:
    return {
        "version": runtime_ready_version(),
        "cache_state": "ready",
        "device": result.device,
        "torch_version": result.torch_version,
        "cuda_available": result.cuda_available,
    }


def runtime_ready_version() -> str:
    runtime_manifest = importlib.import_module("runtime_manifest")
    return str(runtime_manifest.RUNTIME_VERSION)


_FP16_UNSUPPORTED_GPU_MARKERS = ("GTX 16",)
_fp16_disabled = False


def _fp16_supported(torch: Any) -> bool:
    if _fp16_disabled:
        return False
    try:
        name = str(torch.cuda.get_device_name(0))
    except Exception:
        return True
    return not any(marker in name for marker in _FP16_UNSUPPORTED_GPU_MARKERS)


def _has_nan(torch: Any, tensor: Any) -> bool:
    try:
        return bool(torch.isnan(tensor).any())
    except Exception:
        return False


def _mark_fp16_unsupported(spec: ModelSpec, device: str) -> None:
    global _fp16_disabled
    _fp16_disabled = True
    # Drop the FP16 weights before loading the FP32 copy so both never share VRAM.
    release_runtime_memory()
    log_event(
        "alpha_model.predict.fp16_nan",
        severity="warning",
        component="birefnet",
        **{"model.id": spec.id, "device.type": device, "model.precision": "fp32"},
    )


def _load_model(spec: ModelSpec, snapshot_dir: Path, device: str, half: bool) -> Any:
    key = (spec.id, str(snapshot_dir), device, half)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    torch = importlib.import_module("torch")
    transformers = importlib.import_module("transformers")
    torch.set_float32_matmul_precision("high")
    log_event(
        "alpha_model.load.start",
        component="birefnet",
        **{"model.id": spec.id, "device.type": device},
    )
    model = transformers.AutoModelForImageSegmentation.from_pretrained(
        str(snapshot_dir),
        trust_remote_code=spec.trust_remote_code,
    )
    model.to(device)
    model.eval()
    if half:
        model.half()
    _MODEL_CACHE[key] = model
    log_event(
        "alpha_model.load.result",
        component="birefnet",
        **{"model.id": spec.id, "device.type": device},
    )
    return model


def _preprocess_image(image: Any, resolution: int, transforms: Any) -> Any:
    transform = transforms.Compose(
        [
            transforms.Resize((resolution, resolution)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    return transform(image)
