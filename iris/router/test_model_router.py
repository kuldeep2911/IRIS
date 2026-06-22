"""Unit tests for the model router — pure, no network.

Verifies: classification heuristics, model-id mapping, batch flag, and that the
cheapest-capable rule holds (greetings -> Flash-Lite, work -> Flash, complex ->
Pro). Run: ``python -m pytest iris/router/test_model_router.py -q``.
"""

from __future__ import annotations

from iris.router.model_router import (
    MODEL_MAP,
    ModelChoice,
    RequestClass,
    classify,
    model_for,
)


def test_every_class_maps_to_a_choice():
    for rc in RequestClass:
        choice = model_for(rc)
        assert isinstance(choice, ModelChoice)
        assert choice.model
        assert choice.max_output_tokens > 0


def test_model_ids_match_the_locked_strategy():
    assert model_for(RequestClass.TRIVIAL).model == "gemini-2.5-flash-lite"
    assert model_for(RequestClass.SIMPLE).model == "gemini-2.5-flash-lite"
    assert model_for(RequestClass.STANDARD).model == "gemini-2.5-flash"
    assert model_for(RequestClass.HARD).model == "gemini-3.1-pro"
    assert model_for(RequestClass.LONG_CONTEXT).model == "gemini-3.1-pro"
    assert model_for(RequestClass.BACKGROUND).model == "gemini-2.5-flash"


def test_background_uses_batch():
    assert model_for(RequestClass.BACKGROUND).use_batch is True
    assert model_for(RequestClass.STANDARD).use_batch is False


def test_greetings_are_trivial():
    for greeting in ("hi", "hello", "hey IRIS", "thanks!", "ok", "good morning"):
        assert classify(greeting) == RequestClass.TRIVIAL


def test_short_factual_question_is_simple():
    assert classify("what is the capital of France?") == RequestClass.SIMPLE
    assert classify("who won the 2018 world cup?") == RequestClass.SIMPLE


def test_real_tasks_are_standard():
    assert classify("draft a reply to the latest email from Sam") == RequestClass.STANDARD
    assert classify("search the web and save a summary to notes.txt") == RequestClass.STANDARD
    assert classify("schedule a dentist appointment for Friday 3pm") == RequestClass.STANDARD


def test_complex_requests_are_hard():
    assert classify("design a multi-tenant architecture for this system") == RequestClass.HARD
    assert classify("build a small React landing page and deploy it to a static host") == (
        RequestClass.HARD
    )


def test_large_context_is_long_context():
    assert classify("analyse this", context_token_estimate=250_000) == RequestClass.LONG_CONTEXT


def test_explicit_force_wins():
    assert classify("hi", force=RequestClass.BACKGROUND) == RequestClass.BACKGROUND
    assert classify("design a system", force="SIMPLE") == RequestClass.SIMPLE
    # An unknown force string is ignored (falls through to the heuristic).
    assert classify("hi", force="not-a-class") == RequestClass.TRIVIAL
