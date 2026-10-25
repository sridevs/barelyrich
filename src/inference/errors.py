"""Local inference failures shared by loading and generation."""


class TransformersRuntimeError(ValueError):
    """A local Transformers model could not safely run statement inference."""
