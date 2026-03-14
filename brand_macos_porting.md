# BRAND BCI Tutorial — macOS (Apple Silicon) Porting Notes

*March 2026 — Chethan Pandarinath Lab*

---

## Overview

BRAND (Backend for Real-time Asynchronous Neural Decoding) was originally designed for Ubuntu Linux with a PREEMPT_RT real-time kernel. This document summarizes every change required to run the brand-tutorial on macOS (Apple Silicon, arm64). All changes are macOS-specific additions that preserve full Linux compatibility.

Changes fall into five categories: new bootstrap/setup files, conda environment package version fixes, C source patches (Redis and build system), Python source patches (supervisor, display, mouse input), and Jupyter notebook/graph YAML configuration updates.

---

## 1. New Files Created

### 1.1 `brand/bootstrap_mac.sh`

A macOS replacement for `bootstrap.sh` that uses Homebrew instead of `apt-get`, downloads the macOS Elm binary (with Apple Silicon vs. Intel detection), uses `environment_mac.yaml`, and requires no `sudo`.

| `bootstrap.sh` (apt package) | `bootstrap_mac.sh` (brew package) | Notes |
|---|---|---|
| `libsqlite3-dev` | *(omitted)* | SQLite is bundled with macOS and Xcode CLT; no separate install needed |
| `automake` | `automake` | Direct equivalent |
| `libtool` | `libtool` | Direct equivalent |
| `curl` | `curl` | Direct equivalent |
| `libsdl2-2.0-0` + `libsdl2-dev` | `sdl2` | Homebrew formula includes both runtime and headers |
| `libsdl2-image-2.0-0` + `libsdl2-image-dev` | `sdl2_image` | Same — headers bundled |
| `libsdl2-gfx-1.0-0` + `libsdl2-gfx-dev` | `sdl2_gfx` | Same — headers bundled |
| `libsdl2-ttf-dev` | `sdl2_ttf` | Same — headers bundled |
| *(not present)* | `pkg-config` | Added — required for the pygame build on macOS |

### 1.2 `brand/environment_mac.yaml`

A macOS-specific conda environment file derived from `environment.yaml`.

**Dropped conda packages**

Several Linux-specific packages present in `environment.yaml` were removed entirely. These are internal conda bookkeeping packages that only exist in the Linux conda channel — they have no macOS equivalents because macOS ships its own system C/C++ runtime and linker:

| Dropped package | Reason |
|---|---|
| `_libgcc_mutex=0.1` | Internal conda mutex for managing the Linux GCC runtime; not applicable on macOS |
| `ld_impl_linux-64=2.33.1` | GNU binutils linker for Linux x86-64; macOS uses Apple's `ld` (part of Xcode CLT) |
| `libgcc-ng=9.1.0` | GCC runtime library for Linux; macOS uses its own `libSystem` / `libc++` |
| `libstdcxx-ng=9.1.0` | GNU C++ standard library for Linux; macOS uses `libc++` (LLVM), bundled with Xcode |

**Relaxed conda-level pins**

The remaining conda-level packages were either dropped (pinned versions not available in macOS conda channels) or their version constraints loosened to allow conda to resolve arm64-compatible versions:

| Package | `environment.yaml` | `environment_mac.yaml` | Reason |
|---|---|---|---|
| `python` | `3.8.2` | `3.8` | Exact patch version not available in macOS channel; any 3.8.x is fine |
| `pip` | `20.0.2` | unpinned | Old pip versions lack arm64 wheel support; let conda pick latest |
| `setuptools` | `46.4.0` | unpinned | Pinned version unavailable on macOS; latest is compatible |
| `wheel` | `0.34.2` | unpinned | Same reason |
| `ca-certificates`, `certifi`, `libedit`, `libffi`, `ncurses`, `openssl`, `readline`, `sqlite`, `tk`, `xz`, `zlib` | pinned | *(omitted)* | These are system-level libraries managed by macOS/Xcode; conda does not need to install them |

**pip package version bumps**

The following pip packages were bumped to obtain arm64-compatible wheels:

