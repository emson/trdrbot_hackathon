"""One tick: drain the inbox, decide, act, journal, archive.

This is the walking skeleton's spine. It implements the ordering and
idempotency rules the design simulations found load-bearing, and stubs
everything else (sensors, memory, exit rules, calibration) so the end-to-end
path can be explored before those land.

What is real here:
  - write-ahead journalling (INV-18)
  - resume-rather-than-re-decide on retry (INV-27)
  - batch-derived client_order_id (INV-18)
  - at-least-once inbox with dead-letter (INV-20)
  - single-flight stale-breakable lock (INV-7)

What is stubbed: the collector, elfmem, the wiki, exit rules, reconciliation,
forecasting. Those are build stages 2-4.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.prebuilt import create_react_agent

from . import failures, ids, mcp_client, tool_guard
from .config import Config
from .inbox import Inbox, Item
from .journal import Journal
from .llm import SYSTEM_PROMPT, build_model


def _render_context(items: list[Item]) -> str:
    lines = ["## Observations this cycle", ""]
    for it in items:
        lines.append(f"- [{it.type} | trust={it.trust} | {it.ts}] {json.dumps(it.payload)}")
    return "\n".join(lines)


async def run_tick(config: Config, *, verbose: bool = True) -> dict[str, Any]:
    journal = Journal(config.paths.journal)
    inbox = Inbox(config.paths, max_retries=config.max_retries)

    items = inbox.pending()
    if not items:
        if verbose:
            print("[tick] inbox empty - nothing to do")
        return {"status": "idle"}

    batch = ids.batch_id([i.id for i in items])
    if verbose:
        print(f"[tick] batch {batch} with {len(items)} item(s)")

    # INV-27: resume rather than re-decide. An LLM is nondeterministic, so
    # re-deciding after a crash would orphan the write-ahead record and burn a
    # call. The batch-derived order id makes a resubmission safely idempotent.
    prior = journal.unresolved_decision(batch)
    if prior:
        if verbose:
            print(f"[tick] resuming unresolved decision {prior['id']} (not re-deciding)")

    tools = await mcp_client.get_tools(config)
    # The model authors every tool argument, so left alone it invents its own
    # client_order_id and INV-18's idempotency guarantee silently evaporates.
    tools = tool_guard.enforce_order_ids(tools, batch)
    if verbose:
        print(f"[tick] {len(tools)} MCP tools available (order ids pinned to batch)")

    model = build_model(config)
    agent = create_react_agent(model, tools, prompt=SYSTEM_PROMPT)

    prompt = _render_context(items)
    if prior:
        prompt += (
            f"\n\n## Resuming\nA previous decision for this batch did not complete: "
            f"{prior.get('thesis', '(no thesis recorded)')}\n"
            f"Its intended action was: {json.dumps(prior.get('action', {}))}\n"
            f"Re-attempt that same action if it still makes sense; the order id is "
            f"idempotent so a duplicate will be rejected safely."
        )

    # Write-ahead (INV-18): the decision is journalled BEFORE any order goes out.
    decision_id = journal.append(
        "decision",
        batch=batch,
        model=config.model,
        item_ids=[i.id for i in items],
        resumed_from=prior["id"] if prior else None,
        context={"observations": [i.to_dict() for i in items]},
    )
    if verbose:
        print(f"[tick] write-ahead decision {decision_id}")

    try:
        result = await agent.ainvoke({"messages": [("user", prompt)]})
    except Exception as exc:  # noqa: BLE001 - journal it, do not lose the batch
        cause = failures.classify(exc)
        journal.append(
            "error",
            batch=batch,
            decision_ref=decision_id,
            cause=cause.value,
            error=repr(exc),
        )
        for it in items:
            inbox.record_failure(it, reason=f"agent error: {exc!r}", cause=cause)
        if verbose:
            print(f"\n[tick] FAILED ({cause.value})")
            print(f"  {type(exc).__name__}: {exc}")
            print(f"\n  {failures.advice(cause, exc)}\n")
        raise

    messages = result["messages"]
    final = messages[-1]
    tool_calls = [
        tc
        for m in messages
        for tc in (getattr(m, "tool_calls", None) or [])
    ]
    order_calls = [tc for tc in tool_calls if tc.get("name") in mcp_client.ORDER_TOOLS]

    journal.append(
        "execution" if order_calls else "no_op",
        batch=batch,
        decision_ref=decision_id,
        model=config.model,
        client_order_id=ids.client_order_id(batch) if order_calls else None,
        tool_calls=[tc.get("name") for tc in tool_calls],
        # Record the model's args verbatim AND what was actually enforced, so a
        # divergence between the two is visible in the record rather than hidden.
        order_calls=[
            {
                "name": tc.get("name"),
                "args_as_model_supplied": tc.get("args"),
                "client_order_id_enforced": ids.client_order_id(batch),
            }
            for tc in order_calls
        ],
        summary=str(getattr(final, "content", ""))[:2000],
    )

    inbox.archive(items)

    if verbose:
        print(f"\n[tick] tools called: {[tc.get('name') for tc in tool_calls] or 'none'}")
        print(f"[tick] orders placed: {len(order_calls)}")
        print(f"\n--- agent ---\n{getattr(final, 'content', '')}\n")

    return {
        "status": "done",
        "batch": batch,
        "decision": decision_id,
        "tool_calls": [tc.get("name") for tc in tool_calls],
        "orders": len(order_calls),
    }
