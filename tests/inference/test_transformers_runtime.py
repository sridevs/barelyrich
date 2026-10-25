from contextlib import contextmanager
from base64 import b64decode
from io import BytesIO
from threading import Event, Thread
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from src.config import DEFAULT_TRANSFORMERS_MODEL
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_page import StatementPage
from src.inference import model_loader, page_images
from src.inference.configuration import TransformersRuntimeConfig
from src.inference.transformers_runtime import (
    TransformersRuntime,
    TransformersRuntimeError,
)

try:
    from PIL import Image
except ImportError:
    Image = None

PAGE_IMAGE = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/"
    "AAX+Av4N70a4AAAAAElFTkSuQmCC"
)


class FakeTensor:
    def __init__(self, rows):
        self.rows = rows
        self.shape = (len(rows), len(rows[0]))

    def __getitem__(self, indices):
        row_selection, column_selection = indices
        if isinstance(row_selection, int) and isinstance(column_selection, int):
            return SimpleNamespace(item=lambda: self.rows[row_selection][column_selection])
        return FakeTensor([row[column_selection] for row in self.rows[row_selection]])


class FakeBatch(dict):
    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords)
        self.destination = None

    def to(self, device):
        self.destination = device
        return self


class FakeProcessor:
    def __init__(self, input_token_count=3, decoded_text='{"balances":[]}'):
        self.input_token_count = input_token_count
        self.decoded_text = decoded_text
        self.messages = None
        self.decoded_tokens = None
        self.template_options = None
        self.decode_options = None

    def apply_chat_template(self, messages, **options):
        for message in messages:
            assert isinstance(message["content"], list)
            for content_part in message["content"]:
                assert isinstance(content_part, dict)
                assert content_part["type"] in {"text", "image"}
        self.messages = messages
        self.template_options = options
        return FakeBatch({
            "input_ids": FakeTensor([list(range(self.input_token_count))]),
            "token_type_ids": FakeTensor([[0] * self.input_token_count]),
        })

    def batch_decode(self, generated_tokens, **options):
        self.decoded_tokens = generated_tokens
        self.decode_options = options
        return [self.decoded_text]


class FakeModel:
    def __init__(self, output_token_count=2, generate_action=None, grad_state=None):
        self.output_token_count = output_token_count
        self.generate_action = generate_action
        self.grad_state = grad_state
        self.destination = None
        self.is_eval = False
        self.generate_calls = []
        self.grad_enabled_during_generation = []
        self.device = None
        self.generation_config = SimpleNamespace(eos_token_id=91)
        self.config = SimpleNamespace(model_type="qwen3_vl")

    def to(self, device):
        self.destination = device
        self.device = device
        return self

    def eval(self):
        self.is_eval = True
        return self

    def generate(self, **inputs):
        self.generate_calls.append(inputs)
        if self.grad_state is not None:
            self.grad_enabled_during_generation.append(self.grad_state["enabled"])
        if self.generate_action is not None:
            return self.generate_action(inputs)
        input_ids = inputs["input_ids"]
        return FakeTensor([
            [*input_ids.rows[0], *([91] * self.output_token_count)]
        ])


