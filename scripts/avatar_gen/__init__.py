from .base import AvatarClient, AvatarQualityError
from .factory import make_avatar_client
from .heygen_client import HeyGenAvatarClient
from .kling_client import KlingAvatarClient

# EchoMimicClient kept in echomimic_client.py as a reference artifact —
# superseded by HeyGen/Kling backends (2026-03-29).

__all__ = [
    "AvatarClient",
    "AvatarQualityError",
    "HeyGenAvatarClient",
    "KlingAvatarClient",
    "make_avatar_client",
]
