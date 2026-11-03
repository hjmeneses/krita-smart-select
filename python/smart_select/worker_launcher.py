#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

RUNTIME_WORKER_PYTHON = "3.12"


def format_log_event(event_name: str, **fields: object) -> str:
    parts = [
        "[SmartSelectWorker]",
        f"event.name={_format_value(event_name)}",
        "event.domain=smart_select",
        "severity=info",
        "component=worker_launcher",
    ]
    parts.extend(f"{key}={_format_value(value)}" for key, value in fields.items())
    return " ".join(parts)


def _format_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if text and all(ch.isalnum() or ch in "_./:@+-" for ch in text):
        return text
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _exec_or_run(cmd: list[str], env: dict[str, str]) -> NoReturn:
    if sys.platform.startswith("win"):
        # Windows has no exec(): the launcher stays as the parent. Tie the worker
        # (and anything it spawns, e.g. pip) to a kill-on-close job so that when
        # Krita kills the launcher the worker does not linger holding VRAM.
        job = _create_kill_on_close_job()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # Pass the std streams explicitly: without them Popen does not hand the
        # QProcess pipes to the child (it gets a fresh hidden console instead), so
        # the worker would block on an empty stdin and never answer Krita.
        process = subprocess.Popen(
            cmd,
            env=env,
            creationflags=creationflags,
            stdin=_std_stream(sys.stdin),
            stdout=_std_stream(sys.stdout),
            stderr=_std_stream(sys.stderr),
        )
        if job is not None:
            _assign_to_job(job, process)
        raise SystemExit(process.wait())
    os.execvpe(cmd[0], cmd, env)
    raise SystemExit(127)


def _std_stream(stream: object) -> int | None:
    try:
        return stream.fileno()  # type: ignore[attr-defined, no-any-return]
    except (AttributeError, OSError, ValueError):
        return None


def _create_kill_on_close_job() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class _IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class _BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimit),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        job_object_extended_limit_information = 9
        if not kernel32.SetInformationJobObject(
            job, job_object_extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)
        ):
            return None
        return int(job)
    except Exception:
        return None


def _assign_to_job(job: int, process: subprocess.Popen[bytes]) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject(job, int(process._handle))  # type: ignore[attr-defined]
    except Exception:
        pass


def _find_uv(env: dict[str, str]) -> str | None:
    found = shutil.which("uv", path=env.get("PATH"))
    if found is not None:
        return found
    exe_name = "uv.exe" if sys.platform.startswith("win") else "uv"
    home = Path.home()
    for candidate in (home / ".local" / "bin" / exe_name, home / ".cargo" / "bin" / exe_name):
        if candidate.exists():
            return str(candidate)
    return None


