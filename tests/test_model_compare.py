"""Tests for model_compare.py — unit + integration with mocked AsyncOpenAI."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import model_compare as mc


# ── Helpers ──────────────────────────────────────────────────────────

def _mock_chat_response(content: str, prompt_tokens: int = 10, completion_tokens: int = 5):
    """Build a mock OpenAI chat completion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


# ── Config Tests ─────────────────────────────────────────────────────

class TestCompareConfig:
    def test_from_env_defaults(self):
        config = mc.CompareConfig.from_env("test query")
        assert config.query == "test query"
        assert config.models == ["deepseek-chat", "gpt-4o"]
        assert config.mode == "judge"
        assert config.timeout == 120.0

    def test_models_override(self):
        config = mc.CompareConfig.from_env("q", models_override=["a", "b"])
        assert config.models == ["a", "b"]

    def test_mode_override(self):
        config = mc.CompareConfig.from_env("q", mode_override="vote")
        assert config.mode == "vote"

    def test_judge_override(self):
        config = mc.CompareConfig.from_env("q", judge_override="custom-judge")
        assert config.judge_model == "custom-judge"

    def test_env_models(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_MODELS", "m1,m2,m3")
        config = mc.CompareConfig.from_env("q")
        assert config.models == ["m1", "m2", "m3"]

    def test_env_mode(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_MODE", "vote")
        config = mc.CompareConfig.from_env("q")
        assert config.mode == "vote"

    def test_env_timeout(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_TIMEOUT", "30")
        config = mc.CompareConfig.from_env("q")
        assert config.timeout == 30.0

    def test_env_temperature(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_TEMPERATURE", "0.3")
        config = mc.CompareConfig.from_env("q")
        assert config.temperature == 0.3

    def test_env_max_tokens(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_MAX_TOKENS", "512")
        config = mc.CompareConfig.from_env("q")
        assert config.max_tokens == 512

    def test_env_api_keys_json(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"m1":"sk-a","m2":"sk-b"}')
        config = mc.CompareConfig.from_env("q")
        assert config.api_keys == {"m1": "sk-a", "m2": "sk-b"}

    def test_env_api_keys_invalid_json(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", "not-json")
        config = mc.CompareConfig.from_env("q")
        assert config.api_keys == {}

    def test_env_base_urls_json(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_BASE_URLS", '{"m1":"http://localhost:8000"}')
        config = mc.CompareConfig.from_env("q")
        assert config.api_base_urls == {"m1": "http://localhost:8000"}

    def test_resolve_api_key_direct(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"exact-model":"sk-direct"}')
        config = mc.CompareConfig.from_env("q")
        assert config.resolve_api_key("exact-model") == "sk-direct"

    def test_resolve_api_key_deepseek(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
        config = mc.CompareConfig.from_env("q")
        assert config.resolve_api_key("deepseek-chat") == "sk-ds"

    def test_resolve_api_key_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
        config = mc.CompareConfig.from_env("q")
        assert config.resolve_api_key("gpt-4o") == "sk-oai"

    def test_resolve_api_key_none(self):
        # Clear relevant env vars
        for key in list(os.environ):
            if key.endswith("_API_KEY"):
                os.environ.pop(key, None)
        config = mc.CompareConfig.from_env("q")
        assert config.resolve_api_key("unknown-model") is None

    def test_resolve_base_url_exact(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_BASE_URLS", '{"exact-model":"http://custom:8000"}')
        config = mc.CompareConfig.from_env("q")
        assert config.resolve_base_url("exact-model") == "http://custom:8000"

    def test_resolve_base_url_deepseek(self):
        config = mc.CompareConfig.from_env("q")
        assert "deepseek.com" in config.resolve_base_url("deepseek-chat")

    def test_resolve_base_url_openai(self):
        config = mc.CompareConfig.from_env("q")
        assert "openai.com" in config.resolve_base_url("gpt-4o")

    def test_show_config(self):
        config = mc.CompareConfig.from_env("test")
        output = config.show()
        assert "models:" in output
        assert "judge_model:" in output
        assert "api_keys:" in output


# ── CLI Parser Tests ─────────────────────────────────────────────────

class TestParseArgs:
    def test_positional_query(self):
        args = mc.parse_args(["what is 2+2"])
        assert args["query"] == "what is 2+2"

    def test_multi_word_query(self):
        args = mc.parse_args(["what", "is", "the", "capital"])
        assert args["query"] == "what is the capital"

    def test_models_flag(self):
        args = mc.parse_args(["--models", "a,b,c", "query"])
        assert args["models"] == ["a", "b", "c"]

    def test_mode_flag(self):
        args = mc.parse_args(["--mode", "vote", "query"])
        assert args["mode"] == "vote"

    def test_judge_flag(self):
        args = mc.parse_args(["--judge", "custom", "query"])
        assert args["judge"] == "custom"

    def test_stdin_flag(self):
        args = mc.parse_args(["--stdin", "query"])
        assert args["stdin"] is True

    def test_show_config_flag(self):
        args = mc.parse_args(["--show-config"])
        assert args["show_config"] is True

    def test_help_exits(self):
        with pytest.raises(SystemExit):
            mc.parse_args(["--help"])

    def test_no_query(self):
        args = mc.parse_args([])
        assert args["query"] is None


# ── ModelComparator Tests ────────────────────────────────────────────

@pytest.mark.asyncio
class TestModelComparator:
    async def test_query_model_success(self):
        config = mc.CompareConfig.from_env("test query")
        comparator = mc.ModelComparator(config)

        mock_client = MagicMock()
        mock_resp = _mock_chat_response("Paris", 10, 5)
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await comparator.query_model("test-model", mock_client)
        assert result.model == "test-model"
        assert result.content == "Paris"
        assert result.error is None
        assert result.tokens_prompt == 10
        assert result.tokens_completion == 5
        assert result.elapsed_ms > 0

    async def test_query_model_timeout(self):
        config = mc.CompareConfig.from_env("test query")
        config.timeout = 0.001  # Force timeout
        comparator = mc.ModelComparator(config)

        mock_client = MagicMock()
        async def slow_response(**kwargs):
            await asyncio.sleep(10)
        mock_client.chat.completions.create = AsyncMock(side_effect=slow_response)

        result = await comparator.query_model("test-model", mock_client)
        assert result.error is not None
        assert "Timeout" in result.error

    async def test_query_model_api_error(self):
        config = mc.CompareConfig.from_env("test query")
        comparator = mc.ModelComparator(config)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API Error")
        )

        result = await comparator.query_model("test-model", mock_client)
        assert result.error is not None
        assert "API Error" in result.error

    async def test_build_clients_skips_no_key(self):
        config = mc.CompareConfig.from_env("q", models_override=["unknown-model"])
        comparator = mc.ModelComparator(config)
        clients = comparator._build_clients()
        assert clients["unknown-model"] is None

    async def test_run_all_fail(self):
        config = mc.CompareConfig.from_env("q")
        config.api_keys = {"m1": "sk-test"}  # Only one key, but model list is different
        config.models = ["no-key-model"]
        comparator = mc.ModelComparator(config)

        result = await comparator.run()
        assert result.winner is None
        assert len(result.errors) > 0

    async def test_run_one_success_one_fail(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"m1":"sk-test","m2":"sk-test2"}')
        config = mc.CompareConfig.from_env("q", models_override=["m1", "m2"])
        config.timeout = 5.0
        comparator = mc.ModelComparator(config)

        with patch("model_compare.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock()
            mock_client.chat.completions.create.side_effect = [
                _mock_chat_response("Response from m1", 10, 5),
                Exception("m2 network error"),
            ]
            mock_cls.return_value = mock_client

            result = await comparator.run()
            assert len(result.responses) == 2
            successful = [r for r in result.responses if not r.get("error")]
            failed = [r for r in result.responses if r.get("error")]
            assert len(successful) == 1
            assert len(failed) == 1
            assert "m2" in result.errors[0] if result.errors else False

    async def test_run_success_with_judge(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"m1":"sk-test","m2":"sk-test2"}')
        config = mc.CompareConfig.from_env("q", models_override=["m1", "m2"],
                                           judge_override="m1")
        config.timeout = 5.0
        comparator = mc.ModelComparator(config)

        with patch("model_compare.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()

            # First two calls: m1 and m2 responses
            # Third call: judge (m1) evaluating
            mock_client.chat.completions.create = AsyncMock()
            mock_client.chat.completions.create.side_effect = [
                _mock_chat_response("Answer from m1", 10, 5),
                _mock_chat_response("Answer from m2", 10, 5),
                _mock_chat_response(
                    json.dumps({
                        "winner": "m1",
                        "justification": "m1 was more concise.",
                        "runner_up": "m2",
                        "scores": {
                            "m1": {"correctness": 10, "completeness": 9, "clarity": 10, "conciseness": 10, "helpfulness": 9},
                            "m2": {"correctness": 10, "completeness": 9, "clarity": 8, "conciseness": 9, "helpfulness": 9},
                        },
                    })
                ),
            ]
            mock_cls.return_value = mock_client

            result = await comparator.run()
            assert result.winner == "m1"
            assert "more concise" in (result.justification or "")
            assert result.runner_up == "m2"
            assert "m1" in result.scores
            assert result.scores["m1"]["correctness"] == 10

    async def test_run_judge_returns_non_json(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"m1":"sk-test","m2":"sk-test2"}')
        config = mc.CompareConfig.from_env("q", models_override=["m1", "m2"],
                                           judge_override="m1")
        config.timeout = 5.0
        comparator = mc.ModelComparator(config)

        with patch("model_compare.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock()
            mock_client.chat.completions.create.side_effect = [
                _mock_chat_response("Answer from m1", 10, 5),
                _mock_chat_response("Answer from m2", 10, 5),
                _mock_chat_response("I think m1 is the best answer because it is clearer."),
            ]
            mock_cls.return_value = mock_client

            result = await comparator.run()
            assert result.winner == "m1"  # Regex fallback found "m1" in text
            assert "non-JSON" in (result.justification or "") or "regex" in (result.justification or "").lower()

    async def test_run_judge_returns_json_in_fence(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"m1":"sk-test","m2":"sk-test2"}')
        config = mc.CompareConfig.from_env("q", models_override=["m1", "m2"],
                                           judge_override="m1")
        config.timeout = 5.0
        comparator = mc.ModelComparator(config)

        with patch("model_compare.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            judge_json = json.dumps({"winner": "m2", "justification": "Better structure.", "scores": {}})
            mock_client.chat.completions.create = AsyncMock()
            mock_client.chat.completions.create.side_effect = [
                _mock_chat_response("Answer from m1"),
                _mock_chat_response("Answer from m2"),
                _mock_chat_response(f"```json\n{judge_json}\n```"),
            ]
            mock_cls.return_value = mock_client

            result = await comparator.run()
            assert result.winner == "m2"

    async def test_run_vote_mode(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"m1":"sk-test","m2":"sk-test2"}')
        config = mc.CompareConfig.from_env("q", models_override=["m1", "m2"],
                                           mode_override="vote")
        config.timeout = 5.0
        comparator = mc.ModelComparator(config)

        with patch("model_compare.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock()
            mock_client.chat.completions.create.side_effect = [
                # Model responses
                _mock_chat_response("Answer from m1"),
                _mock_chat_response("Answer from m2"),
                # Votes: m1 votes B, m2 votes A
                _mock_chat_response("B"),
                _mock_chat_response("A"),
            ]
            mock_cls.return_value = mock_client

            result = await comparator.run()
            assert result.mode == "vote"
            assert result.winner is not None

    async def test_run_judge_winner_not_in_list(self, monkeypatch):
        """Judge picks a model not in the queried list → fallback to first model."""
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"m1":"sk-test","m2":"sk-test2"}')
        config = mc.CompareConfig.from_env("q", models_override=["m1", "m2"],
                                           judge_override="m1")
        config.timeout = 5.0
        comparator = mc.ModelComparator(config)

        with patch("model_compare.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock()
            mock_client.chat.completions.create.side_effect = [
                _mock_chat_response("Answer from m1"),
                _mock_chat_response("Answer from m2"),
                _mock_chat_response(json.dumps({"winner": "totally-unknown-model", "justification": "I pick this.", "scores": {}})),
            ]
            mock_cls.return_value = mock_client

            result = await comparator.run()
            assert result.winner == "m1"  # Fell back

    async def test_query_model_prediction_exception_handling(self):
        """Verify unexpected exceptions during model query are caught."""
        config = mc.CompareConfig.from_env("test query")
        comparator = mc.ModelComparator(config)
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("mock error"))
        result = await comparator.query_model("test-model", mock_client)
        assert result.error is not None
        assert "RuntimeError" in result.error


# ── Judge Prompt Tests ───────────────────────────────────────────────

class TestJudgePrompt:
    def test_judge_system_prompt_contains_criteria(self):
        assert "correctness" in mc.JUDGE_SYSTEM_PROMPT
        assert "completeness" in mc.JUDGE_SYSTEM_PROMPT
        assert "clarity" in mc.JUDGE_SYSTEM_PROMPT
        assert "conciseness" in mc.JUDGE_SYSTEM_PROMPT
        assert "helpfulness" in mc.JUDGE_SYSTEM_PROMPT

    def test_judge_system_prompt_requires_json(self):
        assert '"winner"' in mc.JUDGE_SYSTEM_PROMPT
        assert '"justification"' in mc.JUDGE_SYSTEM_PROMPT
        assert '"scores"' in mc.JUDGE_SYSTEM_PROMPT

    def test_build_judge_messages(self):
        config = mc.CompareConfig.from_env("What is Python?")
        comparator = mc.ModelComparator(config)
        responses = [
            mc.ModelResponse(model="m1", content="Python is a language."),
            mc.ModelResponse(model="m2", content="Python is a snake."),
        ]
        msgs = comparator._build_judge_messages(responses)
        assert msgs[0]["role"] == "system"
        assert "What is Python?" in msgs[1]["content"]
        assert "m1" in msgs[1]["content"]
        assert "m2" in msgs[1]["content"]


# ── Vote Prompt Tests ────────────────────────────────────────────────

class TestVotePrompt:
    def test_vote_system_prompt(self):
        assert "SINGLE BEST" in mc.VOTE_SYSTEM_PROMPT
        assert "letter" in mc.VOTE_SYSTEM_PROMPT.lower()


# ── Output Format Tests ──────────────────────────────────────────────

class TestOutputFormat:
    def test_comparison_result_is_serializable(self):
        result = mc.ComparisonResult(
            query="test",
            mode="judge",
            timestamp="2026-01-01T00:00:00Z",
            models_queried=["m1", "m2"],
            responses=[],
            judge_answer="Свой ответ судьи",
            winner="m1",
            justification="ok",
            runner_up="m2",
            scores={"m1": {"correctness": 10}, "m2": {"correctness": 8}},
            errors=[],
            total_elapsed_ms=100.0,
        )
        json.dumps(result.__dict__)  # Should not raise

    def test_model_response_asdict(self):
        from dataclasses import asdict
        r = mc.ModelResponse(model="m1", content="Hello", elapsed_ms=100.0,
                            tokens_prompt=5, tokens_completion=3)
        d = asdict(r)
        assert d["model"] == "m1"
        assert d["error"] is None

    def test_model_response_with_error_asdict(self):
        from dataclasses import asdict
        r = mc.ModelResponse(model="m1", error="timeout", elapsed_ms=5000.0)
        d = asdict(r)
        assert d["error"] == "timeout"


# ── Provider URL Detection ───────────────────────────────────────────

class TestProviderDetection:
    def test_deepseek_prefix(self):
        assert "deepseek.com" in mc._detect_base_url("deepseek-chat")

    def test_openai_prefix(self):
        assert "openai.com" in mc._detect_base_url("gpt-4o")

    def test_unknown_falls_back_to_openai(self):
        assert "openai.com" in mc._detect_base_url("some-unknown-model")


# ── Edge Cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_models_list(self):
        config = mc.CompareConfig.from_env("q", models_override=[])
        assert config.models == []

    def test_whitespace_in_models_env(self, monkeypatch):
        monkeypatch.setenv("MODEL_COMPARE_MODELS", " m1 , m2 , m3 ")
        config = mc.CompareConfig.from_env("q")
        assert config.models == ["m1", "m2", "m3"]

    @pytest.mark.asyncio
    async def test_run_with_skip_no_key_models(self, monkeypatch):
        """Models without keys appear in errors, not responses."""
        monkeypatch.setenv("MODEL_COMPARE_API_KEYS", '{"has-key":"sk-test"}')
        config = mc.CompareConfig.from_env("q", models_override=["has-key", "no-key"])
        config.timeout = 5.0
        comparator = mc.ModelComparator(config)

        with patch("model_compare.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_mock_chat_response("Answer")
            )
            mock_cls.return_value = mock_client

            result = await comparator.run()
            assert len(result.responses) == 1  # Only has-key model responded
            assert any("no-key" in e.lower() or "Skipped" in e for e in result.errors)
