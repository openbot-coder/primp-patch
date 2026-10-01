"""primp-patch: replace requests/urllib3/http.client/urllib transport with primp at runtime.

    import primp_patch
    primp_patch.patch()          # one line; all four layers routed through primp
    # ... existing code using requests / urllib3 / urllib / http.client is untouched
"""
from ._patch import patch, unpatch, is_patched
from .transport import Response, Session, HTTPError

__version__ = "0.2.0"
__all__ = ["patch", "unpatch", "is_patched", "Session", "Response", "HTTPError"]
