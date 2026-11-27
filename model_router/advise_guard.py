"""The ask_advisor tool and the read-only guard on the advisor's child.

The agent that is working asks one question and waits for the answer in the
same tool call. The answer comes from a native ``delegate_task`` child routed
to the ``advise`` slot, dispatched synchronously through the registered
tool-execution middleware so the runtime limit and every other delegation
observer apply as they do to an ordinary call.

The child may read but never change anything: every tool call from its session
outside ``READ_ONLY_TOOLS`` is blocked by a ``pre_tool_call`` hook, and so is a
later ``continue`` of that child. The guard binds the child's exact native
session and subagent ids from ``subagent_start`` and follows the session across
compaction. Bindings live in a process-wide store that outlives a plugin reload,
and any child whose goal carries the advisor marker is bound even without an
in-flight call record. If the child of a call cannot be bound, its answer is
discarded and the call reports the refusal.

Nothing here writes settings or Hermes state; the bindings live in memory.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
import types
from typing import Any, Callable, Mapping
from uuid import uuid4

from .slots import ADVISE_SLOT

logger = logging.getLogger(__name__)

TOOL_NAME = "ask_advisor"
# Reading and looking up only. Everything else (terminal, code execution, file
# writes, browser, delegation, the deferred tool bridge, MCP tools) is blocked.
READ_ONLY_TOOLS = frozenset({
    "read_file", "search_files", "web_search", "web_extract", "skill_view", "skills_list", "vision_analyze",
})
ADVISE_TIMEOUT_SECONDS = 300
QUESTION_LIMIT = 4000
CONTEXT_LIMIT = 24000
# Every advisor child's goal starts with this marker. The goal is fixed text: the question rides in the
# context, which the host's batch template-marker check does not inspect.
GOAL_MARKER = re.compile(r"Advisor consultation [0-9a-f]{12}\. ")
BLOCK_MESSAGE = ("Blocked by Model Router: the advisor is read-only. Only {tools} are available; "
                 "answer from what you can read and leave every change to the agent that asked.")
CONTINUE_BLOCK_MESSAGE = ("Blocked by Model Router: an advisor child cannot be continued. "
                          "Ask a new question with ask_advisor instead.")
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "description": "What to do next, stated directly."},
        "reasons": {"type": "array", "items": {"type": "string"}, "description": "Why, in short points."},
        "risks": {"type": "array", "items": {"type": "string"}, "description": "What could go wrong or still needs checking."},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["recommendation", "confidence"],
}
# A module name outside this plugin's package, so a plugin reload (which evicts the package's
# modules and re-registers fresh hooks) finds the same bindings again.
_STORE_MODULE = "_hermes_model_router_advisor_bindings"

_ACTIVE_CALL: contextvars.ContextVar["_AdvisorCall | None"] = contextvars.ContextVar(
    "model_router_advisor_call", default=None,
)


@dataclass
class _Bindings:
    lock: threading.Lock = field(default_factory=threading.Lock)
    sessions: set[str] = field(default_factory=set)
    subagents: set[str] = field(default_factory=set)


@dataclass
class _AdvisorCall:
    guard: "AdviseGuard"
    goal: str
    parent_session_id: str
    started: int = 0
    unbound: bool = False
    closed: bool = False
    sessions: set[str] = field(default_factory=set)


def _bindings(home_key: str) -> Any:
    """This profile's process-wide bindings; created once, shared by every load of the plugin."""
    store = sys.modules.get(_STORE_MODULE)
    if store is None:
        fresh = types.ModuleType(_STORE_MODULE)
        fresh.lock = threading.Lock()
        fresh.homes = {}
        store = sys.modules.setdefault(_STORE_MODULE, fresh)
    with store.lock:
        entry = store.homes.get(home_key)
        if entry is None:
            entry = store.homes[home_key] = _Bindings()
        return entry


def _identifier(value: Any) -> str | None:
    if (not isinstance(value, str) or not value or len(value) > 256 or value != value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        return None
    return value


def _home_key(path: Any) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=True)))


def advisor_call_active(home: Any, goal: Any) -> bool:
    """Whether ``goal`` is the in-flight ask_advisor call of this profile, asked by the current parent."""
    call = _ACTIVE_CALL.get()
    try:
        if not (call is not None and not call.closed and call.guard.ready and isinstance(goal, str)
                and goal == call.goal and _home_key(home) == call.guard.home_key):
            return False
        # Inside the advisor child's own turn the active parent is the child, not the asker.
        parent = call.guard.get_active_parent()
        return _identifier(getattr(parent, "session_id", None)) == call.parent_session_id
    except Exception:
        return False


