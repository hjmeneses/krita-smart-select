#!/usr/bin/env python3
"""Fast Windows build & packaging helper for Krita Smart Select.

Configures Krita with CMake/Ninja to generate export headers and compile_commands.json,
compiles only the kritasmartselect C++ sources + MOC/RCC files with LLVM-MinGW Clang,
and links directly against an installed Krita 5.3.x binary directory + KDE CI Qt5/KF5 deps.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KRITA_SRC = Path(os.environ.get("KRITA_SRC", r"F:\krita-work\krita-src"))
BUILD_DIR = Path(os.environ.get("KRITA_BUILD", r"F:\krita-work\build-windows"))
KRITA_INSTALL = Path(os.environ.get("KRITA_INSTALL", r"F:\krita-work\krita\_install"))
LLVM_MINGW = Path(
    os.environ.get("LLVM_MINGW", r"F:\krita-work\llvm-mingw\llvm-mingw-20261020-ucrt-x86_64")
)
INSTALLED_KRITA_BIN = Path(
    os.environ.get("KRITA_BIN", r"C:\Program Files\Krita (x64)\bin")
)
VERSION = os.environ.get("SMART_SELECT_VERSION", "0.1.1")


def setup_env() -> dict[str, str]:
    env = os.environ.copy()
    llvm_bin = str(LLVM_MINGW / "bin")
    llvm_sub_bin = str(LLVM_MINGW / "x86_64-w64-mingw32" / "bin")
    install_bin = str(KRITA_INSTALL / "bin")
    env["PATH"] = os.pathsep.join([llvm_bin, llvm_sub_bin, install_bin, env.get("PATH", "")])
    env["CC"] = str(LLVM_MINGW / "bin" / "clang.exe")
    env["CXX"] = str(LLVM_MINGW / "bin" / "clang++.exe")
    return env


def sync_plugin_source() -> Path:
    ktm_h = KRITA_SRC / "libs" / "flake" / "KoToolManager.h"
    if ktm_h.exists():
        ktm_text = ktm_h.read_text(encoding="utf-8")
        if "static KoToolManager* instance();" not in ktm_text:
            ktm_text = ktm_text.replace(
                "KoToolAction(KoToolFactoryBase *toolFactory, KoToolManager *toolManager);",
                "explicit KoToolAction(KoToolFactoryBase *toolFactory);\n"
                "    KoToolAction(KoToolFactoryBase *toolFactory, KoToolManager *toolManager);",
            )
            ktm_text = ktm_text.replace(
                "KoToolManager::Private *priv();",
                "static KoToolManager* instance();\n    KoToolManager::Private *priv();",
            )
            ktm_h.write_text(ktm_text, encoding="utf-8")

    for rel_hdr in (
        Path("libs/flake/KoToolFactoryBase.h"),
        Path("libs/ui/tool/KisToolPaintFactoryBase.h"),
        Path("libs/ui/tool/KisSelectionToolFactoryBase.h"),
    ):
        hdr = KRITA_SRC / rel_hdr
        if hdr.exists():
            txt = hdr.read_text(encoding="utf-8")
            if "createActionsImpl(KoToolManager *toolManager)" in txt:
                txt = txt.replace(
                    "createActionsImpl(KoToolManager *toolManager)", "createActionsImpl()"
                )
                hdr.write_text(txt, encoding="utf-8")

    tools_cmake = KRITA_SRC / "plugins" / "tools" / "CMakeLists.txt"
    if tools_cmake.exists():
        cmake_txt = tools_cmake.read_text(encoding="utf-8")
        if "krita-smart-select" not in cmake_txt:
            cmake_txt = cmake_txt.replace(
                "add_subdirectory( tool_knife )",
                "add_subdirectory( tool_knife )\nadd_subdirectory( krita-smart-select )",
            )
            tools_cmake.write_text(cmake_txt, encoding="utf-8")

    dest = KRITA_SRC / "plugins" / "tools" / "krita-smart-select"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REPO_ROOT / "plugin", dest)
    print(f"[1/6] Copied plugin source to {dest}", flush=True)
    return dest


def run_cmake_configure(env: dict[str, str]) -> None:
    compile_db = BUILD_DIR / "compile_commands.json"
    if compile_db.exists():
        text = compile_db.read_text(encoding="utf-8", errors="ignore")
        if "krita-smart-select" in text:
            print("[2/6] CMake already configured with krita-smart-select!", flush=True)
            return

    print("[2/6] Running CMake configure...", flush=True)
    cmd = [
        "cmake.exe",
        "-S",
        str(KRITA_SRC),
        "-B",
        str(BUILD_DIR),
        "-G",
        "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_WITH_QT6=OFF",
        "-DBUILD_TESTING=OFF",
        "-DBUILD_KRITA_QT_DESIGNER_PLUGINS=OFF",
        f"-DCMAKE_PREFIX_PATH={KRITA_INSTALL.as_posix()}",
        f"-DCMAKE_INSTALL_PREFIX={KRITA_INSTALL.as_posix()}",
        f"-DCMAKE_C_COMPILER={(LLVM_MINGW / 'bin' / 'clang.exe').as_posix()}",
        f"-DCMAKE_CXX_COMPILER={(LLVM_MINGW / 'bin' / 'clang++.exe').as_posix()}",
    ]
    subprocess.run(cmd, env=env, check=True)


def run_moc_and_rcc(env: dict[str, str], plugin_src: Path, plugin_build: Path) -> list[Path]:
    print("[3/6] Generating Qt MOC and RCC files...", flush=True)
    autogen_include = plugin_build / "kritasmartselect_autogen" / "include"
    autogen_mocs_dir = plugin_build / "kritasmartselect_autogen" / "EWIEGA46WW"
    autogen_include.mkdir(parents=True, exist_ok=True)
    autogen_mocs_dir.mkdir(parents=True, exist_ok=True)

    moc_exe = KRITA_INSTALL / "bin" / "moc.exe"
    rcc_exe = KRITA_INSTALL / "bin" / "rcc.exe"

    subprocess.run(
        [
            str(moc_exe),
            f"-I{plugin_src.as_posix()}",
            f"-I{(KRITA_INSTALL / 'include' / 'KF5' / 'KCoreAddons').as_posix()}",
            f"-I{(KRITA_INSTALL / 'include' / 'QtCore').as_posix()}",
            "-o",
            str(autogen_include / "SmartSelectPlugin.moc"),
            str(plugin_src / "SmartSelectPlugin.cpp"),
        ],
        env=env,
        check=True,
    )

    extra_cpp: list[Path] = []
    hdr_list = [
        plugin_src / "SmartSelectPlugin.h",
        plugin_src / "SmartSelectTool.h",
        plugin_src / "WorkerClient.h",
        KRITA_SRC / "plugins" / "tools" / "selectiontools" / "kis_selection_modifier_mapper.h",
    ]
    for hdr_path in hdr_list:
        stem = hdr_path.stem
        moc_out = autogen_mocs_dir / f"moc_{stem}.cpp"
        subprocess.run(
            [
                str(moc_exe),
                f"-I{plugin_src.as_posix()}",
                f"-I{(KRITA_SRC / 'plugins' / 'tools' / 'selectiontools').as_posix()}",
                f"-I{(KRITA_SRC / 'libs' / 'ui' / 'tool').as_posix()}",
                f"-I{(KRITA_SRC / 'libs' / 'ui').as_posix()}",
                f"-I{(KRITA_SRC / 'libs' / 'flake' / 'tools').as_posix()}",
                f"-I{(KRITA_SRC / 'libs' / 'flake').as_posix()}",
                f"-I{(KRITA_SRC / 'libs' / 'basicflakes' / 'tools').as_posix()}",
                f"-I{(KRITA_INSTALL / 'include' / 'QtCore').as_posix()}",
                f"-I{(KRITA_INSTALL / 'include' / 'QtGui').as_posix()}",
                f"-I{(KRITA_INSTALL / 'include' / 'QtWidgets').as_posix()}",
                "-o",
                str(moc_out),
                str(hdr_path),
            ],
            env=env,
            check=True,
        )

    mocs_compilation = plugin_build / "kritasmartselect_autogen" / "mocs_compilation.cpp"
    mocs_compilation.write_text(
        '#include "EWIEGA46WW/moc_SmartSelectPlugin.cpp"\n'
        '#include "EWIEGA46WW/moc_SmartSelectTool.cpp"\n'
        '#include "EWIEGA46WW/moc_WorkerClient.cpp"\n'
        '#include "EWIEGA46WW/moc_kis_selection_modifier_mapper.cpp"\n',
        encoding="utf-8",
    )
    extra_cpp.append(mocs_compilation)

    qrc_cpp = plugin_build / "qrc_smartselect.cpp"
    subprocess.run(
        [
            str(rcc_exe),
            "--name",
            "smartselect",
            "--output",
            str(qrc_cpp),
            str(plugin_src / "icons" / "smartselect.qrc"),
        ],
        env=env,
        check=True,
    )
    extra_cpp.append(qrc_cpp)
    return extra_cpp


def ensure_missing_ui_header(header_name: str, env: dict[str, str]) -> bool:
    if not header_name.startswith("ui_") or not header_name.endswith(".h"):
        return False
    ui_base = header_name[3:-2] + ".ui"
    matches = list(KRITA_SRC.rglob(ui_base))
    if not matches:
        return False
    uic_exe = KRITA_INSTALL / "bin" / "uic.exe"
    target_dirs = [
        BUILD_DIR / "libs" / "ui",
        BUILD_DIR / "libs" / "widgets",
        BUILD_DIR / "libs" / "flake",
        BUILD_DIR / "plugins" / "tools" / "krita-smart-select",
    ]
    ui_file = matches[0]
    for out_dir in target_dirs:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_header = out_dir / header_name
        if not out_header.exists():
            print(f"  -> Generating {out_header} from {ui_file}", flush=True)
            subprocess.run([str(uic_exe), "-o", str(out_header), str(ui_file)], env=env, check=True)
            return True
    return False


def compile_objects(env: dict[str, str]) -> list[Path]:
    print("[4/6] Compiling kritasmartselect C++ sources...", flush=True)
    compile_db = json.loads((BUILD_DIR / "compile_commands.json").read_text(encoding="utf-8"))
    entries = [
        e for e in compile_db if "plugins/tools/krita-smart-select" in e["command"].replace("\\", "/")
    ]
    if not entries:
        raise RuntimeError("No compile_commands.json entries found for krita-smart-select!")

    obj_files: list[Path] = []
    for entry in entries:
        cmd_str: str = entry["command"]
        work_dir = Path(entry["directory"])
        m = re.search(r"-o\s+(\S+)\s+-c\s+", cmd_str)
        if not m:
            raise RuntimeError(f"Could not parse -o from command: {cmd_str}")
        obj_rel = m.group(1).strip('"')
        obj_path = work_dir / obj_rel
        obj_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            res = subprocess.run(
                cmd_str,
                cwd=str(work_dir),
                env=env,
                shell=True,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                print(f"  [OK] {Path(entry['file']).name}", flush=True)
                obj_files.append(obj_path)
                break
            err = res.stderr + "\n" + res.stdout
            ui_match = re.search(r"fatal error:\s+'(ui_[^']+\.h)'\s+file not found", err)
            if ui_match and ensure_missing_ui_header(ui_match.group(1), env):
                continue
            raise RuntimeError(f"Compile failed for {entry['file']}:\n{err}")

    return obj_files


def link_dll(env: dict[str, str], obj_files: list[Path]) -> Path:
    print("[5/6] Linking kritasmartselect.dll...", flush=True)
    out_dir = BUILD_DIR / "bin"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dll = out_dir / "kritasmartselect.dll"

    clangxx = LLVM_MINGW / "bin" / "clang++.exe"
    cmd = [
        str(clangxx),
        "-shared",
        "-o",
        str(out_dll),
        *[str(o) for o in obj_files],
        f"-L{INSTALLED_KRITA_BIN.as_posix()}",
        f"-L{(KRITA_INSTALL / 'lib').as_posix()}",
        "-lkritaui",
        "-lkritabasicflakes",
        "-lkritaimage",
        "-lkritaflake",
        "-lkritawidgets",
        "-lkritawidgetutils",
        "-lkritaresources",
        "-lkritaresourcewidgets",
        "-lkritapigment",
        "-lkritacommand",
        "-lkritaglobal",
        "-lkritaversion",
        "-lKF5CoreAddons",
        "-lKF5I18n",
        "-lKF5ConfigCore",
        "-lKF5ConfigGui",
        "-lKF5WidgetsAddons",
        "-lQt5Widgets",
        "-lQt5Gui",
        "-lQt5Core",
        "-lQt5Xml",
        "-lQt5Network",
    ]
    subprocess.run(cmd, env=env, check=True)
    print(f"  [OK] Built {out_dll} ({out_dll.stat().st_size} bytes)", flush=True)
    return out_dll


def package_zip(env: dict[str, str]) -> None:
    print("[6/6] Packaging release ZIP...", flush=True)
    env["LLVM_MINGW"] = str(LLVM_MINGW)
    subprocess.run(
        [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "package-windows.ps1"),
            "-Version",
            VERSION,
            "-BuildDir",
            str(BUILD_DIR),
        ],
        env=env,
        check=True,
    )


def main() -> None:
    env = setup_env()
    plugin_src = sync_plugin_source()
    run_cmake_configure(env)
    plugin_build = BUILD_DIR / "plugins" / "tools" / "krita-smart-select"
    run_moc_and_rcc(env, plugin_src, plugin_build)
    obj_files = compile_objects(env)
    link_dll(env, obj_files)
    package_zip(env)
    print("ALL DONE!", flush=True)


if __name__ == "__main__":
    main()