def _python_version_of(python: str, env: dict[str, str]) -> str | None:
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    )
    try:
        res = subprocess.run(
            [python, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        )
    except Exception:
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def _find_python_via_py_launcher(env: dict[str, str]) -> str | None:
    if not sys.platform.startswith("win"):
        return None
    py = shutil.which("py", path=env.get("PATH"))
    if py is None:
        windir = Path(env.get("SystemRoot", r"C:\Windows"))
        candidate = windir / "py.exe"
        if not candidate.exists():
            return None
        py = str(candidate)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        res = subprocess.run(
            [py, f"-{RUNTIME_WORKER_PYTHON}", "-c", "import sys; print(sys.executable)"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        )
    except Exception:
        return None
    if res.returncode != 0 or not res.stdout.strip():
        return None
    candidate = res.stdout.strip().splitlines()[-1].strip()
    return candidate if Path(candidate).exists() else None


def _is_store_python(path: str) -> bool:
    # Microsoft Store Python virtualizes writes under %APPDATA%, so the managed
    # venv would land in a hidden per-package location. Prefer a regular install.
    return "\\windowsapps\\" in path.lower()


def _find_python_on_path(env: dict[str, str]) -> str | None:
    for name in (f"python{RUNTIME_WORKER_PYTHON}", "python3", "python"):
        found = shutil.which(name, path=env.get("PATH"))
        if found is None or _is_store_python(found):
            continue
        if _python_version_of(found, env) == RUNTIME_WORKER_PYTHON:
            return found
    return None


def _find_runtime_python(env: dict[str, str]) -> tuple[str, str] | None:
    """Locate a Python matching RUNTIME_WORKER_PYTHON.

    The worker imports torch from the managed venv into its own interpreter, so
    it must run on exactly the runtime Python version.
    """
    if sys.platform.startswith("win"):
        found = _find_python_via_py_launcher(env)
        if found is not None:
            return found, "py-launcher"
    uv = _find_uv(env)
    if uv is not None:
        found = _find_python_via_uv(uv, env)
        if found is not None and not _is_store_python(found):
            return found, "uv-python-find"
    found = _find_python_on_path(env)
    if found is not None:
        return found, "path"
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    if current == RUNTIME_WORKER_PYTHON:
        return sys.executable, "current"
    return None


def _find_python_via_uv(uv: str, env: dict[str, str]) -> str | None:
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    )
    try:
        res = subprocess.run(
            [uv, "python", "find", "--no-project", "--system", RUNTIME_WORKER_PYTHON],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        )
        if res.returncode == 0 and res.stdout.strip():
            candidate = res.stdout.strip().splitlines()[-1].strip()
            if Path(candidate).exists():
                return candidate
    except Exception:
        pass
    return None


def main() -> NoReturn:
    if len(sys.argv) < 2:
        print(
            format_log_event("worker.launcher.failed", **{"error.reason": "missing_worker_script"}),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2)

    env = os.environ.copy()
    _configure_cuda_environment(env)

    found = _find_runtime_python(env)
    if found is not None:
        python_bin, mode = found
        print(
            format_log_event(
                "worker.launcher.exec",
                **{
                    "launcher.mode": mode,
                    "runtime.python.version": RUNTIME_WORKER_PYTHON,
                    "python.executable": python_bin,
                },
            ),
            file=sys.stderr,
            flush=True,
        )
        _exec_or_run([python_bin, *sys.argv[1:]], env)

    # No matching interpreter: still start the worker so it can report a
    # structured RuntimeBootstrapError instead of the process dying silently.
    print(
        format_log_event(
            "worker.launcher.python_not_found",
            **{
                "runtime.python.version": RUNTIME_WORKER_PYTHON,
                "python.executable": sys.executable,
            },
        ),
        file=sys.stderr,
        flush=True,
    )
    _exec_or_run([sys.executable, *sys.argv[1:]], env)


def _configure_cuda_environment(env: dict[str, str]) -> None:
    cuda_home = _detect_cuda_home(env)
    if cuda_home is None:
        return

    env.setdefault("SMART_SELECT_CUDA_HOME", str(cuda_home))
    env["CUDA_HOME"] = str(cuda_home)
    env["CUDA_PATH"] = str(cuda_home)
    env["PATH"] = _prepend_env_path(str(cuda_home / "bin"), env.get("PATH", ""))

    library_dirs = [
        str(candidate)
        for candidate in (cuda_home / "lib64", cuda_home / "lib")
        if candidate.exists()
    ]
    if library_dirs:
        env["LD_LIBRARY_PATH"] = _prepend_env_path(
            os.pathsep.join(library_dirs),
            env.get("LD_LIBRARY_PATH", ""),
        )


def _detect_cuda_home(env: dict[str, str]) -> Path | None:
    for key in ("SMART_SELECT_CUDA_HOME", "CUDA_HOME", "CUDA_PATH"):
        value = env.get(key)
        if value and _is_cuda_home(Path(value)):
            return Path(value)

    if sys.platform.startswith("win"):
        program_files = env.get("ProgramFiles", r"C:\Program Files")
        for candidate in (
            Path(program_files) / "NVIDIA GPU Computing Toolkit" / "CUDA" / "v12.4",
            Path(program_files) / "NVIDIA GPU Computing Toolkit" / "CUDA" / "v12.6",
            Path(program_files) / "NVIDIA GPU Computing Toolkit" / "CUDA" / "v13.0",
            Path(program_files) / "NVIDIA GPU Computing Toolkit" / "CUDA" / "v13.2",
            Path(program_files) / "NVIDIA GPU Computing Toolkit" / "CUDA" / "v13.3",
        ):
            if _is_cuda_home(candidate):
                return candidate
    else:
        for candidate in (
            Path("/usr/local/cuda-12.4"),
            Path("/usr/local/cuda"),
            Path.home() / ".local/share/krita/smart_select/cuda-12.4",
            Path.home() / "miniconda3",
        ):
            if _is_cuda_home(candidate):
                return candidate

    nvcc = shutil.which("nvcc", path=env.get("PATH"))
    if nvcc is None:
        return None
    candidate = Path(nvcc).resolve().parents[1]
    return candidate if _is_cuda_home(candidate) else None


def _is_cuda_home(path: Path) -> bool:
    if sys.platform.startswith("win"):
        return (path / "bin" / "nvcc.exe").exists() and (
            (path / "lib" / "x64").exists() or (path / "lib").exists()
        )
    return (path / "bin" / "nvcc").exists() and (
        (path / "lib64").exists() or (path / "lib").exists()
    )


def _prepend_env_path(prefix: str, current: str) -> str:
    return f"{prefix}{os.pathsep}{current}" if current else prefix


if __name__ == "__main__":
    main()
