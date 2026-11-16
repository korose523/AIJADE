from pathlib import Path
from datetime import datetime,timezone
import hashlib,importlib.util,json,os,shutil,subprocess
C=Path(__file__).resolve().parent;BASE=Path("/Volumes/Untitled/AIJADE");TARGET=C/"prepared-renderer";DOTNET=Path("/Users/mac/.dotnet/dotnet")
p=TARGET/"scripts/run-native-mmd-scene.py";original=(C/"original-renderer-launcher.py").read_bytes()
env=dict(os.environ,DOTNET_ROOT=str(DOTNET.parent),DOTNET_PROCESSOR_COUNT='2',DOTNET_CLI_USE_MSBUILD_SERVER='0',MSBUILDDISABLENODEREUSE='1',UseSharedCompilation='false')
with (C/'renderer-prebuild-native-cache.log').open('x') as log:
    r=subprocess.run([str(DOTNET),'build',str(TARGET/'clients/godot-scene/MosaicScene.csproj'),'--nologo','--no-incremental','-p:Optimize=true','-p:UseSharedCompilation=false','--disable-build-servers'],cwd=TARGET,env=env,stdout=log,stderr=subprocess.STDOUT)
assert r.returncode==0,'renderer prebuild failed; original output retained'
spec=importlib.util.spec_from_file_location('prepared_renderer_launcher',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
stamp=dict(sources_sha256=module.client_sources_sha256(True,DOTNET),dlls=module.loaded_client_dlls())
assert stamp['dlls'];module.CLIENT_BUILD_STAMP.parent.mkdir(parents=True,exist_ok=True);module.CLIENT_BUILD_STAMP.write_text(json.dumps(stamp,indent=1)+'\n')
sha=lambda q:hashlib.sha256(q.read_bytes()).hexdigest()
authored={str(q.relative_to(TARGET)):sha(q) for q in TARGET.rglob('*') if q.is_file() and not {'.godot','bin','obj','__pycache__'}&set(q.relative_to(TARGET).parts)}
binary={str(q.relative_to(TARGET)):sha(q) for q in module.CLIENT_DLLS.iterdir() if q.is_file()}
marker=dict(status='PREBUILT_NO_RUNTIME_REBUILD',preparedAt=datetime.now(timezone.utc).isoformat(),files=dict(authored,**binary),
            originalLauncherSha256=hashlib.sha256(original).hexdigest(),patchedLauncherSha256=sha(p),
            adjustment='Only refuse automatic rebuild in the explicit prebuilt mode; installed Godot/log sandbox are supplied separately. Client C# and renderer logic unchanged.',sdk=str(DOTNET))
(TARGET/'aijade-prepared-renderer.json').write_text(json.dumps(marker,indent=2)+'\n')
(C/'renderer-preparation.json').write_text(json.dumps(marker,indent=2)+'\n')
print(json.dumps(dict(status=marker['status'],authoredFiles=len(authored),binaryFiles=len(binary))))
