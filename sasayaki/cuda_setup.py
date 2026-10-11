"""Make pip-installed NVIDIA CUDA libraries (cuBLAS, cuDNN) visible to CTranslate2 on Windows.

Must run before `faster_whisper` / `ctranslate2` is first used.
"""

from __future__ import annotations

import glob
import os
import site
import sys

_done = False


def ensure_cuda_dlls() -> None:
    global _done
    if _done or sys.platform != "win32":
        return
    _done = True
    roots = list(site.getsitepackages())
    user = site.getusersitepackages()
    if user:
        roots.append(user)
    for root in roots:
        for d in glob.glob(os.path.join(root, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(d)
            except OSError:
                continue
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
