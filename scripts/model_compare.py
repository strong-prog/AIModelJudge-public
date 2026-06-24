#!/usr/bin/env python3
"""Сравнительный анализ ответов нескольких моделей.

Запрашивает N моделей параллельно, затем судья (или голосование) выбирает лучший ответ.

Usage:
    python scripts/model_compare.py "Your query here"
    python scripts/model_compare.py --models deepseek-chat,gpt-4o "Your query"
    python scripts/model_compare.py --mode vote "Your query"
    echo "Your query" | python scripts/model_compare.py --stdin
    python scripts/model_compare.py --show-config
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from openai import AsyncOpenAI

logger = logging.getLogger("model_compare")


def _load_hermes_dotenv() -> None:
    """Загружает переменные из ~/.hermes/.env, если они ещё не заданы в окружении."""
    dotenv_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.isfile(dotenv_path):
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_hermes_dotenv()

# ── Configuration ────────────────────────────────────────────────────


@dataclass
class CompareConfig:
    models: list[str]
    judge_model: str
    query: str
    mode: str = "judge"
    api_keys: dict[str, str] = field(default_factory=dict)
    api_base_urls: dict[str, str] = field(default_factory=dict)
    temperature: float = 0.7
    max_tokens: int = 2048
    judge_max_tokens: int = 4096
    timeout: float = 120.0

    @classmethod
    def from_env(cls, query: str, models_override: Optional[list[str]] = None,
                 mode_override: Optional[str] = None,
                 judge_override: Optional[str] = None) -> CompareConfig:
        models_str = os.getenv("MODEL_COMPARE_MODELS", "deepseek-chat,gpt-4o")
        if models_override is not None:
            models = list(models_override)
        else:
            models = [m.strip() for m in models_str.split(",") if m.strip()]
        judge = judge_override or os.getenv("MODEL_COMPARE_JUDGE_MODEL", "") or (
            models[0] if models else "deepseek-chat"
        )

        api_keys = cls._parse_json_env("MODEL_COMPARE_API_KEYS", {})
        api_base_urls = cls._parse_json_env("MODEL_COMPARE_BASE_URLS", {})

        return cls(
            models=models,
            judge_model=judge,
            query=query,
            mode=mode_override or os.getenv("MODEL_COMPARE_MODE", "judge"),
            api_keys=api_keys,
            api_base_urls=api_base_urls,
            temperature=float(os.getenv("MODEL_COMPARE_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("MODEL_COMPARE_MAX_TOKENS", "2048")),
            judge_max_tokens=int(os.getenv("MODEL_COMPARE_JUDGE_MAX_TOKENS", "4096")),
            timeout=float(os.getenv("MODEL_COMPARE_TIMEOUT", "120")),
        )

    @staticmethod
    def _parse_json_env(name: str, default: Any) -> Any:
        raw = os.getenv(name, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse %s as JSON, using default", name)
            return default

    def resolve_api_key(self, model: str) -> Optional[str]:
        if model in self.api_keys:
            return self.api_keys[model]
        if model.startswith("deepseek"):
            return os.getenv("DEEPSEEK_API_KEY")
        if model.startswith(("gpt-", "o1", "o3", "o4")):
            return os.getenv("OPENAI_API_KEY")
        if model.startswith("claude"):
            return os.getenv("ANTHROPIC_API_KEY")
        return os.getenv("OPENAI_API_KEY")

    def resolve_base_url(self, model: str) -> Optional[str]:
        if model in self.api_base_urls:
            return self.api_base_urls[model]
        if model.startswith("deepseek"):
            return os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        if model.startswith(("gpt-", "o1", "o3", "o4")):
            return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if model.startswith("claude"):
            return os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
        return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def show(self) -> str:
        lines = [
            f"models:       {self.models}",
            f"judge_model:  {self.judge_model}",
            f"mode:         {self.mode}",
            f"timeout:      {self.timeout}s",
            f"temperature:  {self.temperature}",
            f"max_tokens:   {self.max_tokens}",
            f"judge_max_tokens: {self.judge_max_tokens}",
            f"api_base_urls: {self.api_base_urls}",
            "api_keys:     ***" if self.api_keys else "api_keys:     (none)",
        ]
        return "\n".join(lines)


# ── Response Containers ──────────────────────────────────────────────


@dataclass
class ModelResponse:
    model: str
    content: str = ""
    reasoning_content: str = ""
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    tokens_prompt: int = 0
    tokens_completion: int = 0


@dataclass
class ComparisonResult:
    query: str
    mode: str
    timestamp: str
    models_queried: list[str]
    responses: list[dict]
    judge_answer: Optional[str]
    winner: Optional[str]
    justification: Optional[str]
    runner_up: Optional[str]
    scores: dict[str, dict[str, int]]
    errors: list[str]
    total_elapsed_ms: float
    judge_prompt: str = ""
    judge_raw_response: str = ""


# ── Judge Prompt ─────────────────────────────────────────────────────

JUDGE_SYSTEM_PROMPT = """Ты — судья-аналитик. Ты получишь запрос пользователя и два независимых ответа
от первичных AI-моделей. Твоя задача — дать СВОЙ СОБСТВЕННЫЙ ответ на запрос пользователя,
проанализировав и обобщив оба первичных ответа, а затем выбрать лучший из них.

