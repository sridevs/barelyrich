from concurrent.futures import ThreadPoolExecutor
from http.client import RemoteDisconnected
from socket import socketpair
from threading import Event
from unittest.mock import MagicMock

import pytest

from src.inference.cancellation import Cancellation, ExtractionCancelled
from src.inference.ollama_runtime import OllamaRuntime, OllamaRuntimeConfig
from src.inference.progress import InferenceProgress, observe, report_stage
from tests.inference.test_ollama_runtime import document


def test_cancel_is_request_local_and_interrupt_hook_is_removed():
    cancellation = Cancellation()
    interrupt = MagicMock()
    with cancellation.interrupt_with(interrupt):
        cancellation.cancel()
        with pytest.raises(ExtractionCancelled):
            cancellation.check()
    interrupt.assert_called_once()
    cancellation.cancel()
    interrupt.assert_called_once()
    Cancellation().check()


def test_cancel_stops_progress_stages():
    progress = InferenceProgress()
    progress.cancellation.cancel()
    with observe(progress), pytest.raises(ExtractionCancelled):
        report_stage("Generating")


def test_ollama_cancel_interrupts_blocked_request_and_closes_connection(monkeypatch):
    transport, peer = socketpair()
    entered = Event()
    connection = MagicMock()
    connection.sock = transport

    def blocked_response():
        entered.set()
        transport.recv(1)
        raise RemoteDisconnected("cancelled")

    connection.getresponse.side_effect = blocked_response
    monkeypatch.setattr(
        "src.inference.ollama_runtime.HTTPConnection",
        lambda *arguments, **keywords: connection,
    )
    progress = InferenceProgress()

    def generate_response():
        with observe(progress):
            return OllamaRuntime(OllamaRuntimeConfig()).generate(document(), "Extract")

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(generate_response)
            assert entered.wait(3)
            progress.cancellation.cancel()
            with pytest.raises(ExtractionCancelled):
                future.result(timeout=3)
        connection.close.assert_called_once()
    finally:
        transport.close()
        peer.close()
