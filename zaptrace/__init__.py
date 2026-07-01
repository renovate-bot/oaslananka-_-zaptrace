# ZapTrace — Agent-native electronics design core
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("zaptrace")
except PackageNotFoundError:
    __version__ = "0.3.0"

from zaptrace.core.models import Component, Design, Net, resolve_variant
from zaptrace.core.parser import parse_file, parse_str

__all__ = [
    "__version__",
    "Design",
    "Component",
    "Net",
    "resolve_variant",
    "parse_file",
    "parse_str",
]
