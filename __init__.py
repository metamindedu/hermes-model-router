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
        parser.add_argument("operation", choices=["status", "preview", "fallback-preview", "apply"])
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
                if set(body) != {"plan_id"}: raise ValueError("apply accepts only plan_id")
                return service.apply(body["plan_id"])
            result = scoped(operation)
            print("MODEL_ROUTER_JSON:" + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return 0
        except Exception as exc:
            print("MODEL_ROUTER_JSON:" + json.dumps({"error": type(exc).__name__, "message": "작업이 완료되지 않았습니다. 상태를 확인한 후 다시 미리보기 하세요."}, ensure_ascii=False))
            return 2

    ctx.register_cli_command("model-router", "Profile model settings and coding routing", cli_setup, cli_handler)

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

    if not enabled():
        return
    ctx.register_skill(
        "adaptive-coding-orchestration",
        Path(__file__).parent / "skills/adaptive-coding-orchestration/SKILL.md",
        "Profile-enabled coding orchestration: Light implementation, verified Heavy semantic review.",
    )

    def handler(args, **kwargs):
        try:
            def run(service):
                if not service.routing_config(service.active_profile())["enabled"]:
                    return {"error": "routing_disabled", "message": "현재 프로필의 코딩 라우팅이 꺼져 있습니다."}
                action = args.get("action")
                if action == "config":
                    return service.routing_config(service.active_profile())
                router = Router(service)
                if action == "status":
                    return router.status(args.get("job_id", ""))
                if action == "start":
                    allowed = {"action", "purpose", "prompt", "cwd", "timeout"}
                    if set(args) - allowed:
                        raise ValueError("unsupported start fields")
                    return router.start(args.get("purpose"), args.get("prompt"), args.get("cwd"), args.get("timeout", 600))
                raise ValueError("action must be config, start, or status")
            return json.dumps(scoped(run), ensure_ascii=False)
        except (ValueError, PermissionError, KeyError) as exc:
            return json.dumps({"error": "invalid_or_denied", "message": str(exc)}, ensure_ascii=False)
        except Exception:
            return json.dumps({"error": "route_operation_failed", "message": "작업 상태를 확인하세요. 모델 실행/설정 변경은 자동 재시도하지 않습니다."}, ensure_ascii=False)

    schema = {
        "name": "coding_route",
        "description": "Run profile-approved coding routes. Read model-router:adaptive-coding-orchestration first. config reads effective roles; start launches one bounded job; status reads its evidence. implementation/mechanical/preliminary-review use Light; plan/semantic-final/independent-review use Heavy. Disabled profiles are denied. This tool never changes model settings. A verified model identity is not itself a semantic GO.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": ["config", "start", "status"]},
                "purpose": {"type": "string", "enum": ["implementation", "mechanical", "preliminary-review", "plan", "semantic-final", "independent-review"]},
                "prompt": {"type": "string", "description": "Complete bounded handoff; independent review must be read-only."},
                "cwd": {"type": "string", "description": "Existing task workspace."},
                "timeout": {"type": "integer", "minimum": 30, "maximum": 900},
                "job_id": {"type": "string"},
            }, "required": ["action"],
        },
    }
    ctx.register_tool(name="coding_route", toolset="model_router", schema=schema, handler=handler, check_fn=enabled)
