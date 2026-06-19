"""Tests für das reine PresentMon-CSV-Header-Parsing — laufen OHNE PresentMon/GPU."""

from __future__ import annotations

from gpu_efficiency_finder.adapters.presentmon_source import find_frametime_column


def test_finds_ms_between_presents_v1_schema() -> None:
    header = ["Application", "ProcessID", "SwapChainAddress", "MsBetweenPresents"]
    assert find_frametime_column(header) == 3


def test_case_insensitive() -> None:
    assert find_frametime_column(["a", "msBetweenPresents", "b"]) == 1


def test_accepts_frametime_alternative() -> None:
    assert find_frametime_column(["FrameTime", "x"]) == 0


def test_prefers_ms_between_presents_over_frametime() -> None:
    # Wenn beide vorhanden sind, gewinnt die stabile v1-Spalte MsBetweenPresents.
    assert find_frametime_column(["FrameTime", "MsBetweenPresents"]) == 1


def test_no_match_returns_none() -> None:
    assert find_frametime_column(["Application", "ProcessID", "TimeInSeconds"]) is None


def test_empty_header_returns_none() -> None:
    assert find_frametime_column([]) is None