def install_fake_runtime_modules(
    monkeypatch,
    *,
    cuda_available=False,
    mps_available=False,
    input_token_count=3,
    output_token_count=2,
    generate_action=None,
    decoded_text='{"balances":[]}',
):
    load_calls = {"processors": [], "models": []}
    grad_state = {"enabled": True}
    processor = FakeProcessor(input_token_count, decoded_text)
    model = FakeModel(output_token_count, generate_action, grad_state)

    class FakeCudaOutOfMemoryError(RuntimeError):
        pass

    fake_torch = ModuleType("torch")
    fake_torch.cuda = SimpleNamespace(
        is_available=lambda: cuda_available,
        OutOfMemoryError=FakeCudaOutOfMemoryError,
    )
    fake_torch.mps = SimpleNamespace(OutOfMemoryError=FakeCudaOutOfMemoryError)
    fake_torch.backends = SimpleNamespace(
        mps=SimpleNamespace(is_available=lambda: mps_available),
    )
    fake_torch.float32 = "float32"
    fake_torch.float16 = "float16"

    @contextmanager
    def inference_mode():
        previous_state = grad_state["enabled"]
        grad_state["enabled"] = False
        try:
            yield
        finally:
            grad_state["enabled"] = previous_state

    fake_torch.inference_mode = inference_mode

    class FakeAutoProcessor:
        @classmethod
        def from_pretrained(cls, model_name, **options):
            load_calls["processors"].append((model_name, options))
            return processor

    class FakeAutoModel:
        @classmethod
        def from_pretrained(cls, model_name, **options):
            load_calls["models"].append((model_name, options))
            return model

    monkeypatch.setattr(model_loader, "torch", fake_torch)
    monkeypatch.setattr(model_loader, "AutoProcessor", FakeAutoProcessor)
    monkeypatch.setattr(model_loader, "AutoModelForImageTextToText", FakeAutoModel)
    monkeypatch.setattr(model_loader, "_MODEL_CACHE", {})
    return processor, model, load_calls, grad_state, FakeCudaOutOfMemoryError


def test_runtime_defaults_and_environment_configuration(monkeypatch, tmp_path):
    model_directory = tmp_path / "offline-qwen"
    monkeypatch.setenv("WT_TRANSFORMERS_MODEL", str(model_directory))
    monkeypatch.setenv("WT_TRANSFORMERS_DEVICE", "MPS")

    runtime = TransformersRuntime.from_environment()

    assert runtime.configuration.model_name == str(model_directory)
    assert runtime.configuration.device == "mps"
    assert TransformersRuntime().configuration.model_name == DEFAULT_TRANSFORMERS_MODEL


def test_environment_can_adjust_statement_output_budget(monkeypatch):
    monkeypatch.setenv("WT_TRANSFORMERS_MAX_NEW_TOKENS", "16384")
    assert TransformersRuntimeConfig.from_environment().max_new_tokens == 16384
    for value in ("invalid", "0", "32769"):
        monkeypatch.setenv("WT_TRANSFORMERS_MAX_NEW_TOKENS", value)
        with pytest.raises(ValueError):
            TransformersRuntimeConfig.from_environment()


def test_text_model_defaults_to_qwen_and_has_independent_override(monkeypatch):
    monkeypatch.delenv("WT_TEXT_MODEL", raising=False)
    monkeypatch.setenv("WT_TRANSFORMERS_MODEL", "vision-model")
    configuration = TransformersRuntimeConfig.from_environment(model_kind="text")
    assert configuration.model_name == "Qwen/Qwen3-4B-Instruct-2507"
    assert configuration.model_kind == "text"
    monkeypatch.setenv("WT_TEXT_MODEL", "/local/text-model")
    assert TransformersRuntimeConfig.from_environment(model_kind="text").model_name == "/local/text-model"
    assert TransformersRuntimeConfig.from_environment().model_name == "vision-model"


