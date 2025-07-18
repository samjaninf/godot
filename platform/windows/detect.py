import os
import re
import subprocess
import sys
from typing import TYPE_CHECKING

import methods
from methods import print_error, print_warning
from platform_methods import detect_arch, validate_arch

if TYPE_CHECKING:
    from SCons.Script.SConscript import SConsEnvironment

# To match other platforms
STACK_SIZE = 8388608
STACK_SIZE_SANITIZERS = 30 * 1024 * 1024


def get_name():
    return "Windows"


def try_cmd(test, prefix, arch, check_clang=False):
    archs = ["x86_64", "x86_32", "arm64", "arm32"]
    if arch:
        archs = [arch]

    for a in archs:
        try:
            out = subprocess.Popen(
                get_mingw_bin_prefix(prefix, a) + test,
                shell=True,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            outs, errs = out.communicate()
            if out.returncode == 0:
                if check_clang and not outs.startswith(b"clang"):
                    return False
                return True
        except Exception:
            pass

    return False


def can_build():
    if os.name == "nt":
        # Building natively on Windows
        return True

    if os.name == "posix":
        # Cross-compiling with MinGW-w64 (old MinGW32 is not supported)
        prefix = os.getenv("MINGW_PREFIX", "")

        if try_cmd("gcc --version", prefix, "") or try_cmd("clang --version", prefix, ""):
            return True

    return False


def get_mingw_bin_prefix(prefix, arch):
    bin_prefix = (os.path.normpath(os.path.join(prefix, "bin")) + os.sep) if prefix else ""
    ARCH_PREFIXES = {
        "x86_64": "x86_64-w64-mingw32-",
        "x86_32": "i686-w64-mingw32-",
        "arm32": "armv7-w64-mingw32-",
        "arm64": "aarch64-w64-mingw32-",
    }
    arch_prefix = ARCH_PREFIXES[arch] if arch else ""
    return bin_prefix + arch_prefix


def get_detected(env: "SConsEnvironment", tool: str) -> str:
    checks = [
        get_mingw_bin_prefix(env["mingw_prefix"], env["arch"]) + tool,
        get_mingw_bin_prefix(env["mingw_prefix"], "") + tool,
    ]
    return str(env.Detect(checks))


def detect_build_env_arch():
    msvc_target_aliases = {
        "amd64": "x86_64",
        "i386": "x86_32",
        "i486": "x86_32",
        "i586": "x86_32",
        "i686": "x86_32",
        "x86": "x86_32",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "arm": "arm32",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    if os.getenv("VCINSTALLDIR") or os.getenv("VCTOOLSINSTALLDIR"):
        if os.getenv("Platform"):
            msvc_arch = os.getenv("Platform").lower()
            if msvc_arch in msvc_target_aliases.keys():
                return msvc_target_aliases[msvc_arch]

        if os.getenv("VSCMD_ARG_TGT_ARCH"):
            msvc_arch = os.getenv("VSCMD_ARG_TGT_ARCH").lower()
            if msvc_arch in msvc_target_aliases.keys():
                return msvc_target_aliases[msvc_arch]

        # Pre VS 2017 checks.
        if os.getenv("VCINSTALLDIR"):
            PATH = os.getenv("PATH").upper()
            VCINSTALLDIR = os.getenv("VCINSTALLDIR").upper()
            path_arch = {
                "BIN\\x86_ARM;": "arm32",
                "BIN\\amd64_ARM;": "arm32",
                "BIN\\x86_ARM64;": "arm64",
                "BIN\\amd64_ARM64;": "arm64",
                "BIN\\x86_amd64;": "a86_64",
                "BIN\\amd64;": "x86_64",
                "BIN\\amd64_x86;": "x86_32",
                "BIN;": "x86_32",
            }
            for path, arch in path_arch.items():
                final_path = VCINSTALLDIR + path
                if final_path in PATH:
                    return arch

        # VS 2017 and newer.
        if os.getenv("VCTOOLSINSTALLDIR"):
            host_path_index = os.getenv("PATH").upper().find(os.getenv("VCTOOLSINSTALLDIR").upper() + "BIN\\HOST")
            if host_path_index > -1:
                first_path_arch = os.getenv("PATH")[host_path_index:].split(";")[0].rsplit("\\", 1)[-1].lower()
                if first_path_arch in msvc_target_aliases.keys():
                    return msvc_target_aliases[first_path_arch]

    msys_target_aliases = {
        "mingw32": "x86_32",
        "mingw64": "x86_64",
        "ucrt64": "x86_64",
        "clang64": "x86_64",
        "clang32": "x86_32",
        "clangarm64": "arm64",
    }
    if os.getenv("MSYSTEM"):
        msys_arch = os.getenv("MSYSTEM").lower()
        if msys_arch in msys_target_aliases.keys():
            return msys_target_aliases[msys_arch]

    return ""


def get_tools(env: "SConsEnvironment"):
    from SCons.Tool.MSCommon import msvc_exists

    if os.name != "nt" or env.get("use_mingw") or not msvc_exists():
        return ["mingw"]
    else:
        msvc_arch_aliases = {"x86_32": "x86", "arm32": "arm"}
        env["TARGET_ARCH"] = msvc_arch_aliases.get(env["arch"], env["arch"])
        env["MSVC_VERSION"] = env["MSVS_VERSION"] = env.get("msvc_version")
        return ["msvc", "mslink", "mslib"]


def get_opts():
    from SCons.Variables import BoolVariable, EnumVariable

    mingw = os.getenv("MINGW_PREFIX", "")

    # Direct3D 12 SDK dependencies folder.
    d3d12_deps_folder = os.getenv("LOCALAPPDATA")
    if d3d12_deps_folder:
        d3d12_deps_folder = os.path.join(d3d12_deps_folder, "Godot", "build_deps")
    else:
        # Cross-compiling, the deps install script puts things in `bin`.
        # Getting an absolute path to it is a bit hacky in Python.
        try:
            import inspect

            caller_frame = inspect.stack()[1]
            caller_script_dir = os.path.dirname(os.path.abspath(caller_frame[1]))
            d3d12_deps_folder = os.path.join(caller_script_dir, "bin", "build_deps")
        except Exception:  # Give up.
            d3d12_deps_folder = ""

    return [
        ("mingw_prefix", "MinGW prefix", mingw),
        EnumVariable("windows_subsystem", "Windows subsystem", "gui", ["gui", "console"], ignorecase=2),
        ("msvc_version", "MSVC version to use. Handled automatically by SCons if omitted.", ""),
        BoolVariable("use_mingw", "Use the Mingw compiler, even if MSVC is installed.", False),
        BoolVariable("use_llvm", "Use the LLVM compiler", False),
        BoolVariable("use_static_cpp", "Link MinGW/MSVC C++ runtime libraries statically", True),
        BoolVariable("use_asan", "Use address sanitizer (ASAN)", False),
        BoolVariable("use_ubsan", "Use LLVM compiler undefined behavior sanitizer (UBSAN)", False),
        BoolVariable("debug_crt", "Compile with MSVC's debug CRT (/MDd)", False),
        BoolVariable("incremental_link", "Use MSVC incremental linking. May increase or decrease build times.", False),
        BoolVariable("silence_msvc", "Silence MSVC's cl/link stdout bloat, redirecting any errors to stderr.", True),
        ("angle_libs", "Path to the ANGLE static libraries", ""),
        # Direct3D 12 support.
        (
            "mesa_libs",
            "Path to the MESA/NIR static libraries (required for D3D12)",
            os.path.join(d3d12_deps_folder, "mesa"),
        ),
        (
            "agility_sdk_path",
            "Path to the Agility SDK distribution (optional for D3D12)",
            os.path.join(d3d12_deps_folder, "agility_sdk"),
        ),
        BoolVariable(
            "agility_sdk_multiarch",
            "Whether the Agility SDK DLLs will be stored in arch-specific subdirectories",
            False,
        ),
        BoolVariable("use_pix", "Use PIX (Performance tuning and debugging for DirectX 12) runtime", False),
        (
            "pix_path",
            "Path to the PIX runtime distribution (optional for D3D12)",
            os.path.join(d3d12_deps_folder, "pix"),
        ),
    ]


def get_doc_classes():
    return [
        "EditorExportPlatformWindows",
    ]


def get_doc_path():
    return "doc_classes"


def get_flags():
    arch = detect_build_env_arch() or detect_arch()

    return {
        "arch": arch,
        "supported": ["d3d12", "dcomp", "mono", "xaudio2"],
    }


def build_def_file(target, source, env: "SConsEnvironment"):
    arch_aliases = {
        "x86_32": "i386",
        "x86_64": "i386:x86-64",
        "arm32": "arm",
        "arm64": "arm64",
    }

    cmdbase = "dlltool -m " + arch_aliases[env["arch"]]
    if env["arch"] == "x86_32":
        cmdbase += " -k"
    else:
        cmdbase += " --no-leading-underscore"

    mingw_bin_prefix = get_mingw_bin_prefix(env["mingw_prefix"], env["arch"])

    for x in range(len(source)):
        ok = True
        # Try prefixed executable (MinGW on Linux).
        cmd = mingw_bin_prefix + cmdbase + " -d " + str(source[x]) + " -l " + str(target[x])
        try:
            out = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE).communicate()
            if len(out[1]):
                ok = False
        except Exception:
            ok = False

        # Try generic executable (MSYS2).
        if not ok:
            cmd = cmdbase + " -d " + str(source[x]) + " -l " + str(target[x])
            try:
                out = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE).communicate()
                if len(out[1]):
                    return -1
            except Exception:
                return -1

    return 0


