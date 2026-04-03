"""Backend loader for fork terminal."""

import importlib


def load_backend(name: str):
    """Load a backend module by name."""
    return importlib.import_module(f".{name}", package="backends")