def _reply(status: str, **fields: Any) -> str:
    return json.dumps({"status": status, **fields}, ensure_ascii=False)


def _same_model(route: Mapping[str, Any], parent: Any) -> bool:
    model = getattr(parent, "model", None)
    provider = getattr(parent, "provider", None)
    return (isinstance(model, str) and isinstance(provider, str)
            and route.get("model", "").casefold() == model.casefold()
            and route.get("provider", "").casefold() == provider.casefold())


def _goal(nonce: str) -> str:
    return (f"Advisor consultation {nonce}. Another agent is doing the work and asks for your judgment on one "
            "question, given in the context. Answer it directly; do not do the work yourself.")


def _context(question: str, context: str) -> str:
    rules = ("You are read-only. You may read files and look things up; any tool that changes files, runs "
             "commands, drives a browser or delegates is blocked. Keep the answer short (about 700 tokens at "
             "most): a recommendation, the reasons, the risks, and your confidence.")
    text = rules + "\n\nQuestion:\n" + question
    return text + ("\n\nWhat the asking agent knows so far:\n" + context if context else "")


def _refusal_text(value: Any) -> str:
    return str(value)[:500] if value else "refused"


class AdviseGuard:
    """Session-bound read-only guard plus the synchronous advisor dispatch."""

    def __init__(
        self,
        home: str | Path,
        *,
        get_active_parent: Callable[[], Any],
        dispatch_backend: Callable[[Any], str],
        resolve_route: Callable[[], dict[str, Any]],
        run_delegation: Callable[[dict[str, Any], Any, Mapping[str, Any]], Any],
        routing_enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self.home_key = _home_key(home)
        self.get_active_parent = get_active_parent
        self.dispatch_backend = dispatch_backend
        self.resolve_route = resolve_route
        self.run_delegation = run_delegation
        self.routing_enabled = routing_enabled
        # Bound for the life of the process and shared across plugin reloads: a released session
        # could otherwise be continued with every tool. Holding a dead id only ever blocks more.
        self.bindings = _bindings(self.home_key)
        self.ready = False

    # ---- hooks -------------------------------------------------------------------------------

    def on_subagent_start(self, **payload: Any) -> None:
        goal = payload.get("child_goal")
        call = _ACTIVE_CALL.get()
        ours = (call is not None and call.guard is self and not call.closed and goal == call.goal
                and payload.get("parent_session_id") == call.parent_session_id)
        # A child carrying the advisor marker is bound even without this call record (a reload,
        # a rebuilt or continued child): binding too much only blocks more.
        marked = isinstance(goal, str) and GOAL_MARKER.match(goal) is not None
        if not (ours or marked):
            return
        session_id = _identifier(payload.get("child_session_id"))
        subagent_id = _identifier(payload.get("child_subagent_id"))
        with self.bindings.lock:
            if ours:
                call.started += 1
            if session_id is not None:
                self.bindings.sessions.add(session_id)
            if subagent_id is not None:
                self.bindings.subagents.add(subagent_id)
            if session_id is None or subagent_id is None:
                if ours:
                    call.unbound = True
                return
            if ours:
                call.sessions.add(session_id)

    def on_post_compaction(self, session_id: Any = None, old_session_id: Any = None, **_: Any) -> None:
        new, old = _identifier(session_id), _identifier(old_session_id)
        if new is None or old is None:
            return
        with self.bindings.lock:
            if old in self.bindings.sessions:
                self.bindings.sessions.add(new)

    def pre_tool_call(self, tool_name: Any = None, args: Any = None, session_id: Any = None,
                      task_id: Any = None, **_: Any) -> Any:
        try:
            with self.bindings.lock:
                # The child's conversation task id is its subagent id and survives a session rotation
                # whose compaction event was lost.
                bound = ((isinstance(session_id, str) and session_id in self.bindings.sessions)
                         or (isinstance(task_id, str) and task_id in self.bindings.subagents))
                if bound:
                    if tool_name in READ_ONLY_TOOLS:
                        return None
                    return {"action": "block", "message": BLOCK_MESSAGE.format(tools=", ".join(sorted(READ_ONLY_TOOLS)))}
                if tool_name == "delegate_task" and isinstance(args, dict):
                    action, target = args.get("action"), args.get("subagent_id")
                    if (isinstance(action, str) and action.strip().lower() == "continue"
                            and isinstance(target, str) and target.strip() in self.bindings.subagents):
                        return {"action": "block", "message": CONTINUE_BLOCK_MESSAGE}
            return None
        except Exception:
            # Block on our own internal errors, whatever the host does with a raising hook.
            logger.warning("advisor guard check failed; blocking the call", exc_info=False)
            return {"action": "block", "message": BLOCK_MESSAGE.format(tools=", ".join(sorted(READ_ONLY_TOOLS)))}

    # ---- tool --------------------------------------------------------------------------------

    def available(self) -> bool:
        """Offer the tool only when the guard is active and this profile routes task slots."""
        try:
            return self.ready and bool(self.routing_enabled())
        except Exception:
            return False

    def tool(self, args: Any, **kwargs: Any) -> str:
        try:
            return self._tool(args, kwargs)
        except Exception:
            logger.warning("ask_advisor failed", exc_info=False)
            return _reply("refused", error="advisor_unavailable",
                          message="The advisor could not run. Decide yourself; nothing was changed.")

    def _tool(self, args: Any, kwargs: Mapping[str, Any]) -> str:
        if not self.ready:
            return _reply("refused", error="guard_unavailable", message="The read-only advisor guard is not active.")
        if not isinstance(args, dict) or set(args) - {"question", "context"}:
            return _reply("refused", error="invalid_params", message="Send question and, optionally, context.")
        question, context = args.get("question"), args.get("context", "")
        if not isinstance(question, str) or not question.strip() or len(question) > QUESTION_LIMIT:
            return _reply("refused", error="invalid_question", message=f"question must be 1-{QUESTION_LIMIT} characters.")
        if not isinstance(context, str) or len(context) > CONTEXT_LIMIT:
            return _reply("refused", error="invalid_context", message=f"context must be at most {CONTEXT_LIMIT} characters.")
        if _ACTIVE_CALL.get() is not None:
            return _reply("refused", error="nested_advisor", message="An advisor call is already in progress here.")
        parent = self.get_active_parent()
        parent_session_id = _identifier(getattr(parent, "session_id", None))
        if parent is None or parent_session_id is None or kwargs.get("session_id") != parent_session_id:
            return _reply("refused", error="bound_parent_required", message="The advisor runs only for the agent that asked.")
        backend = self.dispatch_backend(parent)
        if backend not in ("model-router", "model-router-auto"):
            return _reply("refused", error="routing_backend_required",
                          message="This session does not delegate through Model Router task slots.")
        route = self.resolve_route()
        if _same_model(route, parent):
            return _reply("skipped", reason="same_model", model=route.get("model"),
                          message="The advise slot runs on your own model; decide yourself instead of asking.")

        goal = _goal(uuid4().hex[:12])
        task: dict[str, Any] = {"goal": goal, "context": _context(question.strip(), context.strip()),
                                "purpose": ADVISE_SLOT, "total_timeout_seconds": ADVISE_TIMEOUT_SECONDS}
        if backend == "model-router-auto":
            task["execution"] = "model"
        request = {"tasks": [task], "output_schema": OUTPUT_SCHEMA}
        call = _AdvisorCall(guard=self, goal=goal, parent_session_id=parent_session_id)
        token = _ACTIVE_CALL.set(call)
        try:
            raw = self.run_delegation(request, parent, kwargs)
        finally:
            call.closed = True
            _ACTIVE_CALL.reset(token)
        return self._result(call, raw)

    def _refused(self, message: Any) -> str:
        text = _refusal_text(message)
        if "max_spawn_depth" in text:
            return _reply("refused", error="depth_limit",
                          message="This agent is already a delegated child at the depth limit; it cannot ask the advisor.")
        return _reply("refused", error="dispatch_refused", message=text)

    def _result(self, call: _AdvisorCall, raw: Any) -> str:
        if call.unbound or call.started > 1:
            return _reply("refused", error="guard_unbound",
                          message="The advisor child could not be bound to the read-only guard; its answer was discarded.")
        payload = raw if isinstance(raw, dict) else None
        if payload is None and isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                payload = None
        if not isinstance(payload, dict):
            return _reply("refused", error="no_result", message="The advisor returned no readable result.")
        results = payload.get("results")
        if not isinstance(results, list):
            # A whole-call refusal (preflight, depth, pause): no child was built.
            return self._refused(payload.get("error"))
        if len(results) != 1 or not isinstance(results[0], dict):
            return _reply("refused", error="no_result", message="The advisor returned no readable result.")
        entry = results[0]
        route = entry.get("route")
        if isinstance(route, dict) and route.get("refused") is True:
            # The route refused this task: no child was built for it.
            return self._refused(entry.get("error"))
        if call.started == 0:
            # A result entry without a bound start means a child ran unguarded.
            return _reply("refused", error="guard_unbound",
                          message="The advisor child could not be bound to the read-only guard; its answer was discarded.")
        status = entry.get("status")
        reply: dict[str, Any] = {
            "advice": entry.get("summary"),
            "schema_valid": entry.get("schema_valid"),
            "model": entry.get("model"),
            "route": route,
            "duration_seconds": entry.get("duration_seconds"),
        }
        if entry.get("error"):
            reply["error"] = _refusal_text(entry["error"])
        if entry.get("schema_note"):
            reply["schema_note"] = entry["schema_note"]
        reply["note"] = "Advice is input to your decision, not a verified fact or approval."
        return _reply("ok" if status == "completed" else "failed", **reply)


SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Ask a stronger model for advice at a decision point while you keep doing the work yourself. Use it "
        "sparingly: before committing to an approach, after the same failure twice, or before declaring a hard task "
        "done. The advisor is read-only (it can read files and look things up but cannot change anything) and does "
        "not see this conversation, so put the decision, what you tried, the evidence and the relevant absolute paths "
        "or excerpts in context. This call waits for the answer (about five minutes at most). If the advise slot runs "
        "on your own model the call is skipped; decide yourself. A delegated child at the delegation depth limit "
        "cannot ask. Advice is input, not approval or verified fact."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "question": {"type": "string", "description": "The one decision you want advice on."},
            "context": {"type": "string", "description": "What the advisor needs: goal, findings so far, options considered, absolute file paths or excerpts."},
        },
        "required": ["question"],
    },
}


