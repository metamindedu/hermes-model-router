import pytest
from test_native_service import fixture, body
from model_router import native_service
from model_router.service import RevisionConflict


def test_old_package_refuses_only_new_inheritance_intent(fixture):
    service, calls, writer = fixture
    resolver = service.root / 'plugins/model-router/model_router/role_metadata.py'
    resolver.unlink()
    dto = native_service.status(service, 'default')
    assert dto['role_intro_inheritance']['supported'] is False
    request = body(service, backend='model-router-profiles', profiles={'profiles':[{'name':'p1','description':''}], 'default':None})
    request['updates'][0]['allow_profile_access'] = True
    with pytest.raises(ValueError, match='inheritance'):
        service.delegation_preview(request)
    assert not calls
    request['updates'][0]['profile_routes']['profiles'][0]['description'] = 'manual'
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'
    request = body(service, backend='model-router-profiles', profiles={'profiles':[{'name':'p1','description':''}], 'default':None})
    with pytest.raises(ValueError, match='inheritance'):
        service.delegation_preview(request)
    request = body(service, backend='model-router-profiles')
    assert service.apply(service.delegation_preview(request)['plan_id'])['status'] == 'applied'


def test_feature_replacement_aborts_before_write(fixture):
    service, calls, _ = fixture
    assert native_service.status(service, 'default')['role_intro_inheritance']['supported'] is True
    request = body(service, backend='model-router-profiles', profiles={'profiles':[{'name':'p1','description':''}], 'default':None})
    request['updates'][0]['allow_profile_access'] = True
    plan = service.delegation_preview(request)
    (service.root / 'plugins/model-router/model_router/role_metadata.py').unlink()
    with pytest.raises(RevisionConflict):
        service.apply(plan['plan_id'])
    assert not calls
