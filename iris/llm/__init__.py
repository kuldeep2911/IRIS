"""LLM adapters — provider-agnostic interface; swap provider in ONE file.

get_llm() factory (STEP 0.3) returns the concrete client so callers never import
it directly (GOLDEN RULE #10).
"""