def _run_delegation(request: dict[str, Any], parent: Any, kwargs: Mapping[str, Any]) -> Any:
    """The synchronous native call, through every registered tool-execution middleware."""
    from hermes_cli.middleware import run_tool_execution_middleware
    from tools.delegate_tool import delegate_task

    def terminal(args: Any) -> Any:
        return delegate_task(**dict(args), parent_agent=parent, background=False)

    context = {name: kwargs.get(name) or "" for name in ("task_id", "tool_call_id", "turn_id", "api_request_id", "conversation_id")}
    return run_tool_execution_middleware("delegate_task", request, terminal,
                                         session_id=getattr(parent, "session_id", "") or "", **context)


def register_advise_guard(ctx: Any, home: str | Path, *, routing_enabled: Callable[[], bool] = lambda: False,
                          run_delegation: Callable[..., Any] | None = None) -> AdviseGuard | None:
    """Register the guard hooks first and the tool last; any failure leaves the tool unavailable."""
    from .native_watchdog import _dispatch_backend, _get_active_parent

    def resolve_route() -> dict[str, Any]:
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override
        from .native_delegation import resolve_slot_route
        from .service import Service
        token = set_hermes_home_override(str(home))
        try:
            return resolve_slot_route(Path(home), Service(), ADVISE_SLOT)[0]
        finally:
            reset_hermes_home_override(token)

    try:
        guard = AdviseGuard(home, get_active_parent=_get_active_parent, dispatch_backend=_dispatch_backend,
                            resolve_route=resolve_route, run_delegation=run_delegation or _run_delegation,
                            routing_enabled=routing_enabled)
    except Exception:
        logger.debug("advisor guard unavailable for this profile", exc_info=True)
        return None
    handles: list[Any] = []
    try:
        handles.append(ctx.register_hook("pre_tool_call", guard.pre_tool_call))
        handles.append(ctx.register_hook("subagent_start", guard.on_subagent_start))
        handles.append(ctx.register_hook("post_compaction", guard.on_post_compaction))
        guard.ready = True  # only once every hook is registered
    except Exception:
        for handle in reversed(handles):
            dispose = getattr(handle, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    pass
        logger.warning("advisor guard hooks could not be registered; ask_advisor stays unavailable")
    ctx.register_tool(name=TOOL_NAME, toolset="model_router", schema=SCHEMA, handler=guard.tool,
                      check_fn=guard.available)
    return guard
