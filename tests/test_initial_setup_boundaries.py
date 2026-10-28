"""Genuine readiness/core config boundaries in credential-free child homes.

The package layout and install record are fixtures, not native admission proof.
Readiness, package inspection, first preview/apply and native enable-tail helpers
are real; no target module is imported and no provider request is made.
"""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import pytest


@pytest.mark.parametrize('case', ['fresh', 'native_toolsets', 'modified_enable', 'modified_select', 'package_race', 'new_executable', 'store_authority', 'pyd_enable', 'pyd_select', 'pyd_race', 'pyd_readback'])
def test_real_initial_setup_boundary(tmp_path, case):
    home = tmp_path/'real-case'; home.mkdir()
    env = dict(os.environ)
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home/'AppData/Local'),
               APPDATA=str(home/'AppData/Roaming'), INITIAL_BOUNDARY_CASE=case, INITIAL_BOUNDARY_REPO=str(Path(__file__).resolve().parents[1]))
    for name in ('LOCALAPPDATA','APPDATA'): Path(env[name]).mkdir(parents=True)
    script = textwrap.dedent(r'''
        from pathlib import Path
        import copy, json, os, shutil, subprocess
        from hermes_constants import get_hermes_home, get_default_hermes_root, set_hermes_home_override, reset_hermes_home_override
        from hermes_cli.config import set_config_value
        from model_router import native_service as native, installation
        from model_router.service import Service, RevisionConflict
        from model_router.yaml_compat import yaml
        root = Path(get_hermes_home())
        assert root.resolve() == Path(get_default_hermes_root()).resolve()
        assert root.name == 'real-case'
        repo = Path(os.environ['INITIAL_BOUNDARY_REPO'])
        case = os.environ['INITIAL_BOUNDARY_CASE']
        files = subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=repo).decode().split('\0')
        base = {'model':{'provider':'openai-codex','default':'offline-fixture'},'agent':{'reasoning_effort':'high'},
                'delegation':{'model':'offline-light','provider':'openai-codex'}, 'plugins':{'enabled':['model-router']},
                'skills':{'disabled':[]}, 'unrelated':{'keep':'opaque'}}
        for name in ('default','target'):
            home = root if name == 'default' else root/'profiles'/name
            home.mkdir(parents=True,exist_ok=True)
            cfg = copy.deepcopy(base)
            if name == 'target' and case in ('native_toolsets','modified_enable','pyd_enable'): cfg['plugins']['enabled']=[]
            if name == 'target' and case == 'native_toolsets': cfg['platform_toolsets']={'cli':['terminal','file']}
            (home/'config.yaml').write_text(yaml.safe_dump(cfg),encoding='utf-8')
            package = home/'plugins/model-router'; package.mkdir(parents=True)
            for relative in filter(None,files):
                if relative.startswith(('tests/','.github/','docs/')): continue
                destination=package/relative; destination.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(repo/relative,destination)
            (home/'plugins/.install-metadata.json').write_text(json.dumps({'model-router':{'revision':'b'*40,'source':'https://github.com/metamindedu/hermes-model-router','pinned':True}}))
        writes=[]
        service = None
        def writer(profile,key,value):
            assert key == 'delegation.backend' and value == 'model-router-auto'
            home = root if profile == 'default' else root/'profiles'/profile
            token = set_hermes_home_override(home)
            try: set_config_value(key,value)
            finally: reset_hermes_home_override(token)
            writes.append((profile,key,value))
            if case == 'pyd_readback':
                (home/'plugins/model-router/model_router/fast_inheritance.pyd').write_bytes(b'non-runnable fixture native module')
        service=Service(root=root,writer=writer)
        target=root/'profiles/target'; package=target/'plugins/model-router'
        def dto(name='default'): return native.initial_setup_status(service,name)
        def request(name='default'):
            return {'expected_revision':0,'expected_root_identity':installation._root_identity(root),
                    'updates':[{'profile':name,'expected_digest':dto(name)['digest']}]}
        def config(name='default'):
            return yaml.safe_load(((root if name=='default' else target)/'config.yaml').read_text())
        assert not service._lock_path.parent.exists()
        if case == 'fresh':
            before=config(); status=dto()
            assert status['action']=='select_backend',status
            assert not service._lock_path.parent.exists(), 'status must not create service data'
            plan=service.initial_setup_preview(request())
            assert service.apply(plan['plan_id'])['status']=='applied'
            before['delegation']['backend']='model-router-auto'
            assert config()==before and len(writes)==1 and not service.store_path.exists()
            from hermes_cli.plugins import get_plugin_manager
            from tools.registry import registry
            from tools import delegate_tool  # bootstrap the genuine core tool registration
            manager=get_plugin_manager(); manager.discover_and_load()
            assert manager._plugins['model-router'].enabled and not manager._plugins['model-router'].error
            definition=registry.get_definitions({'delegate_task'})[0]['function']
            parameters=definition['parameters']['properties']['tasks']['items']['properties']
            assert parameters['execution']['enum']==['model'] and 'purpose' in parameters
            assert 'profile' not in parameters, 'initial setup must not grant other profiles'
            manager.unload()
        elif case == 'native_toolsets':
            status=dto('target')
            assert status['action']=='manual' and status['reason_codes']==['native_enable_changes_tool_selection'],status
            before=config('target')
            from hermes_cli.plugins_cmd import _toggle_plugin_toolset
            token=set_hermes_home_override(target)
            try: _toggle_plugin_toolset('model-router',enable=True,toolset_key='model_router')
            finally: reset_hermes_home_override(token)
            after=config('target')
            assert after['platform_toolsets']['cli']==['terminal','file','model_router']
            assert native._initial_intent(before)!=native._initial_intent(after), 'do not erase toolsets from preservation'
            # Once the user has separately permitted the owned toolset, genuine
            # native enable-tail execution is a no-op and its selection delta is
            # compatible with the frozen setup intent.
            permitted=dto('target')
            assert permitted['action']=='enable',permitted
            saved=(target/'config.yaml').read_bytes()
            token=set_hermes_home_override(target)
            try:
                _toggle_plugin_toolset('model-router',enable=True,toolset_key='model_router')
                assert (target/'config.yaml').read_bytes()==saved
                set_config_value('plugins.enabled',json.dumps(['model-router']))
            finally: reset_hermes_home_override(token)
            enabled=dto('target')
            assert enabled['action']=='select_backend' and enabled['intent_digest']==permitted['intent_digest'],enabled
            a={'plugins':{'enabled':['z','a','z'],'disabled':['other']}}
            b={'plugins':{'enabled':['model-router','a','z'],'disabled':['other']}}
            assert native._initial_intent(a)==native._initial_intent(b)
            b['plugins']['enabled'].append('unapproved-other')
            assert native._initial_intent(a)!=native._initial_intent(b)
            assert not writes
        elif case in ('modified_enable','modified_select'):
            assert dto('target')['action']==('enable' if case=='modified_enable' else 'select_backend'),dto('target')
            for filename in ['model_router/native_watchdog.py','model_router/fast_inheritance.py','model_router/routing.py','lib/run_routed_agent.py']:
                path=package/filename; old=path.read_bytes()
                path.write_bytes(old+b'\nraise RuntimeError("fixture custom code must never execute")\n')
                status=dto('target')
                assert status['action']=='manual' and not status['eligible'],(filename,status)
                path.write_bytes(old)
            assert not writes
        elif case == 'package_race':
            plan=service.initial_setup_preview(request('target'))
            path=package/'model_router/fast_inheritance.py';path.write_bytes(path.read_bytes()+b'\n# local package changed after preview\n')
            try: service.apply(plan['plan_id'])
            except RevisionConflict: pass
            else: raise AssertionError('changed package was accepted')
            assert not writes and 'backend' not in config('target')['delegation']
        elif case == 'new_executable':
            path=package/'user-added.py';path.write_text('raise RuntimeError("never import")')
            assert dto('target')['action']=='manual' and path.exists() and not writes
        elif case.startswith('pyd_'):
            from importlib.machinery import FileFinder, ExtensionFileLoader, SourceFileLoader, EXTENSION_SUFFIXES, SOURCE_SUFFIXES
            filename='native_delegation' if case=='pyd_enable' else 'fast_inheritance'
            path=package/'model_router'/(filename+EXTENSION_SUFFIXES[0])
            baseline=dto('target')
            assert baseline['action']==('enable' if case=='pyd_enable' else 'select_backend'),baseline
            plan=service.initial_setup_preview(request('target')) if case in ('pyd_race','pyd_readback') else None
            if case != 'pyd_readback':
                path.write_bytes(b'non-runnable fixture native module')
                spec=FileFinder(str(package/'model_router'),(ExtensionFileLoader,EXTENSION_SUFFIXES),(SourceFileLoader,SOURCE_SUFFIXES)).find_spec(filename)
                assert isinstance(spec.loader,ExtensionFileLoader) and Path(spec.origin)==path
            if case=='pyd_race':
                try: service.apply(plan['plan_id'])
                except RevisionConflict: pass
                else: raise AssertionError('native module added after preview was accepted')
                assert not writes and 'backend' not in config('target')['delegation']
            elif case=='pyd_readback':
                assert service.apply(plan['plan_id'])['status']=='partial'
                assert len(writes)==1 and config('target')['delegation']['backend']=='model-router-auto'
            else:
                status=dto('target')
                assert status['action']=='manual' and not status['eligible'] and path.exists() and not writes,status
        else:
            first=installation.profile_readiness(service,'default',None)
            service.store_path.parent.mkdir(parents=True)
            assert installation.profile_readiness(service,'default',None)['identity']==first['identity']
            service.store_path.write_text('{}')
            assert installation.profile_readiness(service,'default',None)['identity']!=first['identity']
            service.store_path.unlink(); service.store_path.parent.rmdir(); service.store_path.parent.parent.rmdir()
            (root/'plugin-data').write_text('not a directory')
            status=dto()
            assert status['action']=='manual' and not status['eligible'] and not writes,status
        print('real_boundary_'+case+'=PASS')
    ''')
    result = subprocess.run([sys.executable,'-B','-c',script],cwd=Path(__file__).resolve().parents[1],env=env,
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
    assert result.returncode == 0, result.stderr.decode('utf-8',errors='replace')[-4500:]
    assert ('real_boundary_'+case+'=PASS').encode() in result.stdout