| Package | Change |
|---|---|
| `numpy` | `1.18.4` → `>=1.21.0` |
| `scipy` | `1.4.1` → `>=1.7.0` |
| `h5py` | `3.3.0` → `>=3.6.0` |
| `pygame` | `2.0.0` → `>=2.1.2` |
| `pytorch-lightning` | `1.7.1` → `>=1.8.0,<2.0.0` |
| `pyyaml` | `6.0` → `>=6.0.1` |
| `cython` | `0.29.18` → `>=0.29.28` |
| `kiwisolver` | `1.2.0` → `>=1.3.1` |
| `markupsafe` | `1.1.1` → `>=2.0.0` |
| `matplotlib` | `3.2.1` → `>=3.5.0` |
| `pyrsistent` | `0.16.0` → `>=0.18.0` |
| `pyzmq` | `19.0.1` → `>=22.0.0` |
| `ruamel-yaml-clib` | `0.2.6` → `>=0.2.7` |
| `tornado` | `6.0.4` → `>=6.1.0` |
| `grpcio` | `1.47.0` → `>=1.51.1` |
| `pandas` | `1.3.2` → `>=1.5.0` |
| `nbconvert` | `5.6.1` → `>=6.3` |
| `pynwb` | `2.0.0` → `>=2.3.0` (dropped `pandas<2` requirement) |
| `hdmf` | `3.3.1` → `>=3.5.0` (dropped `pandas<2` requirement) |
| `pyglet` | `1.5.11` → `>=2.0` (see §5.1) |
| `pickle5` | Removed — built into Python 3.8 |
| `jinja2` | Added `>=3.0` (required by markupsafe 2.1+, see §5.2) |

### 1.3 `brand/setup_mac.sh`

A macOS replacement for `setup.sh`:

- `supervisor` alias passes `-s /tmp/redis.sock` (macOS cannot write to `/var/run` without root)
- No `sudo`, no real-time scheduling aliases (`chrt`/`taskset` not available on macOS)

### 1.4 `brand-modules/brand-simulator/nodes/mouseAdapter/mouseAdapter.py`

A full Python/pygame replacement for `mouseAdapter.c`. The C implementation reads raw events from the Linux evdev interface (`/dev/input/event*`), which does not exist on macOS.

- Publishes to the same `mouse_vel` Redis stream with identical binary format: `3×int16 [delta_x, delta_y, left_button]`
- Accepts `mouse_device` parameter from graph YAML but ignores it on macOS
- Uses `pygame.mouse.get_rel()` and `pygame.mouse.get_pressed()` for cross-platform input
- Fixed-deadline sleep loop for accurate `sample_rate` timing
- Window size configurable via `window_width` / `window_height` parameters (default 200×200)

---

## 2. Build System Patches

### 2.1 `brand/Makefile` — ldconfig and module exclusions

`ldconfig` (Linux-only dynamic linker cache tool) wrapped in a `uname` conditional so it is skipped on macOS:

```makefile
$(if $(filter Darwin,$(shell uname)),,ldconfig -C /tmp/cache $(HIREDIS_PATH) && $(RM) /tmp/cache)
```

Linux-only modules excluded from the macOS build:

- `brand-nsp` — Cerebus hardware adapter, requires proprietary SDK
- `brand-simulator/nodes/cb_generator` — uses `linux/input.h`

### 2.2 `brand/setenv.mk` — RPATH_PREFIX

Apple's linker uses comma syntax for `-rpath` flags while GNU ld uses equals syntax. A new make variable `RPATH_PREFIX` was added and all 17 node Makefiles were bulk-patched:

```makefile
# macOS
export RPATH_PREFIX = -Wl,-rpath,
# Linux
export RPATH_PREFIX = -Wl,-rpath=
```

All node Makefiles: `-Wl,-rpath=` → `$(RPATH_PREFIX)` (17 files)

### 2.3 `brand-modules/brand-simulator/nodes/mouseAdapter/Makefile`

Made OS-conditional: on macOS the node compiles `mouseAdapter.py` via Cython (using `mouseAdapter_cython.c` as intermediate to avoid overwriting the original C source); on Linux the original C build path is used unchanged.

---

## 3. Redis Source Patches

Redis in the BRAND repo predates the removal of several deprecated C library symbols from modern macOS SDKs. Two source files required patching.

### 3.1 `brand/lib/redis/src/config.h` — fstat64 / stat64

A branch guarded by `MAC_OS_X_VERSION_10_6` misfired on modern macOS because that macro is defined in `Availability.h`, which is not yet included when `config.h` is first processed. This caused the compiler to reference `fstat64` and `stat64`, which were removed from newer macOS SDKs.

**Fix:** removed the dead pre-10.6 branch; unconditionally defined `redis_fstat = fstat` and `redis_stat = stat`.

### 3.2 `brand/lib/redis/src/debug.c` — `__srr0` (PowerPC register)

