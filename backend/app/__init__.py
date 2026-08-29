"""Finance Innovation trusted RAG package."""

# Python 3.9 compatibility for the existing ``ssgs`` runtime.  The ``slots``
# keyword was added to ``dataclasses.dataclass`` in Python 3.10.  It is only a
# memory/layout optimization in this project, so ignoring it on 3.9 preserves
# the data model and business behaviour while allowing the model environment
# to remain unchanged.
import dataclasses
import sys

if sys.version_info < (3, 10):
    _stdlib_dataclass = dataclasses.dataclass

    def _dataclass_py39_compatible(*args, **kwargs):
        kwargs.pop("slots", None)
        return _stdlib_dataclass(*args, **kwargs)

    dataclasses.dataclass = _dataclass_py39_compatible

# Compatibility patch for Starlette/FastAPI Router across version variances
try:
    import starlette.routing
    _orig_router_init = starlette.routing.Router.__init__

    def _patched_router_init(self, *args, on_startup=None, on_shutdown=None, **kwargs):
        self.on_startup = on_startup or []
        self.on_shutdown = on_shutdown or []
        try:
            return _orig_router_init(self, *args, **kwargs)
        except TypeError:
            return _orig_router_init(self, *args, on_startup=on_startup, on_shutdown=on_shutdown, **kwargs)

    starlette.routing.Router.__init__ = _patched_router_init
except Exception:
    pass
