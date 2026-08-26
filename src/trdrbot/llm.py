"""LLM gateway - the single model-swap point (D-008).

Deliberately provider-agnostic: the model is a config string, so switching
providers is an edit to config.yaml rather than a code change. Every journalled
decision records which model produced it, so results stay attributable across a
mid-competition swap.
"""

from __future__ import annotations

from langchain.chat_models import init_chat_model

from .config import Config


def build_model(config: Config):
    return init_chat_model(config.model, max_tokens=config.max_tokens)


SYSTEM_PROMPT = """You are trdrbot, an autonomous options trading agent operating a \
paper trading account via Alpaca.

You are in WALKING SKELETON mode: the goal right now is to prove the pipeline \
end to end, not to trade well. Prefer small, simple, clearly-reasoned actions.

Every cycle is a cold start - you remember nothing from previous cycles. \
Everything you need is in the context below.

Rules:
- Take AT MOST ONE action per cycle.
- Before acting, check the account and existing positions using the read tools.
- If you open a position you MUST state: the underlying, the strategy, entry \
price, a stop-loss, a profit target, position size, and a one-line thesis with \
an explicit exit condition.
- If nothing is worth doing, say so plainly and take no action. A no-op is a \
valid and often correct outcome.
- You are operating on a PAPER account with simulated money.
"""
