"""Model Router native plugin. No configuration writes during registration."""
from pathlib import Path
import json
import os


def register(ctx):
    from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
    from .model_router.service import Service
    from .model_router.routing import Router

    home = Path(get_hermes_home())

    def scoped(callback):
        token = set_hermes_home_override(home)
        try:
            return callback(Service())
        finally:
            reset_hermes_home_override(token)

    def enabled():
        try:
            return bool(scoped(lambda service: service.routing_config(service.active_profile())["enabled"]))
        except (OSError, ValueError, RuntimeError, KeyError):
            return False

    def cli_setup(parser):
        parser.add_argument("operation", choices=["status", "preview", "fallback-preview", "delegation-preview", "initial-setup-preview", "apply"])
        parser.add_argument("--body", default="{}")

    def cli_handler(args):
        # Native cli.exec passes an argv array, never a renderer shell command.
        try:
            if len(args.body) > 16384:
                raise ValueError("payload too large")
            body = json.loads(args.body)
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            def operation(service):
                if args.operation == "status":
                    if body: raise ValueError("status does not accept a body")
                    return service.status()
                if args.operation == "preview": return service.preview(body)
                if args.operation == "fallback-preview": return service.fallback_preview(body)
                if args.operation == "delegation-preview": return service.delegation_preview(body)
                if args.operation == "initial-setup-preview": return service.initial_setup_preview(body)
                if set(body) != {"plan_id"}: raise ValueError("apply accepts only plan_id")
                return service.apply(body["plan_id"])
            result = scoped(operation)
            print("MODEL_ROUTER_JSON:" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0
        except Exception as exc:
            print("MODEL_ROUTER_JSON:" + json.dumps({"error": type(exc).__name__, "message": "작업이 완료되지 않았습니다. 상태를 확인한 후 다시 미리보기 하세요."}, ensure_ascii=False))
            return 2

    ctx.register_cli_command("model-router", "Profile model settings and task routing", cli_setup, cli_handler)

    # Observers are inert outside a validated plugin-owned attempt. Registration
    # does not change profile settings or make ordinary requests route-scoped.
    from .model_router.attempt_observer import record_event
    def make_observer(event_name):
        def observer(**payload):
            # Each hook belongs to its loading profile. The observer validates
            # an environment-bound child request, so reject a foreign manager
            # before its own module can record that child's API events.
            bound_home = os.environ.get("HERMES_HOME")
            try:
                if not bound_home or Path(bound_home).resolve(strict=True) != home.resolve(strict=True):
                    return
            except (OSError, RuntimeError):
                return
            token = set_hermes_home_override(home)
            try:
                record_event(event_name, **payload)
            finally:
                reset_hermes_home_override(token)
        return observer
    for event_name in ("pre_api_request", "post_api_request", "api_request_error", "pre_tool_call", "post_tool_call"):
        ctx.register_hook(event_name, make_observer(event_name))

    # Ordinary native delegation has its own opt-in total limit, independent
    # of Heavy/Light routing membership. Never mutate native inactivity config.
    from .model_router.native_watchdog import register_native_watchdog
    register_native_watchdog(ctx, home)

    # Session Fast inheritance is independent of routing opt-in and TOTAL.
    # The controller observes exact native child IDs and rewrites only their
    # supported request payloads; it never edits native agent/config state.
    from .model_router.fast_inheritance import register_fast_inheritance
    fast_controller = register_fast_inheritance(ctx, home)

    from .model_router.native_delegation import register_native_delegation
    register_native_delegation(ctx, home)

    if enabled():
        ctx.register_skill(
            "adaptive-coding-orchestration",
            Path(__file__).parent / "skills/adaptive-coding-orchestration/SKILL.md",
            "Profile-enabled coding and complex non-coding orchestration: Main handles small bounded changes directly; delegate implementation only for worthwhile parallel work; retain required Heavy review.",
        )

    def handler(args, **kwargs):
        try:
            def run(service):
                action = args.get("action")
                if action == "start":
                    return {"error": "start_retired", "message": "New jobs use native delegate_task with an explicitly selected model-router backend; standalone starts are retired."}
                if action == "config":
                    return service.routing_config(service.active_profile())
                if action == "status":
                    return Router(service).status(args.get("job_id", ""))
                if action == "join":
                    if set(args) - {"action", "job_id", "wait_timeout"}:
                        raise ValueError("unsupported join fields; wait_timeout is not a job timeout")
                    from .model_router.runtime_tracking import capture_runtime, route_session_context
                    profile = service.active_profile()
                    with route_session_context(session_id=kwargs.get("session_id", ""), expected_profile=profile):
                        runtime = capture_runtime(task_id=kwargs.get("task_id") or "", expected_profile=profile)
                        return Router(service, runtime=runtime).join(
                            args.get("job_id", ""), wait_timeout=args.get("wait_timeout"))
                raise ValueError("action must be config, status, or join")
            return json.dumps(scoped(run), ensure_ascii=False)
        except (ValueError, PermissionError, KeyError) as exc:
            return json.dumps({"error": "invalid_or_denied", "message": str(exc)}, ensure_ascii=False)
        except Exception:
            return json.dumps({"error": "route_operation_failed", "message": "작업 상태를 확인하세요. 모델 실행/설정 변경은 자동 재시도하지 않습니다."}, ensure_ascii=False)

    schema = {
        "name": "coding_route",
        "description": "Read effective Heavy/Light roles or inspect/join historical process-backed jobs. New work uses native delegate_task with the selected model-router or model-router-profiles backend, never coding_route start. Main handles small bounded changes directly, including tests. Ordinary implementation delegation requires at least two substantive independent workstreams unless explicitly requested by the user; required Heavy/independent review remains mandatory. Read model-router:adaptive-coding-orchestration. config is not proof that this session selected a native backend. Native route reports are runtime-reported identity, not successful-response evidence or semantic GO. This tool never launches work or changes settings.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": ["config", "status", "join"]},
                "wait_timeout": {"type": "integer", "minimum": 1, "description": "Legacy join only: seconds for this bounded wait, never a child's total runtime. Stop/steer interrupts; no automatic rejoin."},
                "job_id": {"type": "string", "description": "Historical process-backed job ID, never a native subagent handle."},
            },
            "required": ["action"],
        },
    }
    # Preserve historical results even when new purpose routing is disabled.
    ctx.register_tool(name="coding_route", toolset="model_router", schema=schema, handler=handler, check_fn=lambda: True)
