"""Render request-local diagnostics while inference runs off the Streamlit thread."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextvars import copy_context
from dataclasses import replace
from functools import partial
from time import perf_counter

import streamlit as st

from src.inference.dto.progress_snapshot import ProgressSnapshot
from src.inference.generation_progress import GenerationProgress
from src.inference.progress import InferenceProgress, observe
from src.models.statements.statement_extraction import StatementExtraction
from src.ui import ui_text


class _ProgressDisplay:
    def __init__(self, started_at: float):
        self._started_at = started_at
        self._elapsed = st.empty()
        self._stages = st.empty()
        self._metrics = st.empty()
        self._output = st.empty()
        self._previous_text: str | None = None

    def render(self, snapshot: ProgressSnapshot) -> None:
        self._render_elapsed(snapshot)
        self._stages.text("\n".join(
            f"{stage}: {seconds:.2f}s" for stage, seconds in snapshot.timings
        ))
        if snapshot.generation:
            self._render_generation(snapshot)

    def _render_elapsed(self, snapshot: ProgressSnapshot) -> None:
        now = perf_counter()
        self._elapsed.text(
            f"{snapshot.stage} | Stage: {now - snapshot.stage_started_at:.1f}s | "
            f"Total: {now - self._started_at:.1f}s"
        )

    def _render_generation(self, snapshot: ProgressSnapshot) -> None:
        generation = snapshot.generation
        if generation is None:
            return
        now = perf_counter()
        duration = generation.elapsed_seconds if generation.finished else now - generation.started_at
        self._render_metrics(generation, duration)
        self._render_output(generation.text)

    def _render_metrics(self, generation: GenerationProgress, duration: float) -> None:
        first = generation.first_token_seconds
        first_label = "waiting" if first is None else f"{first:.2f}s"
        live = replace(generation, elapsed_seconds=duration)
        input_count = "pending" if generation.input_tokens is None else f"{generation.input_tokens:,}"
        output_count, rate_label = self._output_metrics(generation, live)
        eos_label = f" | EOS: {'yes' if generation.eos else 'no'}" if generation.finished else ""
        self._metrics.text(
            f"Input: {input_count} tokens | Generated: {output_count} | "
            f"Time to first token: {first_label} | Decode: {rate_label} | "
            f"Generation: {duration:.1f}s{eos_label}"
        )

    @staticmethod
    def _output_metrics(
        generation: GenerationProgress, live: GenerationProgress,
    ) -> tuple[str, str]:
        if generation.generated_tokens is None:
            return (
                f"{generation.generated_characters:,} characters (tokens pending)",
                f"{live.characters_per_second:.2f} chars/s (live)",
            )
        return (
            f"{generation.generated_tokens:,} tokens",
            f"{live.tokens_per_second:.2f} tokens/s",
        )

    def _render_output(self, text: str) -> None:
        if text == self._previous_text:
            return
        self._output.code(
            text or ui_text.WAITING_FOR_OUTPUT, language="json", height=250, wrap_lines=True,
        )
        self._previous_text = text


def preview_with_progress(
    operation: Callable[[], StatementExtraction], label: str,
    *, on_cancel: Callable[[], None] | None = None,
) -> StatementExtraction:
    progress = InferenceProgress()
    st.session_state["active_statement_progress"] = progress
    started_at = perf_counter()
    with st.status(label, expanded=True) as status:
        display = _create_progress_display(progress, label, on_cancel, started_at)
        return _run_with_progress(operation, progress, display, status, on_cancel)


def _create_progress_display(
    progress: InferenceProgress, label: str, on_cancel: Callable[[], None] | None,
    started_at: float,
) -> _ProgressDisplay:
    st.caption(ui_text.LIVE_OUTPUT_HELP)
    st.empty().button(
        ui_text.STOP_EXTRACTION, key=f"stop_statement_extraction_{label}",
        on_click=partial(_cancel_inference, progress, on_cancel),
        icon=":material/stop:", type="primary",
    )
    return _ProgressDisplay(started_at)


def _cancel_inference(
    progress: InferenceProgress, on_cancel: Callable[[], None] | None,
) -> None:
    progress.cancellation.cancel()
    if on_cancel:
        on_cancel()


def _run_with_progress(
    operation: Callable[[], StatementExtraction], progress: InferenceProgress,
    display: _ProgressDisplay, status, on_cancel: Callable[[], None] | None,
) -> StatementExtraction:
    display.render(progress.snapshot())
    executor = ThreadPoolExecutor(max_workers=1)
    with observe(progress):
        future = _submit_operation(executor, operation)
        try:
            return _wait_for_result(future, progress, display)
        finally:
            _finish_operation(future, progress, display, status, executor, on_cancel)


def _submit_operation(
    executor: ThreadPoolExecutor, operation: Callable[[], StatementExtraction],
) -> Future:
    context = copy_context()
    return executor.submit(context.run, operation)


def _wait_for_result(
    future: Future, progress: InferenceProgress, display: _ProgressDisplay,
) -> StatementExtraction:
    while not future.done():
        progress.cancellation.check()
        wait([future], timeout=0.2)
        display.render(progress.snapshot())
    result = future.result()
    progress.cancellation.check()
    return result


def _finish_operation(
    future: Future, progress: InferenceProgress, display: _ProgressDisplay, status,
    executor: ThreadPoolExecutor, on_cancel: Callable[[], None] | None,
) -> None:
    progress.cancellation.cancel()
    if not future.done() and on_cancel:
        on_cancel()
    executor.shutdown(wait=False, cancel_futures=True)
    _clear_active_progress(progress)
    display.render(progress.snapshot())
    _update_status(status, future)


def _clear_active_progress(progress: InferenceProgress) -> None:
    if st.session_state.get("active_statement_progress") is progress:
        st.session_state.pop("active_statement_progress", None)


def _update_status(status, future: Future) -> None:
    successful = future.done() and future.exception() is None
    status.update(
        label=ui_text.EXTRACTION_READY if successful else ui_text.EXTRACTION_FAILED,
        state="complete" if successful else "error",
    )