Выполни строго в этом порядке:

1. СНАЧАЛА дай свой ответ на вопрос пользователя (поле judge_answer).
   Твой ответ должен быть самодостаточным, полным и точным.
   Возьми лучшее из обоих первичных ответов, исправь ошибки если есть,
   дополни недостающее, отбрось неверное. Это НЕ пересказ — это твой синтезированный ответ.

2. ЗАТЕМ выбери лучший из ПЕРВИЧНЫХ ответов (поле winner) и оцени каждый по 5 критериям.

Ты ДОЛЖЕН выдать ровно эту JSON-структуру (без лишнего текста, без markdown-ограждений):
{
  "judge_answer": "<ТВОЙ полный ответ на вопрос пользователя. Бери лучшее из обоих, исправляй ошибки, дополняй. Отвечай на русском.>",
  "winner": "<точное имя модели из списка>",
  "justification": "<2-5 предложений: почему winner лучше второго. Будь конкретен.>",
  "runner_up": "<второе место — имя модели или null>",
  "scores": {
    "<модель_1>": {"correctness": 1-10, "completeness": 1-10, "clarity": 1-10, "conciseness": 1-10, "helpfulness": 1-10},
    "<модель_2>": {...}
  }
}

Критерии оценки:

1. Сравни все ответы по критериям: корректность, полнота, ясность, лаконичность, полезность.
2. Выбери ЕДИНСТВЕННЫЙ лучший ответ.
3. Объясни ПОЧЕМУ он лучший — конкретно, с отсылками к сильным сторонам победителя
   и слабым сторонам остальных.
4. Если ответы сопоставимы — отметь компромиссы.

Ты ДОЛЖЕН выдать ровно эту JSON-структуру (без лишнего текста, без markdown-ограждений):
{
  "winner": "<точное имя модели из списка>",
  "justification": "<2-5 предложений с объяснением выбора>",
  "runner_up": "<второе место — имя модели или null>",
  "scores": {
    "<модель_1>": {"correctness": 1-10, "completeness": 1-10, "clarity": 1-10, "conciseness": 1-10, "helpfulness": 1-10},
    "<модель_2>": {...}
  }
}

Критерии оценки:
- correctness: фактическая точность, отсутствие галлюцинаций, логическая стройность
- completeness: полное покрытие вопроса, ничего не упущено
- clarity: хорошо структурировано, легко читается, хорошее форматирование
- conciseness: без воды, по делу, эффективное использование слов
- helpfulness: практически применимо, полезно для пользователя

Будь объективен. Не отдавай предпочтение модели только из-за её названия.
Победитель ДОЛЖЕН быть одним из точных имён моделей из списка ответов.
Отвечай на русском языке."""

VOTE_SYSTEM_PROMPT = """You are a model-output evaluator. Below is a user query followed by
responses from different models labeled A, B, C, etc.

