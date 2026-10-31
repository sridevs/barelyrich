import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from src.inference import generation_progress
from src.inference import progress as progress_module
from src.inference.generation_progress import LIVE_OUTPUT_CHARACTERS, GenerationProgress
from src.inference.progress import (
    InferenceProgress,
    current_progress,
    observe,
    report_stage,
)


def test_chunks_measure_first_token_live_rate_and_bounded_text(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(generation_progress, "perf_counter", lambda: now[0])
    state = GenerationProgress(10.0, None, generated_tokens=None)
    now[0] = 13.0
    state = state.with_chunk("{")
    assert state.first_token_seconds == 3
    now[0] = 14.0
    state = state.with_chunk("b" * LIVE_OUTPUT_CHARACTERS)
    assert state.text == "b" * LIVE_OUTPUT_CHARACTERS
    assert state.characters_per_second == LIVE_OUTPUT_CHARACTERS
    assert state.tokens_per_second == 0
    final = replace(state, generated_tokens=3).finish(eos=True)
    assert final.finished and final.eos
    assert final.tokens_per_second == 2


def test_waiting_generation_reports_no_rates():
    state = GenerationProgress(0.0, None).finish()
    assert state.first_token_seconds is None
    assert state.characters_per_second == 0
    assert state.tokens_per_second == 0
    assert not state.eos


def test_new_generation_replaces_state_and_keeps_stage_timings(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(progress_module, "perf_counter", lambda: now[0])
    progress = InferenceProgress()
    with observe(progress):
        now[0] = 2
        report_stage("Loading model")
        now[0] = 5
        report_stage("Generating response")
        progress.generation(GenerationProgress(0.0, 100).with_chunk("a"))
        progress.generation(GenerationProgress(0.0, 200))
    state = progress.snapshot()
    assert state.generation.input_tokens == 200
    assert state.generation.text == ""
    assert state.timings == (("Preparing extraction", 2), ("Loading model", 3))


def test_context_is_isolated_and_propagates_to_async_worker():
    async def get_in_worker():
        return await asyncio.to_thread(current_progress)

    def request():
        progress = InferenceProgress()
        with observe(progress):
            assert asyncio.run(get_in_worker()) is progress
            report_stage("Own request")
        assert current_progress() is None
        return progress

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: request(), range(2)))
    assert first is not second
    assert current_progress() is None
    report_stage("No observer")


def test_observer_resets_after_failure():
    with pytest.raises(ValueError), observe(InferenceProgress()):
        raise ValueError("failure")
    assert current_progress() is None