def configure_msvc(env: "SConsEnvironment"):
    """Configure env to work with MSVC"""

    ## Build type

    # TODO: Re-evaluate the need for this / streamline with common config.
    if env["target"] == "template_release":
        env.Append(LINKFLAGS=["/ENTRY:mainCRTStartup"])

    if env["windows_subsystem"] == "gui":
        env.Append(LINKFLAGS=["/SUBSYSTEM:WINDOWS"])
    else:
        env.Append(LINKFLAGS=["/SUBSYSTEM:CONSOLE"])
        env.AppendUnique(CPPDEFINES=["WINDOWS_SUBSYSTEM_CONSOLE"])

    ## Compile/link flags

    if env["use_llvm"]:
        env["CC"] = "clang-cl"
        env["CXX"] = "clang-cl"
        env["LINK"] = "lld-link"
        env["AR"] = "llvm-lib"

        env.AppendUnique(CPPDEFINES=["R128_STDC_ONLY"])
        env.extra_suffix = ".llvm" + env.extra_suffix

        # Ensure intellisense tools like `compile_commands.json` play nice with MSVC syntax.
        env["CPPDEFPREFIX"] = "-D"
        env["INCPREFIX"] = "-I"
        env.AppendUnique(CPPDEFINES=[("alloca", "_alloca")])

    if env["silence_msvc"] and not env.GetOption("clean"):
        from tempfile import mkstemp

        # Ensure we have a location to write captured output to, in case of false positives.
        capture_path = methods.base_folder / "platform" / "windows" / "msvc_capture.log"
        with open(capture_path, "wt", encoding="utf-8"):
            pass

        old_spawn = env["SPAWN"]
        re_redirect_stream = re.compile(r"^[12]?>")
        re_cl_capture = re.compile(r"^.+\.(c|cc|cpp|cxx|c[+]{2})$", re.IGNORECASE)
        re_link_capture = re.compile(r'\s{3}\S.+\s(?:"[^"]+.lib"|\S+.lib)\s.+\s(?:"[^"]+.exp"|\S+.exp)')

        def spawn_capture(sh, escape, cmd, args, env):
            # We only care about cl/link, process everything else as normal.
            if args[0] not in ["cl", "link"]:
                return old_spawn(sh, escape, cmd, args, env)

            # Process as normal if the user is manually rerouting output.
            for arg in args:
                if re_redirect_stream.match(arg):
                    return old_spawn(sh, escape, cmd, args, env)

            tmp_stdout, tmp_stdout_name = mkstemp()
            os.close(tmp_stdout)
            args.append(f">{tmp_stdout_name}")
            ret = old_spawn(sh, escape, cmd, args, env)

            try:
                with open(tmp_stdout_name, "r", encoding=sys.stdout.encoding, errors="replace") as tmp_stdout:
                    lines = tmp_stdout.read().splitlines()
                os.remove(tmp_stdout_name)
            except OSError:
                pass

            # Early process no lines (OSError)
            if not lines:
                return ret

            is_cl = args[0] == "cl"
            content = ""
            caught = False
            for line in lines:
                # These conditions are far from all-encompassing, but are specialized
                # for what can be reasonably expected to show up in the repository.
                if not caught and (is_cl and re_cl_capture.match(line)) or (not is_cl and re_link_capture.match(line)):
                    caught = True
                    try:
                        with open(capture_path, "a", encoding=sys.stdout.encoding) as log:
                            log.write(line + "\n")
                    except OSError:
                        print_warning(f'Failed to log captured line: "{line}".')
                    continue
                content += line + "\n"
            # Content remaining assumed to be an error/warning.
            if content:
                sys.stderr.write(content)

            return ret

        env["SPAWN"] = spawn_capture

    if env["debug_crt"]:
        # Always use dynamic runtime, static debug CRT breaks thread_local.
        env.AppendUnique(CCFLAGS=["/MDd"])
    else:
        if env["use_static_cpp"]:
            env.AppendUnique(CCFLAGS=["/MT"])
        else:
            env.AppendUnique(CCFLAGS=["/MD"])

    # MSVC incremental linking is broken and may _increase_ link time (GH-77968).
    if not env["incremental_link"]:
        env.Append(LINKFLAGS=["/INCREMENTAL:NO"])

    if env["arch"] == "x86_32":
        env["x86_libtheora_opt_vc"] = True

    env.Append(CCFLAGS=["/fp:strict"])

    env.AppendUnique(CCFLAGS=["/Gd", "/GR", "/nologo"])
    env.AppendUnique(CCFLAGS=["/utf-8"])  # Force to use Unicode encoding.
    # Once it was thought that only debug builds would be too large,
    # but this has recently stopped being true. See the mingw function
    # for notes on why this shouldn't be enabled for gcc
    env.AppendUnique(CCFLAGS=["/bigobj"])

    env.AppendUnique(
        CPPDEFINES=[
            "WINDOWS_ENABLED",
            "WASAPI_ENABLED",
            "WINMIDI_ENABLED",
            "TYPED_METHOD_BIND",
            "WIN32",
            "WINVER=0x0A00",
            "_WIN32_WINNT=0x0A00",
        ]
    )
    env.AppendUnique(CPPDEFINES=["NOMINMAX"])  # disable bogus min/max WinDef.h macros
    if env["arch"] == "x86_64":
        env.AppendUnique(CPPDEFINES=["_WIN64"])

    # Sanitizers
    prebuilt_lib_extra_suffix = ""
    if env["use_asan"]:
        env.extra_suffix += ".san"
        prebuilt_lib_extra_suffix = ".san"
        env.AppendUnique(CPPDEFINES=["SANITIZERS_ENABLED"])
        env.Append(CCFLAGS=["/fsanitize=address"])
        env.Append(LINKFLAGS=["/INFERASANLIBS"])

    ## Libs

    LIBS = [
        "winmm",
        "dsound",
        "kernel32",
        "ole32",
        "oleaut32",
        "sapi",
        "user32",
        "gdi32",
        "IPHLPAPI",
        "Shlwapi",
        "Shcore",
        "wsock32",
        "Ws2_32",
        "shell32",
        "advapi32",
        "dinput8",
        "dxguid",
        "imm32",
        "bcrypt",
        "Crypt32",
        "Avrt",
        "dwmapi",
        "dwrite",
        "wbemuuid",
        "ntdll",
    ]

    if env.debug_features:
        LIBS += ["psapi", "dbghelp"]

    if env["accesskit"]:
        if env["accesskit_sdk_path"] != "":
            env.Prepend(CPPPATH=[env["accesskit_sdk_path"] + "/include"])
            if env["arch"] == "arm64":
                env.Append(LIBPATH=[env["accesskit_sdk_path"] + "/lib/windows/arm64/msvc/static"])
            elif env["arch"] == "x86_64":
                env.Append(LIBPATH=[env["accesskit_sdk_path"] + "/lib/windows/x86_64/msvc/static"])
            elif env["arch"] == "x86_32":
                env.Append(LIBPATH=[env["accesskit_sdk_path"] + "/lib/windows/x86/msvc/static"])
            LIBS += [
                "accesskit",
                "uiautomationcore",
                "runtimeobject",
                "propsys",
                "oleaut32",
                "user32",
                "userenv",
                "ntdll",
            ]
        else:
            env.Append(CPPDEFINES=["ACCESSKIT_DYNAMIC"])
        env.Append(CPPDEFINES=["ACCESSKIT_ENABLED"])

    if env["vulkan"]:
        env.AppendUnique(CPPDEFINES=["VULKAN_ENABLED", "RD_ENABLED"])
        if not env["use_volk"]:
            LIBS += ["vulkan"]

    if env["sdl"]:
        env.Append(CPPDEFINES=["SDL_ENABLED"])

    if env["d3d12"]:
        check_d3d12_installed(env, env["arch"] + "-msvc")

        env.AppendUnique(CPPDEFINES=["D3D12_ENABLED", "RD_ENABLED"])
        LIBS += ["dxgi", "dxguid"]
        LIBS += ["version"]  # Mesa dependency.

        # Needed for avoiding C1128.
        if env["target"] == "release_debug":
            env.Append(CXXFLAGS=["/bigobj"])

        # PIX
        if env["arch"] not in ["x86_64", "arm64"] or env["pix_path"] == "" or not os.path.exists(env["pix_path"]):
            env["use_pix"] = False

        if env["use_pix"]:
            arch_subdir = "arm64" if env["arch"] == "arm64" else "x64"

            env.Append(LIBPATH=[env["pix_path"] + "/bin/" + arch_subdir])
            LIBS += ["WinPixEventRuntime"]

        if os.path.exists(env["mesa_libs"] + "-" + env["arch"] + "-msvc"):
            env.Append(LIBPATH=[env["mesa_libs"] + "-" + env["arch"] + "-msvc/bin"])
        else:
            env.Append(LIBPATH=[env["mesa_libs"] + "/bin"])
        LIBS += ["libNIR.windows." + env["arch"] + prebuilt_lib_extra_suffix]

    if env["opengl3"]:
        env.AppendUnique(CPPDEFINES=["GLES3_ENABLED"])
        if env["angle_libs"] != "":
            env.AppendUnique(CPPDEFINES=["EGL_STATIC"])
            env.Append(LIBPATH=[env["angle_libs"]])
            LIBS += [
                "libANGLE.windows." + env["arch"] + prebuilt_lib_extra_suffix,
                "libEGL.windows." + env["arch"] + prebuilt_lib_extra_suffix,
                "libGLES.windows." + env["arch"] + prebuilt_lib_extra_suffix,
            ]
            LIBS += ["dxgi", "d3d9", "d3d11"]
        env.Prepend(CPPEXTPATH=["#thirdparty/angle/include"])

    if env["target"] in ["editor", "template_debug"]:
        LIBS += ["psapi", "dbghelp"]

    if env["use_llvm"]:
        LIBS += [f"clang_rt.builtins-{env['arch']}"]

    env.Append(LINKFLAGS=[p + env["LIBSUFFIX"] for p in LIBS])

    ## LTO

    if env["lto"] == "auto":  # No LTO by default for MSVC, doesn't help.
        env["lto"] = "none"

    if env["lto"] != "none":
        if env["lto"] == "thin":
            if not env["use_llvm"]:
                print("ThinLTO is only compatible with LLVM, use `use_llvm=yes` or `lto=full`.")
                sys.exit(255)

            env.AppendUnique(CCFLAGS=["-flto=thin"])
        elif env["use_llvm"]:
            env.AppendUnique(CCFLAGS=["-flto"])
        else:
            env.AppendUnique(CCFLAGS=["/GL"])
        if env["progress"]:
            env.AppendUnique(LINKFLAGS=["/LTCG:STATUS"])
        else:
            env.AppendUnique(LINKFLAGS=["/LTCG"])
        env.AppendUnique(ARFLAGS=["/LTCG"])

    env.Append(LINKFLAGS=["/NATVIS:platform\\windows\\godot.natvis"])

    if env["use_asan"]:
        env.AppendUnique(LINKFLAGS=["/STACK:" + str(STACK_SIZE_SANITIZERS)])
    else:
        env.AppendUnique(LINKFLAGS=["/STACK:" + str(STACK_SIZE)])


