"""Finance Innovation trusted RAG package."""

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
