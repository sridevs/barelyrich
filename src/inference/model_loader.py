"""Offline model loading, device selection and process-wide resource caching."""


from src.log_messages import error as error_messages
from src.inference.loaded_model import LoadedModel
from contextlib import contextmanager
from threading import Lock
from typing import Any

from src.inference.configuration import TransformersRuntimeConfig
from src.inference.errors import TransformersRuntimeError

try:
    import torch
except ImportError:
    torch = None

try:
    from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoProcessor, AutoTokenizer
except ImportError:
    AutoProcessor = None
    AutoModelForImageTextToText = None
    AutoModelForCausalLM = AutoTokenizer = None

_CACHE_LOCK = Lock()
_MODEL_CACHE: dict[tuple[str, str, str], LoadedModel] = {}


def get_loaded_model(configuration: TransformersRuntimeConfig) -> LoadedModel:
    torch = _import_torch()
    device = _resolve_device(torch, configuration.device)
    cache_key = (configuration.model_name.strip(), device, configuration.model_kind)
    with _CACHE_LOCK:
        loaded_model = _MODEL_CACHE.get(cache_key)
        if loaded_model is None:
            loaded_model = _load_model(torch, cache_key[0], device, text_only=configuration.model_kind == "text")
            _MODEL_CACHE[cache_key] = loaded_model
    return loaded_model


def _import_torch() -> Any:
    if torch is None:
        raise TransformersRuntimeError(
            error_messages.LOCAL_INFERENCE_DEPENDENCIES_REQUIRED
        )
    return torch


def _resolve_device(torch: Any, requested_device: str) -> str:
    cuda_available, mps_available = _available_devices(torch)
    if requested_device == "auto":
        return "cuda" if cuda_available else "mps" if mps_available else "cpu"
    if requested_device == "cuda" and not cuda_available:
        raise TransformersRuntimeError(
            error_messages.CUDA_UNAVAILABLE
        )
    if requested_device == "mps" and not mps_available:
        raise TransformersRuntimeError(
            error_messages.MPS_UNAVAILABLE
        )
    return requested_device


def _available_devices(torch: Any) -> tuple[bool, bool]:
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    return (
        bool(torch.cuda.is_available()),
        bool(mps_backend and getattr(mps_backend, "is_available", lambda: False)()),
    )


def _load_model(torch: Any, model_name: str, device: str, *, text_only: bool = False) -> LoadedModel:
    processor_class, model_class = _model_classes(text_only)
    with _model_loading_errors(torch, model_name, text_only):
        processor = processor_class.from_pretrained(
            model_name, local_files_only=True, trust_remote_code=False,
        )
        model = _load_weights(model_class, torch, model_name, device)
    return LoadedModel(processor, model, torch, Lock())


def _model_classes(text_only: bool) -> tuple[Any, Any]:
    processor_class = AutoTokenizer if text_only else AutoProcessor
    model_class = AutoModelForCausalLM if text_only else AutoModelForImageTextToText
    if processor_class is None or model_class is None:
        raise TransformersRuntimeError(
            error_messages.TRANSFORMERS_MODEL_SUPPORT_REQUIRED
        )

    return processor_class, model_class


def _load_weights(model_class: Any, torch: Any, model_name: str, device: str) -> Any:
    model = model_class.from_pretrained(
        model_name,
        local_files_only=True,
        use_safetensors=True,
        trust_remote_code=False,
        dtype=torch.float32 if device == "cpu" else torch.float16,
        attn_implementation="sdpa",
    )
    model.to(device)
    model.eval()
    return model


@contextmanager
def _model_loading_errors(torch: Any, model_name: str, text_only: bool):
    try:
        yield
    except ImportError as error:
        raise _model_dependency_error(model_name) from error
    except RuntimeError as error:
        if is_out_of_memory(error, torch):
            raise TransformersRuntimeError(
                error_messages.MODEL_LOADING_OUT_OF_MEMORY
            ) from error
        raise
    except (OSError, ValueError) as error:
        raise _local_files_error(model_name, text_only) from error


def _model_dependency_error(model_name: str) -> TransformersRuntimeError:
    return TransformersRuntimeError(
        error_messages.MODEL_DEPENDENCY_REQUIRED.format(model_name=model_name)
    )


def _local_files_error(model_name: str, text_only: bool) -> TransformersRuntimeError:
    setting = "WT_TEXT_MODEL" if text_only else "WT_TRANSFORMERS_MODEL"
    return TransformersRuntimeError(
        error_messages.LOCAL_MODEL_FILES_UNAVAILABLE.format(model_name=model_name, setting=setting)
    )


def is_out_of_memory(error: RuntimeError, torch: Any) -> bool:
    error_types = []
    for backend in (
            getattr(torch, "cuda", None),
            getattr(torch, "mps", None),
    ):
        out_of_memory_type = getattr(backend, "OutOfMemoryError", None)
        if isinstance(out_of_memory_type, type):
            error_types.append(out_of_memory_type)
    return bool(error_types and isinstance(error, tuple(error_types))) or (
            "out of memory" in str(error).casefold()
    )
