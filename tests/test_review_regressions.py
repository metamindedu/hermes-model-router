import copy
import json
from pathlib import Path
import os
import shutil
import subprocess

import pytest
import yaml

from model_router.service import Service
from test_integration import make_home, writer, payload


@pytest.mark.parametrize('role', ['delegation', 'compression', 'title'])
def test_main_change_preserves_approved_inherited_role(tmp_path, role):
    root = make_home(tmp_path)
    file = root / 'config.yaml'
    data = yaml.safe_load(file.read_text())
    if role == 'delegation':
        data['delegation'] = {'provider':'', 'model':'', 'reasoning_effort':''}
    else:
        data['auxiliary']['compression' if role=='compression' else 'title_generation'] = {'provider':'auto', 'model':'', 'reasoning_effort':''}
    file.write_text(yaml.safe_dump(data), encoding='utf-8')
    service = Service(root, writer(root)); service.initialize([])
    body = payload(service); body['routing_profiles'] = []; body['routing']['enabled'] = False
    desired_role = copy.deepcopy(body['models'][role])
    body['model_targets'] = ['default']
    body['models']['main'] = {'provider':'openai-api', 'model':'new-main', 'reasoning':'xhigh'}
    plan = service.preview(body)
    assert service.apply(plan['plan_id'])['status'] == 'applied'
    row = service.status()['profiles'][0]
    assert row['actual_models'][role] == desired_role
    assert row['actual_models'] == row['models']


def test_native_plugin_cli_transport_in_isolated_home(tmp_path):
    launcher = Path(os.environ.get('LOCALAPPDATA','')) / 'hermes/bin/hermes.exe'
    if not launcher.is_file(): pytest.skip('local Windows Hermes launcher unavailable')
    root = make_home(tmp_path)
    package = Path(__file__).resolve().parents[1]
    target = root / 'plugins/model-router'
    target.mkdir(parents=True)
    for name in ['plugin.yaml','__init__.py','model_router','skills']:
        source = package / name
        if source.is_dir(): shutil.copytree(source,target/name,ignore=shutil.ignore_patterns('__pycache__'))
        else: shutil.copy2(source,target/name)
    config = root/'config.yaml'
    data = yaml.safe_load(config.read_text()); data['plugins']={'enabled':['model-router']}
    config.write_text(yaml.safe_dump(data),encoding='utf-8')
    env=dict(os.environ,HERMES_HOME=str(root));env.pop('HERMES_PROFILE',None)
    result=subprocess.run([str(launcher),'--profile','default','model-router','status'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40)
    assert result.returncode==0,result.stderr
    line=next(v for v in result.stdout.splitlines() if v.startswith('MODEL_ROUTER_JSON:'))
    response=json.loads(line.split(':',1)[1])
    assert response['current_profile']=='default'
    assert response['profiles'][0]['actual_models']['main']['model']=='heavy-test'