Pick the SINGLE BEST response. Output ONLY the letter (e.g. "A") — no other text, no explanation."""


# ── Base URL Provider Map ────────────────────────────────────────────

PROVIDER_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def _detect_base_url(model: str) -> str:
    for prefix, url in PROVIDER_BASE_URLS.items():
        if model.lower().startswith(prefix):
            return url
    return PROVIDER_BASE_URLS["openai"]


# ── Core Engine ──────────────────────────────────────────────────────


class ModelComparator:
    def __init__(self, config: CompareConfig) -> None:
        self.config = config

    async def query_model(self, model: str, client: AsyncOpenAI) -> ModelResponse:
        start = time.monotonic()
        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": self.config.query}],
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                ),
                timeout=self.config.timeout,
            )
            elapsed = (time.monotonic() - start) * 1000
            content = resp.choices[0].message.content or ""
            reasoning = getattr(resp.choices[0].message, 'reasoning_content', None) or ''
            return ModelResponse(
                model=model,
                content=content,
                reasoning_content=reasoning,
                elapsed_ms=round(elapsed, 1),
                tokens_prompt=resp.usage.prompt_tokens if resp.usage else 0,
                tokens_completion=resp.usage.completion_tokens if resp.usage else 0,
            )
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning("Model %s timed out after %.1fs", model, self.config.timeout)
            return ModelResponse(
                model=model, elapsed_ms=round(elapsed, 1),
                error=f"Timeout after {self.config.timeout}s",
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning("Model %s failed: %s: %s", model, type(e).__name__, e)
            return ModelResponse(
                model=model, elapsed_ms=round(elapsed, 1),
                error=f"{type(e).__name__}: {e!s}",
            )

    def _build_clients(self) -> dict[str, Optional[AsyncOpenAI]]:
        clients: dict[str, Optional[AsyncOpenAI]] = {}
        for model in self.config.models:
            api_key = self.config.resolve_api_key(model)
            if not api_key:
                logger.warning("No API key for model %s — skipping", model)
                clients[model] = None
                continue
            base_url = self.config.resolve_base_url(model) or _detect_base_url(model)
            clients[model] = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=self.config.timeout,
            )
        return clients

    async def run(self) -> ComparisonResult:
        t0 = time.monotonic()
        clients = self._build_clients()

        skipped = [m for m, c in clients.items() if c is None]
        active = {m: c for m, c in clients.items() if c is not None}

        if not active:
            total_ms = (time.monotonic() - t0) * 1000
            return ComparisonResult(
                query=self.config.query,
                mode=self.config.mode,
                timestamp=datetime.now(timezone.utc).isoformat(),
                models_queried=self.config.models,
                responses=[],
                judge_answer=None,
                winner=None,
                justification=None,
                runner_up=None,
                scores={},
                errors=[f"No API keys configured. Models: {self.config.models}. "
                        f"Set MODEL_COMPARE_API_KEYS or provider-specific keys."],
                total_elapsed_ms=round(total_ms, 1),
            )

        # Fire all queries in parallel
        tasks = {
            model: asyncio.create_task(
                self.query_model(model, client), name=f"cmp-{model}"
            )
            for model, client in active.items()
        }
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)

        responses: list[ModelResponse] = []
        errors: list[str] = []
        for model, result in zip(tasks.keys(), gathered):
            if isinstance(result, Exception):
                logger.warning("Unhandled exception for %s: %s", model, result)
                responses.append(ModelResponse(model=model, error=f"{type(result).__name__}: {result!s}"))
            else:
                responses.append(result)

        for m in skipped:
            errors.append(f"Skipped {m}: no API key")

        successful = [r for r in responses if not r.error]
        failed = [r for r in responses if r.error]
        for r in failed:
            errors.append(f"{r.model}: {r.error}")

        if not successful:
            total_ms = (time.monotonic() - t0) * 1000
            return ComparisonResult(
                query=self.config.query,
                mode=self.config.mode,
                timestamp=datetime.now(timezone.utc).isoformat(),
                models_queried=self.config.models,
                responses=[asdict(r) for r in responses],
                judge_answer=None,
                winner=None,
                justification=None,
                runner_up=None,
                scores={},
                errors=errors,
                total_elapsed_ms=round(total_ms, 1),
            )

        # Judging phase
        if self.config.mode == "vote":
            judge_prompt = ""
            judge_raw_response = ""
            judge_answer = None
            winner, justification, scores = await self._vote(successful, active)
        else:
            judge_answer, winner, justification, scores, judge_prompt, judge_raw_response = await self._judge(successful, active)

        runner_up = self._resolve_runner_up(scores, winner)

        total_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "Comparison complete: %d models, winner=%s, elapsed=%.0fms",
            len(successful), winner, total_ms,
        )
        return ComparisonResult(
            query=self.config.query,
            mode=self.config.mode,
            timestamp=datetime.now(timezone.utc).isoformat(),
            models_queried=self.config.models,
            responses=[asdict(r) for r in responses],
            judge_answer=judge_answer,
            winner=winner,
            justification=justification,
            runner_up=runner_up,
            scores=scores,
            errors=errors if errors else [],
            total_elapsed_ms=round(total_ms, 1),
            judge_prompt=judge_prompt,
            judge_raw_response=judge_raw_response,
        )

    # ── Judge ────────────────────────────────────────────────────────

    async def _judge(
        self, responses: list[ModelResponse], clients: dict[str, AsyncOpenAI]
    ) -> tuple[Optional[str], Optional[str], Optional[str], dict[str, dict[str, int]], str, str]:
        """Returns (judge_answer, winner, justification, scores, judge_prompt, judge_raw_response)."""
        judge_client = clients.get(self.config.judge_model)
        if judge_client is None:
            judge_client = next(iter(clients.values()))
            logger.info("Judge model %s not available, using %s as judge",
                        self.config.judge_model, self.config.models[0])

        messages = self._build_judge_messages(responses)
        judge_prompt = json.dumps(messages, ensure_ascii=False, indent=2)

        try:
            judge_resp = await asyncio.wait_for(
                judge_client.chat.completions.create(
                    model=self.config.judge_model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=self.config.judge_max_tokens,
                ),
                timeout=self.config.timeout,
            )
            content = judge_resp.choices[0].message.content or ""
            parsed = self._parse_judge_json(content, responses)
            return (
                parsed.get("judge_answer"),
                parsed.get("winner"),
                parsed.get("justification"),
                parsed.get("scores", {}),
                judge_prompt,
                content,
            )
        except Exception as e:
            logger.warning("Judge model failed: %s", e)
            winner = responses[0].model if responses else None
            return (
                None,
                winner,
                f"Judge evaluation failed ({e!s}). Selected {winner} as default.",
                {},
                judge_prompt,
                f"ERROR: {e!s}",
            )

    def _build_judge_messages(self, responses: list[ModelResponse]) -> list[dict]:
        user_parts = [f"USER QUERY:\n{self.config.query}\n\nMODEL RESPONSES:"]
        for i, r in enumerate(responses, 1):
            user_parts.append(f"\n--- Response {i}: {r.model} ---\n{r.content}\n")

        return [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    def _parse_judge_json(
        self, content: str, responses: list[ModelResponse]
    ) -> dict:
        model_names = {r.model for r in responses}

        # Try direct JSON parse
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown fences
            m = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
            if m:
                try:
                    data = json.loads(m.group(1))
                except json.JSONDecodeError:
                    data = self._regex_extract(content, model_names)
            else:
                data = self._regex_extract(content, model_names)

        # Validate winner is in our model list
        winner = data.get("winner", "")
        if winner not in model_names:
            data["winner"] = responses[0].model
            data["justification"] = (
                f"Winner '{winner}' not in queried models. "
                f"Fell back to {responses[0].model}. "
                f"Original judge response: {content[:200]}"
            )
        return data

    def _regex_extract(self, content: str, model_names: set[str]) -> dict:
        """Fallback: regex extraction of winner from judge text."""
        winner = None
        for name in model_names:
            if name in content:
                winner = name
                break
        if winner is None:
            winner = next(iter(model_names)) if model_names else "unknown"
        return {
            "winner": winner,
            "justification": f"Judge returned non-JSON. Winner determined by regex. "
                             f"Raw: {content[:300]}",
            "scores": {},
        }

    # ── Vote ─────────────────────────────────────────────────────────

    async def _vote(
        self, responses: list[ModelResponse], clients: dict[str, AsyncOpenAI]
    ) -> tuple[Optional[str], Optional[str], dict[str, dict[str, int]]]:
        labels = [chr(ord('A') + i) for i in range(len(responses))]
        label_to_model = dict(zip(labels, [r.model for r in responses]))
        model_to_label = {r.model: l for l, r in zip(labels, responses)}

        block_parts = ["USER QUERY:\n" + self.config.query + "\n\nRESPONSES:"]
        for label, r in zip(labels, responses):
            block_parts.append(f"\n[{label}] {r.model}\n{r.content}\n")
        block = "\n".join(block_parts)

        vote_messages = [
            {"role": "system", "content": VOTE_SYSTEM_PROMPT},
            {"role": "user", "content": block},
        ]

        async def get_vote(voter_client: AsyncOpenAI, voter_model: str) -> Optional[str]:
            try:
                resp = await asyncio.wait_for(
                    voter_client.chat.completions.create(
                        model=voter_model,
                        messages=vote_messages,
                        temperature=0.1,
                        max_tokens=16,
                    ),
                    timeout=self.config.timeout,
                )
                vote_text = (resp.choices[0].message.content or "").strip().upper()
                m = re.search(r'[A-Z]', vote_text)
                return m.group(0) if m else None
            except Exception as e:
                logger.warning("Voter %s failed: %s", voter_model, e)
                return None

        # Each model votes (use any available client for voting)
        vote_tasks = []
        for r in responses:
            voter_client = clients.get(r.model) or next(iter(clients.values()))
            vote_tasks.append(get_vote(voter_client, r.model))
        votes = await asyncio.gather(*vote_tasks, return_exceptions=True)

        tally: dict[str, int] = {}
        for r, vote in zip(responses, votes):
            if isinstance(vote, str) and vote in label_to_model:
                winner_model = label_to_model[vote]
                tally[winner_model] = tally.get(winner_model, 0) + 1

        if not tally:
            return (
                responses[0].model,
                "Voting failed — no valid votes cast. Defaulted to first model.",
                {},
            )

        winner = max(tally, key=lambda k: (tally[k], -next(
            (r.elapsed_ms for r in responses if r.model == k), 999999
        )))
        tally_str = ", ".join(f"{m}: {c}" for m, c in sorted(tally.items(), key=lambda x: -x[1]))
        return winner, f"Vote tally: {tally_str}. Winner: {winner}", {}

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve_runner_up(
        scores: dict[str, dict[str, int]], winner: Optional[str]
    ) -> Optional[str]:
        if not scores or not winner:
            return None
        total_scores = {
            m: sum(criteria.values()) for m, criteria in scores.items() if m != winner
        }
        if not total_scores:
            return None
        return max(total_scores, key=lambda k: total_scores[k])


# ── CLI ──────────────────────────────────────────────────────────────


def parse_args(argv: Optional[list[str]] = None) -> dict:
    """Parse CLI args. Returns dict with keys: query, models, mode, judge, stdin, show_config."""
    if argv is None:
        argv = sys.argv[1:]

    result: dict = {
        "query": None,
        "models": None,
        "mode": None,
        "judge": None,
        "stdin": False,
        "show_config": False,
    }

    i = 0
    positional: list[str] = []
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        elif arg == "--models" and i + 1 < len(argv):
            i += 1
            result["models"] = [m.strip() for m in argv[i].split(",") if m.strip()]
        elif arg == "--mode" and i + 1 < len(argv):
            i += 1
            result["mode"] = argv[i]
        elif arg == "--judge" and i + 1 < len(argv):
            i += 1
            result["judge"] = argv[i]
        elif arg == "--stdin":
            result["stdin"] = True
        elif arg == "--show-config":
            result["show_config"] = True
        elif not arg.startswith("--"):
            positional.append(arg)
        i += 1

    if positional:
        result["query"] = " ".join(positional)

    return result


async def main() -> None:
    args = parse_args()

    if args["show_config"]:
        config = CompareConfig.from_env("", args["models"], args["mode"], args["judge"])
        print(config.show())
        return

    # Determine query
    query: Optional[str] = args["query"]
    if args["stdin"]:
        stdin_text = sys.stdin.read().strip()
        query = query or stdin_text

    if not query:
        print(json.dumps({
            "error": "No query provided. Use: python scripts/model_compare.py \"Your query\" "
                     "or pipe input with --stdin",
        }, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    config = CompareConfig.from_env(query, args["models"], args["mode"], args["judge"])
    logger.info("Starting comparison: %d models, mode=%s, query_len=%d",
                len(config.models), config.mode, len(query))

    comparator = ModelComparator(config)
    result = await comparator.run()

    # Output JSON to stdout
    output = {
        "query": result.query,
        "mode": result.mode,
        "timestamp": result.timestamp,
        "models_queried": result.models_queried,
        "responses": result.responses,
        "judge_answer": result.judge_answer,
        "winner": result.winner,
        "justification": result.justification,
        "runner_up": result.runner_up,
        "scores": result.scores,
        "errors": result.errors,
        "total_elapsed_ms": result.total_elapsed_ms,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    log_level = os.getenv("MODEL_COMPARE_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.WARNING),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(main())
