"""Coordinate local text/vision preprocessing, generation and response decoding."""


import logging
from contextlib import contextmanager
from typing import Any

from src.log_messages import error as error_messages
from src.log_messages import info
from src.inference import model_loader, page_images
from src.inference.configuration import TransformersRuntimeConfig
from src.inference.errors import TransformersRuntimeError
from src.inference.loaded_model import LoadedModel
from src.models.statements.statement_document import StatementDocument


LOGGER = logging.getLogger(__name__)


class TransformersRuntime:
    """Run a local text or vision model with safely shared cached weights."""

    def __init__(self, configuration: TransformersRuntimeConfig | None = None):
        if configuration is not None and not isinstance(configuration, TransformersRuntimeConfig):
            raise ValueError(error_messages.INVALID_RUNTIME_CONFIGURATION)
        self._configuration = configuration or TransformersRuntimeConfig()

    @property
    def configuration(self) -> TransformersRuntimeConfig:
        return self._configuration

    @classmethod
    def from_environment(cls, *, model_name: str | None = None) -> "TransformersRuntime":
        return cls(TransformersRuntimeConfig.from_environment(model_name=model_name))

    def generate(self, document: StatementDocument, prompt: str) -> str:
        self._validate_request(document, prompt)
        LOGGER.info(
            info.MODEL_LOADING,
            self._configuration.model_kind, self._configuration.model_name,
        )
        loaded = model_loader.get_loaded_model(self._configuration)
        with self._generation_session(loaded):
            LOGGER.info(info.MODEL_INPUT_PREPARATION)
            inputs = self._prepare_inputs(loaded, document, prompt)
            LOGGER.info(
                info.TOKEN_GENERATION,
                self._configuration.model_kind, loaded.model.device,
                int(inputs["input_ids"].shape[-1]),
            )
            return self._generate_response(loaded, inputs)

    def _validate_request(self, document: StatementDocument, prompt: str) -> None:
        if not isinstance(document, StatementDocument):
            raise ValueError(error_messages.STATEMENT_DOCUMENT_REQUIRED)
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(error_messages.THE_STATEMENT_EXTRACTION_PROMPT_MUST_NOT_BE_EMPTY)
        if self._configuration.model_kind == "text" and not document.text_only:
            raise ValueError(error_messages.THE_TEXT_MODEL_REQUIRES_EXTRACTED_TEXT_NOT_PAGE_IMAGES)

    @contextmanager
    def _generation_session(self, loaded: LoadedModel):
        if not loaded.generation_lock.acquire(blocking=False):
            raise TransformersRuntimeError(
                error_messages.MODEL_GENERATION_BUSY
            )
        try:
            yield
        except RuntimeError as error:
            self._require_device_memory(error, loaded)
            raise
        finally:
            loaded.generation_lock.release()

    @staticmethod
    def _require_device_memory(error: RuntimeError, loaded: LoadedModel) -> None:
        if model_loader.is_out_of_memory(error, loaded.torch):
            raise TransformersRuntimeError(
                error_messages.MODEL_GENERATION_OUT_OF_MEMORY
            ) from error

    def _prepare_inputs(
        self, loaded: LoadedModel, document: StatementDocument, prompt: str,
    ) -> Any:
        with page_images.page_content(document, self._configuration.max_image_pixels) as content:
            messages = self._processor_messages(content, prompt)
            inputs = loaded.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
        self._require_input_budget(int(inputs["input_ids"].shape[-1]))
        inputs.pop("token_type_ids", None)
        return inputs.to(loaded.model.device)

    def _processor_messages(
        self, content: list[dict[str, Any]], prompt: str,
    ) -> list[dict[str, Any]]:
        messages = self._messages(content, prompt)
        if self._configuration.model_kind == "text":
            return [
                {"role": message["role"], "content": "\n".join(
                    item["text"] for item in message["content"]
                )}
                for message in messages
            ]
        return messages

    def _require_input_budget(self, input_token_count: int) -> None:
        if input_token_count > self._configuration.max_input_tokens:
            raise TransformersRuntimeError(
                error_messages.STATEMENT_INPUT_TOKEN_LIMIT.format(input_token_count=input_token_count, max_input_tokens=self._configuration.max_input_tokens)
            )

    @staticmethod
    def _messages(
        content: list[dict[str, Any]], prompt: str,
    ) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": [{"type": "text", "text": prompt}]},
            {"role": "user", "content": content},
        ]

    def _generate_response(self, loaded: LoadedModel, inputs: Any) -> str:
        eos_token_ids = self._eos_token_ids(loaded)
        input_token_count = int(inputs["input_ids"].shape[-1])
        with loaded.torch.inference_mode():
            generated_ids = loaded.model.generate(
                **inputs,
                max_new_tokens=self._configuration.max_new_tokens,
                max_time=self._configuration.max_time_seconds,
                do_sample=False,
            )
        self._require_complete_generation(generated_ids, input_token_count, eos_token_ids)
        return self._decode_response(loaded, generated_ids[:, input_token_count:])

    @staticmethod
    def _decode_response(loaded: LoadedModel, generated_ids: Any) -> str:
        decoded = loaded.processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        if len(decoded) != 1 or not decoded[0].strip():
            raise TransformersRuntimeError(error_messages.THE_LOCAL_MODEL_RETURNED_AN_EMPTY_RESPONSE)
        return decoded[0]

    @staticmethod
    def _eos_token_ids(loaded: LoadedModel) -> list[int] | tuple[int, ...]:
        token_ids = loaded.model.generation_config.eos_token_id
        if type(token_ids) is int:
            return [token_ids]
        if (
            not isinstance(token_ids, (list, tuple))
            or not token_ids
            or any(type(token_id) is not int for token_id in token_ids)
        ):
            raise TransformersRuntimeError(
                error_messages.MODEL_EOS_CONFIGURATION_REQUIRED
            )
        return token_ids

    def _require_complete_generation(
        self, generated_ids: Any, input_token_count: int, eos_token_ids: list[int] | tuple[int, ...],
    ) -> None:
        generated_token_count = self._generated_token_count(generated_ids, input_token_count)
        if generated_token_count >= self._configuration.max_new_tokens:
            raise TransformersRuntimeError(
                error_messages.MODEL_OUTPUT_TOKEN_LIMIT
            )
        if generated_token_count == 0 or int(generated_ids[0, -1].item()) not in eos_token_ids:
            raise TransformersRuntimeError(
                error_messages.MODEL_RESPONSE_MISSING_EOS.format(max_time_seconds=self._configuration.max_time_seconds)
            )

    @staticmethod
    def _generated_token_count(generated_ids: Any, input_token_count: int) -> int:
        if len(generated_ids.shape) != 2 or generated_ids.shape[0] != 1:
            raise TransformersRuntimeError(error_messages.THE_LOCAL_MODEL_RETURNED_AN_INVALID_GENERATION_SHAPE)
        generated_token_count = int(generated_ids.shape[-1]) - input_token_count
        if generated_token_count < 0:
            raise TransformersRuntimeError(error_messages.THE_LOCAL_MODEL_RETURNED_A_TRUNCATED_PROMPT)
        return generated_token_count