The same `MAC_OS_X_VERSION_10_6` misfire caused the compiler to select an old PowerPC code path on arm64, referencing the `__srr0` register, which does not exist on Apple Silicon.

**Fix:** collapsed two Apple branches into a single modern branch with explicit checks for x86-64, i386, and arm64:

```c
/* arm64 path */
return (void*) arm_thread_state64_get_pc(uc->uc_mcontext->__ss);
```

---

## 4. Python Source Patches

### 4.1 `brand/lib/python/brand/supervisor.py` — real-time scheduling

`chrt` (run_priority) and `taskset` (cpu_affinity) are Linux-specific tools for real-time thread scheduling and CPU pinning. They do not exist on macOS.

**Fix:** both blocks wrapped in `platform.system() != 'Darwin'` checks. On macOS a warning is logged if these parameters are set, but the node still launches.

### 4.2 `brand/lib/python/brand/redis.supervisor.conf` — Unix socket path

The default Redis Unix socket path `/var/run/redis.sock` requires root to write to on macOS.

**Fix:** `unixsocket /var/run/redis.sock` → `unixsocket /tmp/redis.sock`

### 4.3 `brand/lib/python/brand/timing.py` — libc loading

The file hardcoded `ctypes.CDLL('libc.so.6')`, which is the Linux library name.

**Fix:** `ctypes.CDLL('libc.so.6')` → `ctypes.CDLL(ctypes.util.find_library('c'))`

### 4.4 `brand-modules/cursor-control/nodes/display_centerOut/display_centerOut.py`

Two issues fixed:

- **DISPLAY check:** the node exited with `No display found` because it checked for the X11 `DISPLAY` environment variable, which is not used on macOS. **Fix:** wrapped in `platform.system() != 'Darwin'`.
- **pyglet API:** upgrading to pyglet 2.x (required for §5.1) removed `OrderedGroup`. **Fix:** `OrderedGroup(0/1)` → `Group(order=0/1)`.

---

## 5. Runtime Dependency Issues Resolved

### 5.1 pyglet — `class_getMethodImplementation_stret` crash

pyglet 1.x calls `class_getMethodImplementation_stret`, an Objective-C runtime function removed in macOS 12+. This caused an immediate crash when the display node tried to open a window.

**Fix:** upgraded pyglet to `>=2.0`. Also required the `OrderedGroup` API update in §4.4.

### 5.2 jinja2 / markupsafe / nbconvert version conflict

Upgrading `markupsafe` to 2.1+ (required for arm64) removed `soft_unicode`, which older `jinja2` depended on. Separately, old `nbconvert` used `contextfilter` which was removed in jinja2 3.0.

**Fix:** pinned `jinja2>=3.0` and `nbconvert>=6.3`.

### 5.3 pandas / numpy ABI mismatch

`pandas 1.3.2` was compiled against `numpy 1.18.x`. After upgrading numpy to `>=1.21.0` for arm64 support, importing pandas raised a binary incompatibility error.

**Fix:** upgraded `pandas` to `>=1.5.0`; also upgraded `pynwb` to `>=2.3.0` and `hdmf` to `>=3.5.0`, which both had an incompatible `pandas<2` constraint.

---

## 6. Graph & Notebook Configuration

### 6.1 `notebooks/graphs/sim_graph_ol.yaml` and `sim_graph_cl.yaml`

- `fullscreen: true` → `false` (fullscreen mode covered the mouse adapter window on a single laptop display)
- `window_width` / `window_height`: `1920×1080` → `800×800` (more appropriate for a laptop screen)

### 6.2 mouseAdapter pygame window size

The pygame window used to capture mouse input was hardcoded to `200×50` px. Changed to read optional `window_width` / `window_height` parameters from the graph YAML (defaulting to `200×200`).

---

## 7. Known Remaining Issues & Next Steps

- **Wiener filter calibration:** decoder R² is near zero in initial tests. Mouse movement and Redis stream data confirmed working; root cause under investigation.
- **Real-time scheduling:** `run_priority` and `cpu_affinity` are silently ignored on macOS. Acceptable for research use; a macOS-specific scheduling approach would be needed for latency-critical applications.
- **Linux regression testing:** the new conditional Makefile for mouseAdapter has not been verified end-to-end on Linux; the original C path is preserved.
- **PR preparation:** changes should be cleaned up and submitted as a pull request to the BRAND and brand-tutorial repositories.

---

*Generated March 2026 — All changes are backward-compatible with Linux.*