def test_causal_text_model_uses_tokenizer_string_messages_and_offline_loading(monkeypatch):
    processor, model, calls, _, _ = install_fake_runtime_modules(monkeypatch)
    tokenizer = SimpleNamespace(
        apply_chat_template=lambda messages, **options: FakeBatch({
            "input_ids": FakeTensor([[1, 2, 3]]),
        }),
        batch_decode=processor.batch_decode,
    )
    tokenizer_calls = []
    model_calls = []
    messages_seen = []

    def tokenize(messages, **options):
        messages_seen.extend(messages)
        assert all(isinstance(message["content"], str) for message in messages)
        return FakeBatch({"input_ids": FakeTensor([[1, 2, 3]])})

    tokenizer.apply_chat_template = tokenize

    def load_tokenizer(name, **options):
        tokenizer_calls.append((name, options))
        return tokenizer

    def load_model(name, **options):
        model_calls.append((name, options))
        return model

    monkeypatch.setattr(model_loader, "AutoTokenizer", SimpleNamespace(from_pretrained=load_tokenizer))
    monkeypatch.setattr(model_loader, "AutoModelForCausalLM", SimpleNamespace(from_pretrained=load_model))
    configuration = TransformersRuntimeConfig(
        model_name="Qwen/Qwen3-4B-Instruct-2507", model_kind="text", device="cpu",
    )
    runtime = TransformersRuntime(configuration)
    document = StatementDocument((StatementPage(1, b"", "Example Bank SGD 10.25"),))
    assert runtime.generate(document, "Extract JSON") == '{"balances":[]}'
    assert runtime.generate(document, "Extract JSON") == '{"balances":[]}'
    assert len(tokenizer_calls) == len(model_calls) == 1
    assert not calls["models"] and not calls["processors"]
    assert tokenizer_calls[0][1] == {"local_files_only": True, "trust_remote_code": False}
    assert model_calls[0][1]["use_safetensors"] is True
    assert model_calls[0][1]["local_files_only"] is True
    assert "Example Bank SGD 10.25" in messages_seen[1]["content"]
    with pytest.raises(ValueError, match="not page images"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "Extract JSON")


@pytest.mark.parametrize(("field_name", "invalid_value"), [
    ("device", "tpu"),
    ("max_new_tokens", 0),
    ("max_input_tokens", 131073),
    ("max_image_pixels", 0),
    ("max_time_seconds", 0),
    ("max_time_seconds", 181),
    ("max_time_seconds", True),
])
def test_configuration_rejects_unsupported_limits(field_name, invalid_value):
    with pytest.raises(ValueError):
        TransformersRuntimeConfig(**{field_name: invalid_value})


def test_configuration_rejects_blank_model_name():
    with pytest.raises(ValidationError, match="model_name"):
        TransformersRuntimeConfig(model_name=" ")


@pytest.mark.parametrize("field_name, upper_bound", [
    ("max_new_tokens", 32768),
    ("max_input_tokens", 131072),
    ("max_image_pixels", 4_000_000),
    ("max_time_seconds", 180),
])
def test_pydantic_configuration_enforces_strict_numeric_boundaries(field_name, upper_bound):
    for value in (1, upper_bound):
        assert getattr(TransformersRuntimeConfig(**{field_name: value}), field_name) == value
    for value in (0, upper_bound + 1, True, "1", 1.0):
        with pytest.raises(ValidationError):
            TransformersRuntimeConfig(**{field_name: value})


def test_pydantic_configuration_is_frozen_and_rejects_unknown_fields():
    configuration = TransformersRuntimeConfig()
    with pytest.raises(ValidationError, match="frozen"):
        configuration.device = "cpu"
    with pytest.raises(ValidationError, match="Extra inputs"):
        TransformersRuntimeConfig(unknown_setting=1)
    for value in (None, 1, "", " " * 2, "x" * 301):
        with pytest.raises(ValidationError):
            TransformersRuntimeConfig(model_name=value)


def test_selected_model_overrides_environment_without_mutating_it(monkeypatch):
    monkeypatch.setenv("WT_TRANSFORMERS_MODEL", "/local/default")
    monkeypatch.setenv("WT_TRANSFORMERS_DEVICE", "CPU")
    selected = TransformersRuntime.from_environment(model_name="Qwen/Qwen3-VL-2B-Instruct")
    assert selected.configuration.model_name == "Qwen/Qwen3-VL-2B-Instruct"
    assert selected.configuration.device == "cpu"
    assert TransformersRuntime.from_environment().configuration.model_name == "/local/default"
    with pytest.raises(ValidationError, match="model_name"):
        TransformersRuntime.from_environment(model_name="")