def get_ar_version(env):
    ret = {
        "major": -1,
        "minor": -1,
        "patch": -1,
        "is_llvm": False,
    }
    try:
        output = (
            subprocess.check_output([env.subst(env["AR"]), "--version"], shell=(os.name == "nt"))
            .strip()
            .decode("utf-8")
        )
    except (subprocess.CalledProcessError, OSError):
        print_warning("Couldn't check version of `ar`.")
        return ret

    match = re.search(r"GNU ar(?: \(GNU Binutils\)| version) (\d+)\.(\d+)(?:\.(\d+))?", output)
    if match:
        ret["major"] = int(match[1])
        ret["minor"] = int(match[2])
        if match[3]:
            ret["patch"] = int(match[3])
        else:
            ret["patch"] = 0
        return ret

    match = re.search(r"LLVM version (\d+)\.(\d+)\.(\d+)", output)
    if match:
        ret["major"] = int(match[1])
        ret["minor"] = int(match[2])
        ret["patch"] = int(match[3])
        ret["is_llvm"] = True
        return ret

    print_warning("Couldn't parse version of `ar`.")
    return ret


def get_is_ar_thin_supported(env):
    """Check whether `ar --thin` is supported. It is only supported since Binutils 2.38 or LLVM 14."""
    ar_version = get_ar_version(env)
    if ar_version["major"] == -1:
        return False

    if ar_version["is_llvm"]:
        return ar_version["major"] >= 14

    if ar_version["major"] == 2:
        return ar_version["minor"] >= 38

    print_warning("Unknown Binutils `ar` version.")
    return False


