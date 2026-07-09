"""Deterministic synthetic log fixtures for lg CLI tests."""

from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def tiny_trace_text() -> str:
    return (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 9, in <module>\n'
        "    main()\n"
        '  File "app.py", line 5, in main\n'
        "    obj.version\n"
        "AttributeError: 'NoneType' object has no attribute 'version'\n"
    )


def medium_cicd_text() -> str:
    """~4k chars — MEDIUM route after trace (deterministic CI spam)."""
    line = "INFO: Step docker/build — layer cache miss repo=app/web sha=abc123\n"
    header = (
        "============================= test session starts ==============================\n"
        "collected 12 items\n"
        "FAILED tests/test_api.py::test_health - AssertionError: 503\n"
        "Traceback (most recent call last):\n"
        '  File "tests/test_api.py", line 44, in test_health\n'
        "    assert resp.status_code == 200\n"
        "AssertionError: assert 503 == 200\n"
    )
    body = line * 180
    return header + body


def full_route_synth_text() -> str:
    """~20k raw chars — FULL route (>=10k) after soft clean + trace."""
    kv = "host=192.168.1.42 port=8080 env=prod region=us-east-1 service=api-gateway\n"
    progress = "100%|██████████| 500/500 [01:00<00:00, 8.00it/s]\n"
    json_block = (
        '{"model": "resnet50", "batch_size": 32, "lr": 0.001, '
        '"optimizer": "adam", "epochs": 10, "dataset": "imagenet", '
        '"workers": 4, "pin_memory": true}\n'
    )
    trace = (
        "Traceback (most recent call last):\n"
        '  File "train.py", line 120, in <module>\n'
        "    trainer.fit()\n"
        "RuntimeError: CUDA out of memory\n"
    )
    chunk = (kv + progress + json_block) * 120
    return trace + chunk