@pytest.mark.parametrize("model_name", [
    "Qwen/Qwen3-VL-2B-Instruct", "/local/custom-vision-model",
])
def test_selected_vision_model_uses_offline_auto_loader_and_separate_cache(monkeypatch, model_name):
    _, _, calls, _, _ = install_fake_runtime_modules(monkeypatch)
    document = StatementDocument((StatementPage(1, PAGE_IMAGE),))
    default_runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    selected_runtime = TransformersRuntime(TransformersRuntimeConfig(
        model_name=model_name, device="cpu",
    ))
    default_runtime.generate(document, "prompt")
    selected_runtime.generate(document, "prompt")
    selected_runtime.generate(document, "prompt")

    assert [name for name, options in calls["models"]] == [DEFAULT_TRANSFORMERS_MODEL, model_name]
    assert all(options["local_files_only"] for name, options in calls["models"])
    assert all(options["trust_remote_code"] is False for name, options in calls["models"])


def test_missing_torch_dependency_has_actionable_error(monkeypatch):
    monkeypatch.setattr(model_loader, "torch", None)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(TransformersRuntimeError, match="requires PyTorch and Transformers"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


def test_generation_uses_local_only_qwen_and_slices_prompt_tokens(monkeypatch):
    processor, model, load_calls, grad_state, _ = install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    document = StatementDocument((StatementPage(1, PAGE_IMAGE),))

    response = runtime.generate(document, "Extract JSON matching this schema.")

    assert response == '{"balances":[]}'
    assert load_calls["processors"] == [(
        DEFAULT_TRANSFORMERS_MODEL,
        {"local_files_only": True, "trust_remote_code": False},
    )]
    assert load_calls["models"] == [(
        DEFAULT_TRANSFORMERS_MODEL,
        {
            "local_files_only": True,
            "use_safetensors": True,
            "trust_remote_code": False,
            "dtype": "float32",
            "attn_implementation": "sdpa",
        },
    )]
    assert model.destination == "cpu"
    assert model.is_eval
    assert model.generate_calls[0]["do_sample"] is False
    assert model.generate_calls[0]["max_new_tokens"] == 8192
    assert model.generate_calls[0]["max_time"] == 180
    assert "token_type_ids" not in model.generate_calls[0]
    assert processor.decoded_tokens.rows == [[91, 91]]
    assert model.grad_enabled_during_generation == [False]
    assert grad_state["enabled"]
    assert processor.messages[0] == {
        "role": "system",
        "content": [{"type": "text", "text": "Extract JSON matching this schema."}],
    }
    assert "Statement page 1 image" in processor.messages[1]["content"][0]["text"]
    assert processor.messages[1]["content"][1]["type"] == "image"


def test_text_only_generation_uses_no_image_preprocessing(monkeypatch):
    processor, model, _, _, _ = install_fake_runtime_modules(monkeypatch)

    def forbid_images(*arguments):
        pytest.fail("Text-only generation must not decode images.")

    monkeypatch.setattr(page_images, "load_bounded_image", forbid_images)
    document = StatementDocument((
        StatementPage(1, b"", "Example Bank"),
        StatementPage(2, b"", "Closing balance SGD 10.25"),
    ))
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    assert runtime.generate(document, "Extract statement JSON.") == '{"balances":[]}'
    parts = processor.messages[1]["content"]
    assert all(part["type"] == "text" for part in parts)
    assert "Statement page 2" in parts[1]["text"]
    assert "Closing balance SGD 10.25" in parts[1]["text"]
    assert len(model.generate_calls) == 1


def test_cached_model_and_processor_are_reused_between_runtime_instances(monkeypatch):
    _, _, load_calls, _, _ = install_fake_runtime_modules(monkeypatch)
    document = StatementDocument((StatementPage(1, PAGE_IMAGE),))
    first_runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    second_runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    first_runtime.generate(document, "prompt")
    second_runtime.generate(document, "prompt")

    assert len(load_calls["processors"]) == 1
    assert len(load_calls["models"]) == 1


def test_runtime_supplies_page_images_in_user_content(monkeypatch):
    processor, _, _, _, _ = install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    document = StatementDocument((StatementPage(3, PAGE_IMAGE),))
    prompt = "Extract JSON using the supplied schema and page metadata."

    runtime.generate(document, prompt)

    assert processor.messages[0]["content"] == [{"type": "text", "text": prompt}]
    page_text = processor.messages[1]["content"][0]["text"]
    assert "Statement page 3" in page_text
    assert processor.messages[1]["content"][1]["type"] == "image"


@pytest.mark.parametrize(
    ("cuda_available", "mps_available", "expected_device", "expected_dtype"),
    [
        (True, True, "cuda", "float16"),
        (False, True, "mps", "float16"),
        (False, False, "cpu", "float32"),
    ],
)
def test_auto_device_prefers_cuda_then_mps_then_cpu(
    monkeypatch, cuda_available, mps_available, expected_device, expected_dtype,
):
    _, model, load_calls, _, _ = install_fake_runtime_modules(
        monkeypatch,
        cuda_available=cuda_available,
        mps_available=mps_available,
    )
    runtime = TransformersRuntime()

    runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")

    assert model.destination == expected_device
    assert load_calls["models"][0][1]["dtype"] == expected_dtype


@pytest.mark.parametrize(("requested_device", "cuda_available", "mps_available"), [
    ("cuda", False, False),
    ("mps", False, False),
])
def test_explicit_unavailable_device_fails_clearly(
    monkeypatch, requested_device, cuda_available, mps_available,
):
    install_fake_runtime_modules(
        monkeypatch,
        cuda_available=cuda_available,
        mps_available=mps_available,
    )
    runtime = TransformersRuntime(TransformersRuntimeConfig(device=requested_device))

    with pytest.raises(TransformersRuntimeError, match="unavailable"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


@pytest.mark.parametrize("missing_component", [
    "AutoProcessor", "AutoModelForImageTextToText",
])
def test_missing_transformers_dependency_has_actionable_error(monkeypatch, missing_component):
    install_fake_runtime_modules(monkeypatch)
    monkeypatch.setattr(model_loader, missing_component, None)

    with pytest.raises(TransformersRuntimeError, match="Transformers with Qwen3-VL"):
        TransformersRuntime(TransformersRuntimeConfig(device="cpu")).generate(
            StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt",
        )


def test_missing_pillow_dependency_has_actionable_error(monkeypatch):
    install_fake_runtime_modules(monkeypatch)
    monkeypatch.setattr(page_images, "Image", None)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    document = StatementDocument((StatementPage(1, b"image"),))

    with pytest.raises(TransformersRuntimeError, match="require Pillow"):
        runtime.generate(document, "prompt")


def test_missing_local_model_error_explains_no_downloads(monkeypatch):
    install_fake_runtime_modules(monkeypatch)

    class MissingLocalModel:
        @classmethod
        def from_pretrained(cls, model_name, **options):
            raise OSError("model is not cached")

    monkeypatch.setattr(
        model_loader,
        "AutoModelForImageTextToText",
        MissingLocalModel,
    )
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    with pytest.raises(TransformersRuntimeError, match="does not download models"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


def test_loading_model_oom_has_actionable_guidance(monkeypatch):
    install_fake_runtime_modules(monkeypatch)

    class OutOfMemoryModel:
        @classmethod
        def from_pretrained(cls, model_name, **options):
            raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(
        model_loader,
        "AutoModelForImageTextToText",
        OutOfMemoryModel,
    )
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(TransformersRuntimeError, match="while loading"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


def test_processor_import_error_explains_torchvision_requirement(monkeypatch):
    _, _, load_calls, _, _ = install_fake_runtime_modules(monkeypatch)

    class MissingVideoProcessorDependency:
        @classmethod
        def from_pretrained(cls, model_name, **options):
            raise ImportError("AutoVideoProcessor requires torchvision")

    monkeypatch.setattr(
        model_loader, "AutoProcessor", MissingVideoProcessorDependency,
    )
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(
        TransformersRuntimeError, match=r"local-model.*torchvision.*image-only",
    ) as error_info:
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")
    assert isinstance(error_info.value.__cause__, ImportError)
    assert load_calls["models"] == []


def test_input_token_limit_prevents_generation(monkeypatch):
    _, model, _, _, _ = install_fake_runtime_modules(monkeypatch, input_token_count=4)
    runtime = TransformersRuntime(TransformersRuntimeConfig(
        device="cpu",
        max_input_tokens=3,
    ))

    with pytest.raises(TransformersRuntimeError, match="4 tokens.*3-token limit"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")
    assert model.generate_calls == []


def test_output_token_limit_rejects_truncated_response(monkeypatch):
    _, _, _, _, _ = install_fake_runtime_modules(monkeypatch, output_token_count=2)
    runtime = TransformersRuntime(TransformersRuntimeConfig(
        device="cpu",
        max_new_tokens=2,
    ))

    with pytest.raises(TransformersRuntimeError, match="reached its output token limit"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


def test_time_limited_output_without_eos_is_rejected_and_lock_is_released(monkeypatch):
    processor, model, _, _, _ = install_fake_runtime_modules(
        monkeypatch,
        generate_action=lambda inputs: FakeTensor([[*inputs["input_ids"].rows[0], 92]]),
    )
    runtime = TransformersRuntime(TransformersRuntimeConfig(
        device="cpu",
        max_time_seconds=120,
    ))
    document = StatementDocument((StatementPage(1, PAGE_IMAGE),))

    with pytest.raises(TransformersRuntimeError, match="without EOS.*120-second"):
        runtime.generate(document, "prompt")
    assert processor.decoded_tokens is None
    assert model.generate_calls[0]["max_time"] == 120
    model.generate_action = None
    assert runtime.generate(document, "prompt") == '{"balances":[]}'


@pytest.mark.parametrize("eos_token_ids", [91, [90, 91], (90, 91)])
def test_complete_eos_response_is_accepted(monkeypatch, eos_token_ids):
    _, model, _, _, _ = install_fake_runtime_modules(monkeypatch)
    model.generation_config.eos_token_id = eos_token_ids
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    assert runtime.generate(
        StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt",
    ) == '{"balances":[]}'


@pytest.mark.parametrize("eos_token_ids", [None, [], "91", [None]])
def test_missing_or_invalid_eos_configuration_prevents_generation(monkeypatch, eos_token_ids):
    _, model, _, _, _ = install_fake_runtime_modules(monkeypatch)
    model.generation_config.eos_token_id = eos_token_ids
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(TransformersRuntimeError, match="configure EOS token IDs"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")
    assert model.generate_calls == []


def test_no_generated_tokens_is_rejected_without_decoding(monkeypatch):
    processor, _, _, _, _ = install_fake_runtime_modules(monkeypatch, output_token_count=0)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(TransformersRuntimeError, match="without EOS"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")
    assert processor.decoded_tokens is None


def test_out_of_memory_error_has_recovery_guidance(monkeypatch):
    _, _, _, _, out_of_memory_type = install_fake_runtime_modules(
        monkeypatch,
        generate_action=lambda inputs: (_ for _ in ()).throw(
            out_of_memory_type("device out of memory")
        ),
    )
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(TransformersRuntimeError, match="ran out of device memory"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


@pytest.mark.parametrize("allocation_stage", ["processor", "device_transfer"])
def test_preparation_oom_is_actionable_and_releases_lock(monkeypatch, allocation_stage):
    processor, _, _, _, out_of_memory_type = install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    document = StatementDocument((StatementPage(1, PAGE_IMAGE),))

    def fail_allocation(*arguments, **keywords):
        raise out_of_memory_type("device out of memory")

    with monkeypatch.context() as allocation_patch:
        if allocation_stage == "processor":
            allocation_patch.setattr(processor, "apply_chat_template", fail_allocation)
        else:
            allocation_patch.setattr(FakeBatch, "to", fail_allocation)
        with pytest.raises(
            TransformersRuntimeError, match="memory while preparing or processing",
        ) as error_info:
            runtime.generate(document, "prompt")
        assert error_info.value.__cause__.__class__ is out_of_memory_type

    assert runtime.generate(document, "prompt") == '{"balances":[]}'


def test_non_oom_generation_runtime_errors_are_preserved(monkeypatch):
    install_fake_runtime_modules(
        monkeypatch,
        generate_action=lambda inputs: (_ for _ in ()).throw(
            RuntimeError("unsupported model operation")
        ),
    )
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(RuntimeError, match="unsupported model operation"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


@pytest.mark.parametrize(("output_shape", "error_message"), [
    ((2, 4), "invalid generation shape"),
    ((1, 1), "truncated prompt"),
])
def test_invalid_generated_token_shapes_are_rejected(monkeypatch, output_shape, error_message):
    install_fake_runtime_modules(
        monkeypatch,
        generate_action=lambda inputs: SimpleNamespace(shape=output_shape),
    )
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(TransformersRuntimeError, match=error_message):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


def test_empty_model_response_is_rejected(monkeypatch):
    install_fake_runtime_modules(monkeypatch, decoded_text="  ")
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(TransformersRuntimeError, match="empty response"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), "prompt")


def test_serialized_generation_fails_fast_when_model_is_busy(monkeypatch):
    generation_started = Event()
    release_generation = Event()

    def blocking_generation(inputs):
        generation_started.set()
        assert release_generation.wait(timeout=2)
        input_ids = inputs["input_ids"]
        return FakeTensor([[*input_ids.rows[0], 91]])

    install_fake_runtime_modules(monkeypatch, generate_action=blocking_generation)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    document = StatementDocument((StatementPage(1, PAGE_IMAGE),))
    first_results = []

    def generate_first_response():
        first_results.append(runtime.generate(document, "prompt"))

    generation_thread = Thread(target=generate_first_response)
    generation_thread.start()
    assert generation_started.wait(timeout=2)
    try:
        with pytest.raises(TransformersRuntimeError, match="already generating"):
            runtime.generate(document, "prompt")
    finally:
        release_generation.set()
        generation_thread.join(timeout=2)

    assert not generation_thread.is_alive()
    assert first_results == ['{"balances":[]}']


@pytest.mark.skipif(Image is None, reason="Pillow is not installed")
def test_multimodal_pages_use_pil_images_and_close_them_after_preprocessing(monkeypatch):
    image_buffer = BytesIO()
    Image.new("RGB", (20, 10), color="white").save(image_buffer, format="PNG")
    image_data = image_buffer.getvalue()
    processor, _, _, _, _ = install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(
        device="cpu",
        max_image_pixels=500,
    ))
    document = StatementDocument((
        StatementPage(1, image_data),
        StatementPage(2, PAGE_IMAGE),
    ))

    runtime.generate(document, "extract")

    message_content = processor.messages[1]["content"]
    image_part = next(part for part in message_content if part["type"] == "image")
    assert image_part["image"].size[0] * image_part["image"].size[1] <= 500
    assert [part["type"] for part in message_content] == ["text", "image", "text", "image"]
    with pytest.raises(ValueError, match="closed"):
        image_part["image"].getpixel((0, 0))


@pytest.mark.skipif(Image is None, reason="Pillow is not installed")
def test_image_only_runtime_input_has_page_labels_but_no_extracted_text(monkeypatch):
    image_buffer = BytesIO()
    with Image.new("RGB", (20, 10), color="white") as image:
        image.save(image_buffer, format="PNG")
    processor, _, _, _, _ = install_fake_runtime_modules(monkeypatch)
    document = StatementDocument((
        StatementPage(1, image_buffer.getvalue()),
        StatementPage(2, image_buffer.getvalue()),
    ))
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    runtime.generate(document, "extract")
    content = processor.messages[1]["content"]
    assert [part["type"] for part in content] == ["text", "image", "text", "image"]
    assert "page 1 image" in content[0]["text"]
    assert "page 2 image" in content[2]["text"]
    assert all("text (untrusted" not in part.get("text", "") for part in content)
    for part in content:
        if part["type"] == "image":
            with pytest.raises(ValueError, match="closed"):
                part["image"].getpixel((0, 0))


@pytest.mark.skipif(Image is None, reason="Pillow is not installed")
def test_runtime_rejects_oversized_image_before_decoding_pixels(monkeypatch):
    image_buffer = BytesIO()
    Image.new("RGB", (100, 50), color="white").save(image_buffer, format="PNG")
    install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(
        device="cpu",
        max_image_pixels=500,
    ))
    document = StatementDocument((StatementPage(1, image_buffer.getvalue()),))

    with pytest.raises(TransformersRuntimeError, match="5000 pixels.*500-pixel limit"):
        runtime.generate(document, "prompt")


@pytest.mark.skipif(Image is None, reason="Pillow is not installed")
def test_unreadable_page_image_fails_without_silent_fallback(monkeypatch):
    install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    document = StatementDocument((StatementPage(1, b"not an image"),))

    with pytest.raises(TransformersRuntimeError, match="unreadable image"):
        runtime.generate(document, "prompt")


@pytest.mark.skipif(Image is None, reason="Pillow is not installed")
def test_previously_loaded_images_close_if_a_later_page_is_invalid(monkeypatch):
    image_buffer = BytesIO()
    Image.new("RGB", (20, 10), color="white").save(image_buffer, format="PNG")
    install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    original_image_loader = page_images.load_bounded_image
    loaded_images = []

    def track_loaded_image(image_bytes, max_image_pixels):
        loaded_image = original_image_loader(image_bytes, max_image_pixels)
        loaded_images.append(loaded_image)
        return loaded_image

    monkeypatch.setattr(page_images, "load_bounded_image", track_loaded_image)
    document = StatementDocument((
        StatementPage(1, image_buffer.getvalue()),
        StatementPage(2, b"not an image"),
    ))

    with pytest.raises(TransformersRuntimeError, match="unreadable image"):
        runtime.generate(document, "prompt")
    assert len(loaded_images) == 1
    with pytest.raises(ValueError, match="closed"):
        loaded_images[0].getpixel((0, 0))


@pytest.mark.skipif(Image is None, reason="Pillow is not installed")
def test_images_close_and_generation_lock_releases_when_preprocessing_fails(monkeypatch):
    processor, _, _, _, _ = install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    document = StatementDocument((StatementPage(1, PAGE_IMAGE),))
    loaded_images = []

    def fail_preprocessing(messages, **options):
        loaded_images.extend(
            part["image"]
            for message in messages for part in message["content"] if part["type"] == "image"
        )
        raise RuntimeError("processor failure")

    with monkeypatch.context() as processor_patch:
        processor_patch.setattr(processor, "apply_chat_template", fail_preprocessing)
        with pytest.raises(RuntimeError, match="processor failure"):
            runtime.generate(document, "prompt")
    assert len(loaded_images) == 1
    with pytest.raises(ValueError, match="closed"):
        loaded_images[0].getpixel((0, 0))
    assert runtime.generate(document, "prompt") == '{"balances":[]}'


def test_runtime_rejects_too_many_visual_pages_before_loading_images(monkeypatch):
    install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))
    document = StatementDocument(tuple(
        StatementPage(page_number, b"image bytes")
        for page_number in range(1, 18)
    ))

    with pytest.raises(TransformersRuntimeError, match="at most 16 page images"):
        runtime.generate(document, "prompt")


def test_runtime_rejects_empty_prompt(monkeypatch):
    install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(ValueError, match="must not be empty"):
        runtime.generate(StatementDocument((StatementPage(1, PAGE_IMAGE),)), " ")


def test_runtime_rejects_values_that_are_not_documents(monkeypatch):
    install_fake_runtime_modules(monkeypatch)
    runtime = TransformersRuntime(TransformersRuntimeConfig(device="cpu"))

    with pytest.raises(ValueError, match="StatementDocument"):
        runtime.generate(cast(StatementDocument, object()), "prompt")
