"""Authenticated native Desktop backend. Hermes mounts and scopes this router."""
from pathlib import Path
import hashlib
import importlib
import importlib.util
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


def _service():
    # Dashboard API modules load standalone; isolate the package by installed path.
    root = Path(__file__).resolve().parents[1]
    name = "_model_router_backend_" + hashlib.sha256(str(root).encode()).hexdigest()[:12]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, root / "model_router/__init__.py", submodule_search_locations=[str(root / "model_router")])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    cls = importlib.import_module(name + ".service").Service
    return cls()


def _call(operation):
    try:
        return operation(_service())
    except HTTPException:
        raise
    except PermissionError:
        raise HTTPException(403, "현재 대상에 대한 작업이 거절되었습니다.") from None
    except (ValueError, KeyError) as exc:
        # Service validation errors contain only permitted non-secret field values.
        raise HTTPException(400, str(exc)[:400]) from None
    except (RuntimeError, FileNotFoundError):
        raise HTTPException(409, "설정 충돌 또는 초기화되지 않은 상태입니다. 새로고침 후 적용 상태를 확인하세요. 자동 재시도하지 않습니다.") from None
    except Exception:
        # Never forward a CLI traceback/configuration/credential to the renderer.
        raise HTTPException(500, "작업 결과를 확인할 수 없습니다. 새로고침하여 적용 기록을 확인하세요. 자동 재시도하지 않습니다.") from None


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=16, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


@router.get("/status")
def status():
    return _call(lambda service: service.status())


@router.post("/preview")
def preview(body: dict):
    return _call(lambda service: service.preview(body))


@router.post("/fallback-preview")
def fallback_preview(body: dict):
    return _call(lambda service: service.fallback_preview(body))


@router.post("/apply")
def apply(body: ApplyRequest):
    return _call(lambda service: service.apply(body.plan_id))
