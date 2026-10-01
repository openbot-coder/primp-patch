import os

from primp_patch import patch as _patch


def _auto():
    if os.environ.get("PRIMP_PATCH_AUTO", "").lower() in ("1", "true", "yes"):
        _patch()


_auto()
