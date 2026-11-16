#!/usr/bin/env python3
"""Black-box local-path and companion-argument checks; no server, model or corpus download."""
from pathlib import Path
import json,os,subprocess,tempfile

REPO=Path(__file__).resolve().parents[2];TEMP=REPO/'.runtime/launcher-tests';TEMP.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='paths-',dir=TEMP) as directory:
    fixture=Path(directory);root=fixture/'workspace with spaces';root.mkdir();outside=fixture/'outside';outside.mkdir()
    env=dict(os.environ)
    for k in ['AIJADE_ARTIFACTS','AIJADE_DATA_DIR','AIJADE_LOCAL_ENV_READY','AIJADE_SERVICE_STATE_ROOT','AIJADE_RUNTIME_ROOT']:env.pop(k,None)
    env['AIJADE_WORKSPACE_ROOT']=str(root)
    helper=REPO/'tools/with-workspace-env.sh';checks=[]
    code='import json,os; print(json.dumps({k:os.environ[k] for k in ["AIJADE_WORKSPACE_ROOT","AIJADE_ARTIFACTS","AIJADE_DATA_DIR","TMPDIR","NUGET_PACKAGES","DOTNET_CLI_HOME","COLIMA_HOME","LIMA_HOME"]}))'
    def run(name,extra,want):
        result=subprocess.run([str(helper),'python3','-c',code],cwd=REPO,env=dict(env,**extra),capture_output=True,text=True)
        assert result.returncode==want,(name,result.stdout,result.stderr);checks.append(name);return result
    result=run('default-contained-paths',{},0)
    assert all(Path(p).is_relative_to(root) for p in json.loads(result.stdout).values())
    assert all(Path(json.loads(result.stdout)[key]).is_dir() for key in ['COLIMA_HOME','LIMA_HOME']);checks.append('service-directories-exist-before-command')
    result=run('explicit-contained-service-state',dict(AIJADE_SERVICE_STATE_ROOT=str(root/'native state')),0)
    assert json.loads(result.stdout)['COLIMA_HOME']==str(root/'native state/colima')
    run('outside-service-state-refused',dict(AIJADE_SERVICE_STATE_ROOT=str(outside/'service')),64);assert not (outside/'service').exists()
    run('outside-native-runtime-refused',dict(AIJADE_RUNTIME_ROOT=str(outside/'native')),64);assert not (outside/'native').exists()
    result=run('explicit-contained-paths',dict(AIJADE_ARTIFACTS=str(root/'custom build'),AIJADE_DATA_DIR=str(root/'custom data')),0)
    assert json.loads(result.stdout)['AIJADE_DATA_DIR']==str(root/'custom data')
    run('outside-override-refused',dict(AIJADE_ARTIFACTS=str(outside/'build')),64);assert not (outside/'build').exists()
    run('parent-traversal-refused',dict(AIJADE_DATA_DIR=str(root)+'/../outside/data'),64);assert not (outside/'data').exists()
    (root/'link').symlink_to(outside,target_is_directory=True)
    run('symlink-escape-refused',dict(AIJADE_DATA_DIR=str(root/'link/data')),64);assert not (outside/'data').exists()
    run('service-symlink-escape-refused',dict(AIJADE_SERVICE_STATE_ROOT=str(root/'link/service')),64);assert not (outside/'service').exists()
    stub=fixture/'dotnet-stub';stub.write_text('#!/usr/bin/env python3\nimport json,os,sys\nif sys.argv[1:]==["--version"]:print("10.0.403")\nelse:print(json.dumps({"args":sys.argv[1:],"temporary":os.environ["TMPDIR"]}))\n');stub.chmod(0o755)
    result=subprocess.run([str(REPO/'tools/run-companion.sh'),'--urls','http://127.0.0.1:5137'],cwd=REPO,
        env=dict(env,AIJADE_DOTNET_BIN=str(stub)),capture_output=True,text=True)
    assert result.returncode==0,result.stderr;actual=json.loads(result.stdout)
    assert actual['args']==['run','--project','src/Aijade.Server','-c','Release','--no-launch-profile','--','--Aijade:Profile=companion','--urls','http://127.0.0.1:5137']
    assert Path(actual['temporary']).is_relative_to(root);checks.append('companion-argument-forwarding')
print(json.dumps(dict(status='PASS',checks=checks,total=len(checks),scope='Launcher configuration only; no live companion/QQ or model measurement.')))