WINPATHSEP_RE = re.compile(r"\\([^\"'\\]|$)")


def tempfile_arg_esc_func(arg):
    from SCons.Subst import quote_spaces

    arg = quote_spaces(arg)
    # GCC requires double Windows slashes, let's use UNIX separator
    return WINPATHSEP_RE.sub(r"/\1", arg)


def configure_mingw(env: "SConsEnvironment"):
    if os.getenv("MSYSTEM") == "MSYS":
        print_error(
            "Running from base MSYS2 console/environment, use target specific environment instead (e.g., mingw32, mingw64, clang32, clang64)."
        )
        sys.exit(255)

    if (env_arch := detect_build_env_arch()) and env["arch"] != env_arch:
        print_error(
            f"Arch argument ({env['arch']}) is not matching MSYS2 console/environment that is being used to run SCons ({env_arch}).\n"
            "Run SCons again without arch argument (example: scons p=windows) and SCons will attempt to detect what MSYS2 compiler will be executed and inform you."
        )
        sys.exit(255)

    if not try_cmd("gcc --version", env["mingw_prefix"], env["arch"]) and not try_cmd(
        "clang --version", env["mingw_prefix"], env["arch"]
    ):
        print_error("No valid compilers found, use MINGW_PREFIX environment variable to set MinGW path.")
        sys.exit(255)

    # Workaround for MinGW. See:
    # https://www.scons.org/wiki/LongCmdLinesOnWin32
    env.use_windows_spawn_fix()

    # HACK: For some reason, Windows-native shells have their MinGW tools
    # frequently fail as a result of parsing path separators incorrectly.
    # For some other reason, this issue is circumvented entirely if the
    # `mingw_prefix` bin is prepended to PATH.
    if os.sep == "\\":
        env.PrependENVPath("PATH", os.path.join(env["mingw_prefix"], "bin"))

    # In case the command line to AR is too long, use a response file.
    env["ARCOM_ORIG"] = env["ARCOM"]
    env["ARCOM"] = "${TEMPFILE('$ARCOM_ORIG', '$ARCOMSTR')}"
    env["TEMPFILESUFFIX"] = ".rsp"
    if os.name == "nt":
        env["TEMPFILEARGESCFUNC"] = tempfile_arg_esc_func

    ## Build type

    if not env["use_llvm"] and not try_cmd("gcc --version", env["mingw_prefix"], env["arch"]):
        env["use_llvm"] = True

    if env["use_llvm"] and not try_cmd("clang --version", env["mingw_prefix"], env["arch"]):
        env["use_llvm"] = False

    if not env["use_llvm"] and try_cmd("gcc --version", env["mingw_prefix"], env["arch"], True):
        print("Detected GCC to be a wrapper for Clang.")
        env["use_llvm"] = True

    if env.dev_build:
        # Allow big objects. It's supposed not to have drawbacks but seems to break
        # GCC LTO, so enabling for debug builds only (which are not built with LTO
        # and are the only ones with too big objects).
        env.Append(CCFLAGS=["-Wa,-mbig-obj"])

    if env["windows_subsystem"] == "gui":
        env.Append(LINKFLAGS=["-Wl,--subsystem,windows"])
    else:
        env.Append(LINKFLAGS=["-Wl,--subsystem,console"])
        env.AppendUnique(CPPDEFINES=["WINDOWS_SUBSYSTEM_CONSOLE"])

    ## Compiler configuration

    if env["arch"] == "x86_32":
        if env["use_static_cpp"]:
            env.Append(LINKFLAGS=["-static"])
            env.Append(LINKFLAGS=["-static-libgcc"])
            env.Append(LINKFLAGS=["-static-libstdc++"])
    else:
        if env["use_static_cpp"]:
            env.Append(LINKFLAGS=["-static"])

    if env["arch"] == "x86_32":
        env["x86_libtheora_opt_gcc"] = True

    env.Append(CCFLAGS=["-ffp-contract=off"])

    if env["use_llvm"]:
        env["CC"] = get_detected(env, "clang")
        env["CXX"] = get_detected(env, "clang++")
        env["AR"] = get_detected(env, "ar")
        env["RANLIB"] = get_detected(env, "ranlib")
        env["AS"] = get_detected(env, "clang")
        env.Append(ASFLAGS=["-c"])
        env.extra_suffix = ".llvm" + env.extra_suffix
    else:
        env["CC"] = get_detected(env, "gcc")
        env["CXX"] = get_detected(env, "g++")
        env["AR"] = get_detected(env, "gcc-ar" if os.name != "nt" else "ar")
        env["RANLIB"] = get_detected(env, "gcc-ranlib")
        env["AS"] = get_detected(env, "gcc")
        env.Append(ASFLAGS=["-c"])

    env["RC"] = get_detected(env, "windres")
    ARCH_TARGETS = {
        "x86_32": "pe-i386",
        "x86_64": "pe-x86-64",
        "arm32": "armv7-w64-mingw32",
        "arm64": "aarch64-w64-mingw32",
    }
    env.AppendUnique(RCFLAGS=f"--target={ARCH_TARGETS[env['arch']]}")

    env["OBJCOPY"] = get_detected(env, "objcopy")
    env["STRIP"] = get_detected(env, "strip")

    ## LTO

    if env["lto"] == "auto":  # Enable LTO for production with MinGW.
        env["lto"] = "thin" if env["use_llvm"] else "full"

    if env["lto"] != "none":
        if env["lto"] == "thin":
            if not env["use_llvm"]:
                print("ThinLTO is only compatible with LLVM, use `use_llvm=yes` or `lto=full`.")
                sys.exit(255)
            env.Append(CCFLAGS=["-flto=thin"])
            env.Append(LINKFLAGS=["-flto=thin"])
        elif not env["use_llvm"] and env.GetOption("num_jobs") > 1:
            env.Append(CCFLAGS=["-flto"])
            env.Append(LINKFLAGS=["-flto=" + str(env.GetOption("num_jobs"))])
        else:
            env.Append(CCFLAGS=["-flto"])
            env.Append(LINKFLAGS=["-flto"])
        if not env["use_llvm"]:
            # For mingw-gcc LTO, disable linker plugin and enable whole program to work around GH-102867.
            env.Append(CCFLAGS=["-fno-use-linker-plugin", "-fwhole-program"])
            env.Append(LINKFLAGS=["-fno-use-linker-plugin", "-fwhole-program"])

    if env["use_asan"]:
        env.Append(LINKFLAGS=["-Wl,--stack," + str(STACK_SIZE_SANITIZERS)])
    else:
        env.Append(LINKFLAGS=["-Wl,--stack," + str(STACK_SIZE)])

    ## Compile flags

    if not env["use_llvm"]:
        env.Append(CCFLAGS=["-mwindows"])

    if env["use_asan"] or env["use_ubsan"]:
        if not env["use_llvm"]:
            print("GCC does not support sanitizers on Windows.")
            sys.exit(255)
        if env["arch"] not in ["x86_32", "x86_64"]:
            print("Sanitizers are only supported for x86_32 and x86_64.")
            sys.exit(255)

        env.extra_suffix += ".san"
        env.AppendUnique(CPPDEFINES=["SANITIZERS_ENABLED"])
        san_flags = []
        if env["use_asan"]:
            san_flags.append("-fsanitize=address")
        if env["use_ubsan"]:
            san_flags.append("-fsanitize=undefined")
            # Disable the vptr check since it gets triggered on any COM interface calls.
            san_flags.append("-fno-sanitize=vptr")
        env.Append(CFLAGS=san_flags)
        env.Append(CCFLAGS=san_flags)
        env.Append(LINKFLAGS=san_flags)

    if get_is_ar_thin_supported(env):
        env.Append(ARFLAGS=["--thin"])

    env.Append(CPPDEFINES=["WINDOWS_ENABLED", "WASAPI_ENABLED", "WINMIDI_ENABLED"])
    env.Append(
        CPPDEFINES=[
            "WINVER=0x0A00",
            "_WIN32_WINNT=0x0A00",
        ]
    )
    env.Append(
        LIBS=[
            "mingw32",
            "dsound",
            "ole32",
            "d3d9",
            "winmm",
            "gdi32",
            "iphlpapi",
            "shell32",
            "shlwapi",
            "shcore",
            "wsock32",
            "ws2_32",
            "kernel32",
            "oleaut32",
            "sapi",
            "dinput8",
            "dxguid",
            "ksuser",
            "imm32",
            "bcrypt",
            "crypt32",
            "avrt",
            "uuid",
            "dwmapi",
            "dwrite",
            "wbemuuid",
            "ntdll",
        ]
    )

    if env["accesskit"]:
        if env["accesskit_sdk_path"] != "":
            env.Prepend(CPPPATH=[env["accesskit_sdk_path"] + "/include"])
            if env["use_llvm"]:
                if env["arch"] == "arm64":
                    env.Append(LIBPATH=[env["accesskit_sdk_path"] + "/lib/windows/arm64/mingw-llvm/static/"])
                elif env["arch"] == "x86_64":
                    env.Append(LIBPATH=[env["accesskit_sdk_path"] + "/lib/windows/x86_64/mingw-llvm/static/"])
                elif env["arch"] == "x86_32":
                    env.Append(LIBPATH=[env["accesskit_sdk_path"] + "/lib/windows/x86/mingw-llvm/static/"])
            else:
                if env["arch"] == "x86_64":
                    env.Append(LIBPATH=[env["accesskit_sdk_path"] + "/lib/windows/x86_64/mingw/static/"])
                elif env["arch"] == "x86_32":
                    env.Append(LIBPATH=[env["accesskit_sdk_path"] + "/lib/windows/x86/mingw/static/"])
            env.Append(LIBPATH=["#bin/obj/platform/windows"])
            env.Append(
                LIBS=[
                    "accesskit",
                    "uiautomationcore." + env["arch"],
                    "runtimeobject",
                    "propsys",
                    "oleaut32",
                    "user32",
                    "userenv",
                    "ntdll",
                ]
            )
        else:
            env.Append(CPPDEFINES=["ACCESSKIT_DYNAMIC"])
        env.Append(LIBPATH=["#platform/windows"])
        env.Append(CPPDEFINES=["ACCESSKIT_ENABLED"])

    if env.debug_features:
        env.Append(LIBS=["psapi", "dbghelp"])

    if env["vulkan"]:
        env.Append(CPPDEFINES=["VULKAN_ENABLED", "RD_ENABLED"])
        if not env["use_volk"]:
            env.Append(LIBS=["vulkan"])

    if env["sdl"]:
        env.Append(CPPDEFINES=["SDL_ENABLED"])

    if env["d3d12"]:
        if env["use_llvm"]:
            check_d3d12_installed(env, env["arch"] + "-llvm")
        else:
            check_d3d12_installed(env, env["arch"] + "-gcc")

        env.AppendUnique(CPPDEFINES=["D3D12_ENABLED", "RD_ENABLED"])
        env.Append(LIBS=["dxgi", "dxguid"])

        # PIX
        if env["arch"] not in ["x86_64", "arm64"] or env["pix_path"] == "" or not os.path.exists(env["pix_path"]):
            env["use_pix"] = False

        if env["use_pix"]:
            arch_subdir = "arm64" if env["arch"] == "arm64" else "x64"

            env.Append(LIBPATH=[env["pix_path"] + "/bin/" + arch_subdir])
            env.Append(LIBS=["WinPixEventRuntime"])

        if env["use_llvm"] and os.path.exists(env["mesa_libs"] + "-" + env["arch"] + "-llvm"):
            env.Append(LIBPATH=[env["mesa_libs"] + "-" + env["arch"] + "-llvm/bin"])
        elif not env["use_llvm"] and os.path.exists(env["mesa_libs"] + "-" + env["arch"] + "-gcc"):
            env.Append(LIBPATH=[env["mesa_libs"] + "-" + env["arch"] + "-gcc/bin"])
        else:
            env.Append(LIBPATH=[env["mesa_libs"] + "/bin"])
        env.Append(LIBS=["libNIR.windows." + env["arch"]])
        env.Append(LIBS=["version"])  # Mesa dependency.

    if env["opengl3"]:
        env.Append(CPPDEFINES=["GLES3_ENABLED"])
        if env["angle_libs"] != "":
            env.AppendUnique(CPPDEFINES=["EGL_STATIC"])
            env.Append(LIBPATH=[env["angle_libs"]])
            env.Append(
                LIBS=[
                    "EGL.windows." + env["arch"],
                    "GLES.windows." + env["arch"],
                    "ANGLE.windows." + env["arch"],
                ]
            )
            env.Append(LIBS=["dxgi", "d3d9", "d3d11"])
        env.Prepend(CPPEXTPATH=["#thirdparty/angle/include"])

    env.Append(CPPDEFINES=["MINGW_ENABLED", ("MINGW_HAS_SECURE_API", 1)])

    # dlltool
    env.Append(BUILDERS={"DEF": env.Builder(action=build_def_file, suffix=".a", src_suffix=".def")})


def configure(env: "SConsEnvironment"):
    # Validate arch.
    supported_arches = ["x86_32", "x86_64", "arm32", "arm64"]
    validate_arch(env["arch"], get_name(), supported_arches)

    # At this point the env has been set up with basic tools/compilers.
    env.Prepend(CPPPATH=["#platform/windows"])

    env.msvc = "mingw" not in env["TOOLS"]
    if env.msvc:
        configure_msvc(env)
    else:
        configure_mingw(env)


def check_d3d12_installed(env, suffix):
    if not os.path.exists(env["mesa_libs"]) and not os.path.exists(env["mesa_libs"] + "-" + suffix):
        print_error(
            "The Direct3D 12 rendering driver requires dependencies to be installed.\n"
            "You can install them by running `python misc\\scripts\\install_d3d12_sdk_windows.py`.\n"
            "See the documentation for more information:\n\t"
            "https://docs.godotengine.org/en/latest/contributing/development/compiling/compiling_for_windows.html"
        )
        sys.exit(255)
