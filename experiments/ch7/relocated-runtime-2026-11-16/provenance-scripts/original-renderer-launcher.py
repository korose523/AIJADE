#!/usr/bin/env python3
"""Run the optional native diagnostic without loading research dependencies."""
import argparse
import hashlib
import math
import os
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# The furnished home exported from Blender (tools/build_home_blender.py export_gltf); a local file, not in SVN.
DEFAULT_HOME_MODEL = ROOT/'artifacts/blender-home/home-v1-cozy.glb'

NOT_FOR_BULLET=('wall','rug','decor','pool','hoop')


def home_bullet_scene(layout):
    """The home's furniture as Bullet's scene: mosaic.embodiment.home.Home.static_scene() without importing it (walls,
    rugs, decoration, the pool and the hoop left out); the movable pieces' boxes name them (movable_item), and the client
    moves them with the furniture each step (r448); each box carries its material's friction and restitution
    (configs/scenes/materials-v1.json: the part's material, else the item's, else by its kind)."""
    table=json.loads((ROOT/'configs/scenes/materials-v1.json').read_text(encoding='utf-8'))
    made=lambda item,p:table['materials'][p.get('material') or item.get('material') or table['by_kind'].get(item.get('kind'),'wood')]
    boxes=[dict(name=f"{item['name']}-{k}",center_m=p['center'],half_extents_m=p['half'],**({'movable_item':item['name']} if item.get('movable') else {}),
                friction=made(item,p)['friction'],restitution=made(item,p)['restitution'])
           for item in layout['items'] if item.get('kind') not in NOT_FOR_BULLET for k,p in enumerate(item['parts'])]
    if len(boxes)>64: raise SystemExit(f'{len(boxes)} home furniture boxes: Bullet takes at most 64')
    return dict(schema='mosaic-bullet-static-scene-v1',coordinate_system='world-metres-right-handed',boxes=boxes)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--godot', type=Path, default=Path.home()/'.local/share/mosaic/godot-4.5.2/Godot_mono.app/Contents/MacOS/Godot')
    parser.add_argument('--dotnet', type=Path, default=Path.home()/'.dotnet/dotnet')
    parser.add_argument('--force-build', action='store_true', help='Rebuild the client even if the build stamp shows nothing changed')
    parser.add_argument('--optimize-managed', action=argparse.BooleanOptionalAction, default=True,
                        help='Optimize managed client and Core assemblies in the Godot Debug output location; --no-optimize-managed retains debugger-friendly code')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--pmx', type=Path)
    parser.add_argument('--scale', type=float, help='Explicit meters per PMX unit; required with --pmx')
    parser.add_argument('--clip', type=Path, help='PMX-bound JSON clip or VMD 0002; VMD requires --pose-mode pmx')
    parser.add_argument('--preserve-signed-linear-weights', action='store_true', help='Explicit authored BDEF extrapolation diagnostic, never a weight repair')
    parser.add_argument('--pose-mode',choices=['fk','pmx'],default='fk',help='PMX candidate executes append/fixed-axis; CCD only for pmx-ccd clips')
    parser.add_argument('--timeout',type=float,help='Explicit diagnostic wall timeout in seconds; does not accept performance')
    parser.add_argument('--live-endpoint',help='Explicit loopback /mmd/latest; requires --interactive, --pmx and --pose-mode pmx')
    parser.add_argument('--live-duration',type=float,help='Bounded wall duration for live qualification, <=60 seconds')
    parser.add_argument('--interactive',action='store_true',help='Native keyboard play/pause/seek/rewind/release viewer')
    parser.add_argument('--realtime',action='store_true',help='Use wall-clock playback instead of the diagnostic fixed-fps clock; requires --interactive')
    parser.add_argument('--commands',type=Path,help='Deterministic interactive command plan for acceptance')
    parser.add_argument('--behavior',type=Path,help='Companion behaviour plan (mosaic-companion-behavior-plan-v1): mouth/blink/gaze/beat overlay; requires --clip or --live-endpoint')
    parser.add_argument('--loop',action='store_true',help='Loop the clip (idle motion) in interactive playback')
    parser.add_argument('--background',type=Path,help='Local stage background picture (PNG/JPG/WebP)')
    parser.add_argument('--live-idle-fallback',action='store_true',help='Live mode: fall back to the looping clip (idle) instead of rest when live input lapses')
    parser.add_argument('--live-smoothing',help='One Euro smoothing of live poses: MIN_CUTOFF_HZ,BETA (e.g. 1.0,0.5)')
    parser.add_argument('--mmd-edges',type=float,metavar='PX',help='MMD outline pass (needs --mmd-shading): pixels per PMX edge-size unit, (0, 16]')
    parser.add_argument('--mmd-edge-sign',type=int,choices=[1,-1],default=1,help='Outline push direction (render check pending)')
    parser.add_argument('--gaze-camera',action='store_true',help='Companion eyes (and head share from the plan channel head_follow) follow the camera; needs --behavior')
    parser.add_argument('--physics-wind',help='Wind for --physics: X,Y,Z PMX units/s² in model space, optionally ,GUST_AMPLITUDE,GUST_HZ')
    parser.add_argument('--physics-follow',type=float,metavar='FRACTION',help='Approximate --physics: pull dynamic bodies toward the clip pose of their bones by this fraction per substep (0-1; e.g. a skirt flared over raised thighs)')
    parser.add_argument('--physics-model',type=Path,help='Learned world model weights (tools/mmd_world_model/train.py weights.json); replaces the approximate solver')
    parser.add_argument('--physics-model-fallback',type=int,default=3,help='Switch from the learned model to the approximate solver after this many divergence resets')
    parser.add_argument('--physics-backend',choices=['approx','bullet'],default='approx',help='Optional actual Bullet reference runtime; learned weights remain selected via --physics-model')
    parser.add_argument('--bullet-node',type=Path,help='Node executable for the explicit Bullet backend')
    parser.add_argument('--bullet-ammo-dir',type=Path,help='Directory containing the verified ammo.wasm.js and ammo.wasm.wasm')
    parser.add_argument('--bullet-scene',type=Path,help='Static scene JSON: shared world-metre boxes rendered by Godot and colliding in Bullet')
    parser.add_argument('--bullet-allow-initial-overlap',action='store_true',help='Allow a starting or reset character pose that overlaps the static scene (the live scene: she sits touching the furniture when a clip resets physics; Windows 2026-11-02 the scene exited); rejection is the default')
    parser.add_argument('--model-position',nargs=3,type=float,metavar=('X','Y','Z'),help='Place the character at world coordinates in metres')
    parser.add_argument('--model-yaw',type=float,metavar='DEG',help='Turn the placed character about +y (0 faces +z, 90 faces +x)')
    parser.add_argument('--home',type=Path,help='The companion\'s home (mosaic-home-v1, configs/scenes/home-v1.json): rooms and furniture drawn around her; without --model-position she starts at its start')
    parser.add_argument('--home-model',type=Path,help='With --home: the furnished home as a binary glTF drawn instead of the layout boxes (default artifacts/blender-home/home-v1-cozy.glb when it exists; "none" draws the boxes)')
    parser.add_argument('--physics',action='store_true',help='Approximate PMX rigid-body physics for hair/skirt bones (position-based, not Bullet; needs --pose-mode pmx)')
    parser.add_argument('--control-port',type=int,metavar='PORT',help='Live playback control on 127.0.0.1:PORT (one JSON object per UDP datagram: play/pause/rewind/release/seek/snapshot); the client writes live-status.json every 0.5 s; requires --interactive --realtime and --clip')
    parser.add_argument('--companion-worker',metavar='JSON',help='With --control-port and --home: the companion\'s controller worker as a JSON list [program, args...] (tools/live_controller.py serve, docs/COMPANION-ARCHITECTURE-2026-10-30.md); the client starts it, adds where she stands (--placement) and shows the frame it gives each tick; the "agent" control passes the owner\'s words to it')
    parser.add_argument('--clip-fade',type=float,metavar='SECONDS',help='Crossfade when the "clip" control switches clips (0-2 s; client default 0.4; 0 cuts and resets physics)')
    parser.add_argument('--live-preview-ms',type=int,metavar='MS',help='With --control-port on a rendered run: write a downscaled preview.jpg every MS milliseconds (100-5000) for the workbench, without pausing the scene')
    parser.add_argument('--behavior-live',type=int,metavar='PORT',help='Also accept live behaviour events (one JSON event per UDP datagram) on 127.0.0.1:PORT, e.g. from tools/companion_events.py; writes behavior-live-replay.json; needs --behavior')
    parser.add_argument('--toon-rim',type=float,help='Anime-style rim light strength 0-2 for --mmd-shading (default off; not part of MMD)')
    parser.add_argument('--mmd-self-shadow',action='store_true',help='MMD self-shadow from a camera-attached light (needs --mmd-shading; default off)')
    parser.add_argument('--trace',choices=['full','light','off'],default='full',help='Per-frame skinning trace: full (default, ArrayMesh buffer readback for CPU skinning; no vertex-shader output readback), light (no mesh-buffer readback), off (long companion sessions)')
    parser.add_argument('--gpu-skinning',action='store_true',help='Vertex-shader skinning (needs --mmd-shading and --pose-mode pmx; falls back to CPU with a reason in playback.json)')
    parser.add_argument('--msaa',type=int,choices=[2,4,8],help='Multisample anti-aliasing for rendered runs (default off)')
    parser.add_argument('--ground-blob',action='store_true',help='A soft contact shadow under her feet on the Compatibility renderer (the live scene; Forward+ draws her real shadow)')
    parser.add_argument('--renderer',choices=['compatibility','forward_plus'],default='compatibility',
                        help='Godot renderer of a rendered run: compatibility (OpenGL, the qualified evidence renderer, default) or forward_plus '
                             '(Vulkan/D3D12: her shadow on the floor and furniture, the lamps\' shadows, ambient occlusion, glow; the live scene on a '
                             'capable GPU, owner 2026-11-02 "继续优化Windows端渲染"). Not with --aux-outputs, qualified on Compatibility only')
    parser.add_argument('--write-movie',type=Path,help='Record every rendered frame with Godot Movie Maker (MJPEG .avi) at 30 fps, one frame per clip frame in diagnostic playback; rendered, non-interactive runs only')
    parser.add_argument('--snapshots',metavar='SECONDS',help='Comma-separated times (s) for review PNGs snap-tNNNNNN.png (240 Hz ticks; rendered runs only; at most 64)')
    parser.add_argument('--auto-camera',action='store_true',help='Automatic camera direction from the behaviour state (close-up on speech, orbit on energy, idle drift and wide shots); needs --behavior')
    parser.add_argument('--camera-motion',type=Path,help='VMD with camera keys driving the view (overrides --frame-head)')
    parser.add_argument('--frame-head',action='store_true',help='Frame head and shoulders from the model bones (頭/上半身) instead of the fixed overview camera')
    parser.add_argument('--eye-self-shadow',action='store_true',help='With --mmd-self-shadow, let eye materials receive self-shadow as authored (default: eyes exempt, toon convention)')
    parser.add_argument('--joint-limits',action='store_true',help='Human range-of-motion guard on FK input rotations (elbow/knee hinges, hip adduction, spine/neck/wrist/ankle ranges); requires --pose-mode pmx')
    parser.add_argument('--self-collision',action='store_true',help='Keep the arms out of the body and out of each other (capsules sized from the skin; the shoulder turns out of contact); requires --pose-mode pmx')
    parser.add_argument('--plant-feet',action='store_true',help='Keep both feet planted: leg IK on with controllers at rest (captured clips have no root motion or contact); requires --pose-mode pmx')
    parser.add_argument('--frame-stage',type=float,metavar='HALF_WIDTH_M',help='Elevated view of a floor square of ±HALF_WIDTH_M metres around the start (locomotion review)')
    parser.add_argument('--clean-stage',action='store_true',help='Hide the diagnostic marker mesh and gravity sphere (their physics and diagnostics still run); for product renders and video capture')
    parser.add_argument('--frame-body',action='store_true',help='Frame the whole body (頭 to floor, 30° lens) for kinematics review instead of the fixed overview camera')
    parser.add_argument('--camera-azimuth',type=float,metavar='DEG',help='Turn the framed camera this many degrees about the vertical through its target (-180..180; with --frame-head, --frame-body or --frame-stage): e.g. 180 to see the front of a seat the framing shows from behind')
    parser.add_argument('--camera-follow',action='store_true',help='With --frame-body or --frame-head: the camera follows the character horizontally (smoothed root bone) when clips carry it away, e.g. walking switched in with the "clip" control')
    parser.add_argument('--live-fade',type=float,default=0.,help='Cross-fade seconds between live and idle (0 keeps immediate switching)')
    parser.add_argument('--mmd-shading',action='store_true',help='MMD toon/sphere materials (fixed view-space light; shared toon = generated ramp)')
    parser.add_argument('--render-style', choices=['diagnostic', 'mmd'], default='diagnostic',
                        help='Shared Mac/Windows render defaults; mmd enables toon, 1px outlines, MSAA 4x, rim 0.4 and self-shadow. Config and explicit flags override style values.')
    parser.add_argument('--aux-outputs',action='store_true',help='Also write normal.png, depth.png and camera.json at the terminal frame')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--config',type=Path,help='JSON option defaults (keys = option names with underscores, e.g. "mmd_edges"); paths are relative to the file; command-line flags override; "out" is not allowed')
    return parser

# Keys of the Windows qualification config (tools/migration/qualify_nonresearch_windows.py) that are not launcher options,
# so the same file can be passed as --config (2026-10-23 Windows report: it was rejected for these).
QUALIFICATION_ONLY_KEYS = {'capture_python', 'p3video_landmarks', 'pose_model', 'pose_model_sha256'}
BULLET_KEYS = {'bullet_node', 'bullet_ammo_dir', 'bullet_scene'}


def parse_with_config(parser, argv=None):
    """Apply a JSON config as parser defaults, then parse the command line (which overrides the config). The qualification
    config (recognised by its qualification-only keys) can be passed as is: those keys are ignored, and its Bullet paths are
    used only when the Bullet backend is requested. Any other config must carry launcher options only, Bullet options
    only with the Bullet backend."""
    pre=argparse.ArgumentParser(add_help=False,allow_abbrev=False);pre.add_argument('--config',type=Path)
    pre.add_argument('--render-style', choices=['diagnostic', 'mmd']);pre.add_argument('--physics-backend');known,_=pre.parse_known_args(argv)
    config = {}
    if known.config:
        try: config=json.loads(known.config.read_text(encoding='utf-8'))
        except (OSError,ValueError) as error: parser.error(f'--config unreadable: {error}')
        if isinstance(config,dict) and QUALIFICATION_ONLY_KEYS & set(config):   # the qualification config, recognised by its own keys
            config={k:v for k,v in config.items() if k not in QUALIFICATION_ONLY_KEYS}
            if (known.physics_backend or config.get('physics_backend'))!='bullet': config={k:v for k,v in config.items() if k not in BULLET_KEYS}
        actions={a.dest:a for a in parser._actions if a.dest not in ('help','config','out')}
        if not isinstance(config,dict) or set(config)-set(actions): parser.error(f'--config has unknown keys: {sorted(set(config)-set(actions)) if isinstance(config,dict) else config!r}')
        base=known.config.resolve().parent;defaults={}
        for key,value in config.items():
            if actions[key].type is Path and isinstance(value,str): value=str((base/value).resolve()) if not Path(value).is_absolute() else value
            defaults[key]=value
        config = defaults
    style = known.render_style if known.render_style is not None else config.get('render_style', 'diagnostic')
    styles = json.loads((ROOT / 'configs/scenes/render-styles.json').read_text(encoding='utf-8'))
    if not isinstance(style, str) or style not in styles:
        parser.error('--config render_style must be diagnostic or mmd')
    parser.set_defaults(**{**styles[style], **config, 'render_style': style})
    return parser.parse_args(argv)

CLIENT_BUILD_STAMP = ROOT/'clients/godot-scene/.godot/mono/mosaic-build-stamp.json'
CLIENT_DLLS = ROOT/'clients/godot-scene/.godot/mono/temp/bin/Debug'


def client_sources_sha256(optimize, dotnet):
    """Everything the client build reads (C# sources and project files of the client and host-dotnet, the shared props
    and global.json) plus the requested optimisation and SDK, as one SHA-256."""
    h = hashlib.sha256()
    files = [p for base in (ROOT/'clients/godot-scene', ROOT/'host-dotnet') for p in base.rglob('*')
             if p.is_file() and p.suffix in ('.cs', '.csproj', '.props', '.targets')
             and not {'bin', 'obj', '.godot'} & set(p.relative_to(base).parts)]
    files += [p for p in (ROOT/'Directory.Build.props', ROOT/'global.json') if p.is_file()]
    for f in sorted(files):
        h.update(str(f.relative_to(ROOT)).encode('utf-8') + b'\0' + f.read_bytes() + b'\0')
    h.update(f'optimize={bool(optimize)};dotnet={Path(dotnet).resolve()}'.encode('utf-8'))
    return h.hexdigest()


def loaded_client_dlls():
    """SHA-256 of every assembly Godot loads for the client."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(CLIENT_DLLS.glob('*.dll'))} if CLIENT_DLLS.is_dir() else {}


def client_build_needed(sources, saved, dlls):
    """A build is skipped only when the sources, optimisation and SDK match the last launcher build and the loaded
    assemblies are byte-identical to what that build produced (a test build that swapped in an unoptimised Core DLL,
    the reason for --no-incremental, changes these hashes and forces the rebuild)."""
    return not (isinstance(saved, dict) and dlls and saved.get('sources_sha256') == sources and saved.get('dlls') == dlls)


def validate_explicit_root_launch(args, clip):
    provenance = clip.get('provenance', {})
    # Both explicit static plans and contact-derived roots (mosaic.mmd.contact_root) bind a fixed origin and scale.
    if provenance.get('root_plan_kind') not in ('explicit-static-xz-translation', 'contact-derived-xz-translation', 'ground-truth-xz-translation', 'video-estimated-xz-translation'):
        return
    if args.pose_mode != 'pmx' or args.plant_feet or args.live_endpoint or args.loop:
        raise ValueError('Explicit root plan requires PMX playback without planted feet, live takeover or looping')
    if args.model_position is None:
        raise ValueError('Explicit root plan requires --model-position to bind the fixed world origin')
    origin = provenance.get('model_origin_world_xz_m')
    scale = provenance.get('metres_per_pmx_unit')
    if (not isinstance(origin, list) or len(origin) != 2 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in origin) or
            isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0):
        raise ValueError('Explicit root plan requires valid origin and scale provenance')
    if args.scale != scale or [args.model_position[0], args.model_position[2]] != origin:
        raise ValueError('Explicit root plan origin/scale differs from the native instance')


def main(argv=None):
    parser=build_parser()
    args = parse_with_config(parser, argv)
    if args.realtime and not args.interactive: parser.error('--realtime requires --interactive')
    if args.timeout is not None and not 0 < args.timeout < float('inf'): parser.error('--timeout must be finite and positive')
    if args.out.exists(): parser.error('--out must not exist')
    if args.pmx and (args.scale is None or not 0 < args.scale < float('inf')): parser.error('--pmx requires a finite positive --scale')
    if not args.godot.is_file() or not args.dotnet.is_file(): parser.error('Verified Godot .NET 4.5.2 and .NET 8 are required; see client README')
    env = os.environ.copy()
    # Clear optional model inputs inherited from a different run.
    for name in ['MOSAIC_PMX_PATH','MOSAIC_PMX_SCALE','MOSAIC_MOTION_CLIP','MOSAIC_PRESERVE_SIGNED_LINEAR','MOSAIC_POSE_MODE','MOSAIC_PLAYBACK_INTERACTIVE','MOSAIC_PLAYBACK_COMMANDS','MOSAIC_LIVE_ENDPOINT','MOSAIC_LIVE_DURATION','MOSAIC_BEHAVIOR_PLAN','MOSAIC_PLAYBACK_LOOP','MOSAIC_BACKGROUND_IMAGE','MOSAIC_LIVE_IDLE_FALLBACK','MOSAIC_LIVE_FADE_S','MOSAIC_MMD_SHADING','MOSAIC_AUX_OUTPUTS','MOSAIC_BEHAVIOR_LIVE_PORT','MOSAIC_CAMERA_DIRECTOR','MOSAIC_GAZE','MOSAIC_SNAPSHOT_TICKS','MOSAIC_MSAA','MOSAIC_TOON_RIM','MOSAIC_MMD_SELF_SHADOW','MOSAIC_TRACE','MOSAIC_SKINNING','MOSAIC_JOINT_LIMITS','MOSAIC_SELF_COLLISION','MOSAIC_EYE_SELF_SHADOW','MOSAIC_PLANT_FEET','MOSAIC_CAMERA_FRAMING','MOSAIC_CAMERA_STAGE_M','MOSAIC_CAMERA_AZIMUTH_DEG', 'MOSAIC_MMD_EDGE', 'MOSAIC_MMD_EDGE_SIGN', 'MOSAIC_LIVE_SMOOTHING', 'MOSAIC_PMX_WIND', 'MOSAIC_PMX_POSE_FOLLOW', 'MOSAIC_PMX_PHYSICS', 'MOSAIC_PMX_WORLD_MODEL', 'MOSAIC_PMX_WORLD_MODEL_FALLBACK', 'MOSAIC_CAMERA_MOTION','MOSAIC_BULLET_NODE','MOSAIC_BULLET_WORKER','MOSAIC_CONTROL_PORT','MOSAIC_CLIP_ROOT','MOSAIC_CLIP_FADE_S','MOSAIC_LIVE_PREVIEW_MS','MOSAIC_CAMERA_FOLLOW']: env.pop(name,None)
    if args.clip and not args.pmx: parser.error('--clip requires --pmx')
    if args.preserve_signed_linear_weights and not (args.clip or args.live_endpoint): parser.error('Signed weight diagnostic requires --clip or --live-endpoint')
    if args.interactive and not (args.clip or args.live_endpoint): parser.error('--interactive requires --clip or --live-endpoint')
    if args.commands and not args.interactive: parser.error('--commands requires --interactive')
    if args.behavior:
        if not (args.clip or args.live_endpoint): parser.error('--behavior requires --clip or --live-endpoint')
        env['MOSAIC_BEHAVIOR_PLAN']=str(args.behavior.resolve(strict=True))
    if args.loop:
        if not args.interactive or not args.clip: parser.error('--loop requires --interactive and --clip')
        env['MOSAIC_PLAYBACK_LOOP']='1'
    if args.background: env['MOSAIC_BACKGROUND_IMAGE']=str(args.background.resolve(strict=True))
    if args.mmd_shading: env['MOSAIC_MMD_SHADING']='mmd'
    if args.clean_stage: env['MOSAIC_CLEAN_STAGE']='1'
    if args.renderer=='forward_plus' and args.aux_outputs: parser.error('--aux-outputs is qualified on the Compatibility renderer only')
    if args.aux_outputs:
        if args.headless: parser.error('--aux-outputs needs a rendered (non-headless) run')
        env['MOSAIC_AUX_OUTPUTS']='1'
    if args.live_idle_fallback or args.live_fade:
        if not args.live_endpoint or not 0<=args.live_fade<=2: parser.error('--live-idle-fallback/--live-fade require --live-endpoint and fade in [0, 2] s')
        env['MOSAIC_LIVE_IDLE_FALLBACK']='1';env['MOSAIC_LIVE_FADE_S']=str(args.live_fade)
    if args.live_smoothing:
        try: cutoff,beta=(float(x) for x in args.live_smoothing.split(','))
        except ValueError: parser.error('--live-smoothing takes MIN_CUTOFF_HZ,BETA')
        if not args.live_endpoint or not 0<cutoff<=100 or not 0<=beta<=100: parser.error('--live-smoothing requires --live-endpoint and bounded parameters')
        env['MOSAIC_LIVE_SMOOTHING']=f'{cutoff},{beta}'
    if args.mmd_edges is not None:
        if not args.mmd_shading or not 0<args.mmd_edges<=16: parser.error('--mmd-edges requires --mmd-shading and a width in (0, 16] px')
        env['MOSAIC_MMD_EDGE']=str(args.mmd_edges);env['MOSAIC_MMD_EDGE_SIGN']=str(args.mmd_edge_sign)
    if args.gaze_camera:
        if not args.behavior: parser.error('--gaze-camera requires --behavior')
        env['MOSAIC_GAZE']='camera'
    if args.physics_wind:
        try: wind=[float(x) for x in args.physics_wind.split(',')]
        except ValueError: parser.error('--physics-wind takes numbers')
        if not args.physics or len(wind) not in (3,5) or sum(x*x for x in wind[:3])**.5>1000 or (len(wind)==5 and not (0<=wind[3]<=1 and 0<wind[4]<=10)): parser.error('--physics-wind needs --physics and X,Y,Z[,0..1,(0,10] Hz]')
        env['MOSAIC_PMX_WIND']=','.join(str(x) for x in wind)
    if args.physics_follow is not None:
        if not args.physics or args.physics_backend!='approx' or args.physics_model or not 0<=args.physics_follow<=1: parser.error('--physics-follow needs approximate --physics and 0-1')
        env['MOSAIC_PMX_POSE_FOLLOW']=repr(args.physics_follow)
    if args.physics_backend not in ('approx','bullet'): parser.error('Unknown physics backend')
    for key in ['MOSAIC_BULLET_SCENE','MOSAIC_BULLET_ALLOW_INITIAL_OVERLAP','MOSAIC_MODEL_POSITION','MOSAIC_HOME','MOSAIC_HOME_MODEL','MOSAIC_MODEL_YAW']:env.pop(key,None)
    if args.home_model is not None and args.home is None: parser.error('--home-model needs --home')
    if args.home is not None:
        if not args.pmx or not args.home.is_file() or args.home.stat().st_size>1024*1024: parser.error('--home needs --pmx and a local layout JSON under 1 MiB')
        layout=json.loads(args.home.read_text(encoding='utf-8'))
        if layout.get('schema')!='mosaic-home-v1': parser.error('--home must be a mosaic-home-v1 layout')
        env['MOSAIC_HOME']=str(args.home.resolve())
        model=args.home_model if args.home_model is not None else (DEFAULT_HOME_MODEL if DEFAULT_HOME_MODEL.is_file() else None)
        if model is not None and str(model)!='none':
            if model.suffix.lower()!='.glb' or not model.is_file() or model.stat().st_size>256*1024*1024: parser.error('--home-model must be a local .glb under 256 MiB, or none')
            env['MOSAIC_HOME_MODEL']=str(model.resolve())
        if args.model_position is None:
            x,z=layout['start']['position'];args.model_position=[float(x),0.,float(z)]
    if args.model_yaw is not None:
        if not args.pmx or not math.isfinite(args.model_yaw) or abs(args.model_yaw)>360: parser.error('--model-yaw needs --pmx and degrees within +/-360')
        env['MOSAIC_MODEL_YAW']=repr(float(args.model_yaw))
    if type(args.bullet_allow_initial_overlap) is not bool:parser.error('Initial-overlap override must be a boolean')
    if args.bullet_allow_initial_overlap:
        if args.physics_backend!='bullet' or not (args.bullet_scene or args.home):parser.error('Initial-overlap override requires a Bullet static scene (or the home\'s)')
        env['MOSAIC_BULLET_ALLOW_INITIAL_OVERLAP']='1'
    if args.model_position is not None:
        v=args.model_position
        if not args.pmx or not isinstance(v,(list,tuple)) or len(v)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>10000 for x in v):parser.error('Model position requires a PMX model and three finite coordinates within +/-10000 metres')
        env['MOSAIC_MODEL_POSITION']=json.dumps(v)
    if args.physics_backend!='bullet' and (args.bullet_node or args.bullet_ammo_dir or args.bullet_scene): parser.error('Bullet options require --physics-backend bullet')
    if args.physics_backend=='bullet' and not args.physics: parser.error('--physics-backend bullet requires --physics')
    if args.physics_model and not args.physics: parser.error('--physics-model requires --physics')
    if args.physics:
        if not args.pmx or args.pose_mode!='pmx': parser.error('--physics requires --pmx and --pose-mode pmx')
        if args.physics_backend=='bullet':
            if args.physics_model or args.physics_wind: parser.error('Bullet backend cannot combine learned weights or approximate wind')
            if not (args.clip or args.live_endpoint): parser.error('Bullet playback requires --clip or --live-endpoint')
            if not args.bullet_node or not args.bullet_node.is_file() or not args.bullet_ammo_dir: parser.error('Bullet requires --bullet-node and --bullet-ammo-dir')
            if not all((args.bullet_ammo_dir/name).is_file() for name in ['ammo.wasm.js','ammo.wasm.wasm']): parser.error('Bullet Ammo assets are missing')
            env.update(MOSAIC_PMX_PHYSICS='bullet',MOSAIC_BULLET_NODE=str(args.bullet_node.resolve()),MOSAIC_BULLET_WORKER=str(ROOT/'tools/mmd-bullet-teacher/live-worker.mjs'),MOSAIC_AMMO_DIR=str(args.bullet_ammo_dir.resolve()))
            if args.bullet_scene:
                if not args.bullet_scene.is_file() or args.bullet_scene.stat().st_size>1024*1024: parser.error('Static Bullet scene must be a local JSON file under 1 MiB')
                env['MOSAIC_BULLET_SCENE']=str(args.bullet_scene.resolve())
            elif args.home is not None:
                # The home's fixed furniture collides with her skirt and hair (owner 2026-10-28: the skirt went through the
                # sofa, nothing there to rest on); Godot already draws it from the layout, so the boxes are not drawn again.
                scene=args.out.with_name(args.out.name+'.home-bullet-scene.json')   # the client wants --out new; the scene sits beside it
                scene.write_text(json.dumps(home_bullet_scene(json.loads(args.home.read_text(encoding='utf-8')))),encoding='utf-8')
                env['MOSAIC_BULLET_SCENE']=str(scene.resolve());env['MOSAIC_BULLET_SCENE_DRAWN']='1'
        elif args.physics_model:
            if args.physics_wind: parser.error('--physics-wind applies to the approximate solver only')
            env['MOSAIC_PMX_PHYSICS']='learned';env['MOSAIC_PMX_WORLD_MODEL']=str(args.physics_model.resolve(strict=True))
            if not 1<=args.physics_model_fallback<=1000: parser.error('--physics-model-fallback must be 1..1000')
            env['MOSAIC_PMX_WORLD_MODEL_FALLBACK']=str(args.physics_model_fallback)
        else: env['MOSAIC_PMX_PHYSICS']='approx'
    if args.msaa: env['MOSAIC_MSAA']=str(args.msaa)
    if args.ground_blob: env['MOSAIC_GROUND_BLOB']='1'
    env['MOSAIC_TRACE']=args.trace
    if args.gpu_skinning:
        if not args.mmd_shading or args.pose_mode!='pmx': parser.error('--gpu-skinning needs --mmd-shading and --pose-mode pmx')
        env['MOSAIC_SKINNING']='gpu'
    if args.mmd_self_shadow:
        if not args.mmd_shading: parser.error('--mmd-self-shadow needs --mmd-shading')
        env['MOSAIC_MMD_SELF_SHADOW']='1'
    if args.toon_rim is not None:
        if not args.mmd_shading or not 0<args.toon_rim<=2: parser.error('--toon-rim needs --mmd-shading and a strength in (0, 2]')
        env['MOSAIC_TOON_RIM']=str(args.toon_rim)
    if args.write_movie is not None:
        if args.headless or args.interactive or args.realtime or args.live_endpoint or args.behavior_live is not None:
            parser.error('--write-movie needs a rendered, non-interactive diagnostic run')
        if args.write_movie.suffix.lower()!='.avi' or args.write_movie.exists(): parser.error('--write-movie needs a new .avi path')
    if args.snapshots:
        try: ticks=sorted({round(float(x)*240) for x in args.snapshots.split(',')})
        except ValueError: parser.error('--snapshots needs comma-separated seconds')
        if len(ticks)>64 or ticks[0]<1 or ticks[-1]>1_000_000: parser.error('--snapshots: at most 64 times in (0, 4166] s')
        if args.headless: parser.error('--snapshots needs a rendered (non-headless) run')
        env['MOSAIC_SNAPSHOT_TICKS']=','.join(map(str,ticks))
    if args.control_port is not None:
        if not (args.interactive and args.realtime and args.clip): parser.error('--control-port requires --interactive --realtime and --clip')
        if not 1<=args.control_port<=65535: parser.error('--control-port must be 1..65535')
        env['MOSAIC_CONTROL_PORT']=str(args.control_port)
        env['MOSAIC_CLIP_ROOT']=str(ROOT)   # the "clip" control switches only to clips inside this checkout
    if args.companion_worker is not None:
        try: worker=json.loads(args.companion_worker)
        except ValueError: parser.error('--companion-worker must be a JSON list of strings')
        if not (isinstance(worker,list) and 2<=len(worker)<=32 and all(isinstance(a,str) and 0<len(a)<=1024 and '\0' not in a for a in worker)): parser.error('--companion-worker must be a JSON list of 2-32 strings')
        if args.control_port is None or args.home is None: parser.error('--companion-worker needs --control-port and --home')
        env['MOSAIC_COMPANION_WORKER']=json.dumps(worker,ensure_ascii=False)
    if args.clip_fade is not None:
        if args.control_port is None or not 0<=args.clip_fade<=2: parser.error('--clip-fade needs --control-port and 0-2 seconds')
        env['MOSAIC_CLIP_FADE_S']=repr(args.clip_fade)
    if args.live_preview_ms is not None:
        if args.control_port is None or args.headless or not 100<=args.live_preview_ms<=5000: parser.error('--live-preview-ms needs --control-port, a rendered run and 100-5000 ms')
        env['MOSAIC_LIVE_PREVIEW_MS']=str(args.live_preview_ms)
    if args.behavior_live is not None:
        if not args.behavior: parser.error('--behavior-live requires --behavior (seed and channels)')
        if not 1<=args.behavior_live<=65535: parser.error('--behavior-live port must be 1..65535')
        env['MOSAIC_BEHAVIOR_LIVE_PORT']=str(args.behavior_live)
    if args.auto_camera:
        if not args.behavior or not args.pmx: parser.error('--auto-camera requires --behavior and --pmx')
        env['MOSAIC_CAMERA_DIRECTOR']='auto'
    if args.camera_motion:
        if not args.pmx: parser.error('--camera-motion requires --pmx')
        env['MOSAIC_CAMERA_MOTION']=str(args.camera_motion.resolve(strict=True))
    if args.frame_head:
        if not args.pmx: parser.error('--frame-head requires --pmx')
        env['MOSAIC_CAMERA_FRAMING']='head'
    if args.eye_self_shadow:
        if not args.mmd_self_shadow: parser.error('--eye-self-shadow requires --mmd-self-shadow')
        env['MOSAIC_EYE_SELF_SHADOW']='1'
    if args.joint_limits:
        if args.pose_mode!='pmx': parser.error('--joint-limits requires --pose-mode pmx')
        env['MOSAIC_JOINT_LIMITS']='1'
    if args.self_collision:
        if args.pose_mode!='pmx': parser.error('--self-collision requires --pose-mode pmx')
        env['MOSAIC_SELF_COLLISION']='1'
    if args.plant_feet:
        if args.pose_mode!='pmx': parser.error('--plant-feet requires --pose-mode pmx')
        env['MOSAIC_PLANT_FEET']='1'
    if args.frame_stage is not None:
        if not args.pmx or args.frame_head or args.frame_body or not 0<args.frame_stage<=50: parser.error('--frame-stage requires --pmx, 0<m<=50, and excludes other framings')
        env['MOSAIC_CAMERA_FRAMING']='stage';env['MOSAIC_CAMERA_STAGE_M']=repr(args.frame_stage)
    if args.frame_body:
        if not args.pmx or args.frame_head: parser.error('--frame-body requires --pmx and excludes --frame-head')
        env['MOSAIC_CAMERA_FRAMING']='body'
    if args.camera_follow:
        if not (args.frame_body or args.frame_head) or args.camera_motion or args.auto_camera: parser.error('--camera-follow requires --frame-body or --frame-head and excludes --camera-motion and --auto-camera')
        env['MOSAIC_CAMERA_FOLLOW']='1'
    if args.camera_azimuth is not None:
        if not (args.frame_head or args.frame_body or args.frame_stage is not None) or not math.isfinite(args.camera_azimuth) or not -180<=args.camera_azimuth<=180:
            parser.error('--camera-azimuth requires --frame-head, --frame-body or --frame-stage and -180..180 degrees')
        env['MOSAIC_CAMERA_AZIMUTH_DEG']=repr(args.camera_azimuth)
    if args.interactive: env['MOSAIC_PLAYBACK_INTERACTIVE']='1'
    if args.commands: env['MOSAIC_PLAYBACK_COMMANDS']=str(args.commands.resolve(strict=True))
    if args.live_endpoint:
        if not args.pmx or not args.interactive or args.pose_mode!='pmx' or args.commands: parser.error('Live endpoint requires interactive PMX mode without replay commands')
        env['MOSAIC_LIVE_ENDPOINT']=args.live_endpoint
    if args.live_duration is not None:
        if not args.live_endpoint or not 0<args.live_duration<=60: parser.error('Live duration requires endpoint and finite 0..60 seconds')
        env['MOSAIC_LIVE_DURATION']=str(args.live_duration)
    duration=4
    if args.clip:
        env['MOSAIC_MOTION_CLIP']=str(args.clip.resolve(strict=True))
        if args.clip.suffix.lower()=='.vmd':
            if args.pose_mode!='pmx': parser.error('VMD requires --pose-mode pmx')
            duration=600  # Bounded parser horizon; an explicit timeout can override.
        else:
            clip_data=json.loads(args.clip.read_text(encoding='utf-8-sig'))
            try: validate_explicit_root_launch(args,clip_data)
            except ValueError as error: parser.error(str(error))
            count=len(clip_data['frames'])
            duration=max(4,(count-1)/30)
    env['MOSAIC_POSE_MODE']=args.pose_mode
    if args.preserve_signed_linear_weights: env['MOSAIC_PRESERVE_SIGNED_LINEAR']='1'
    env['DOTNET_ROOT'] = str(args.dotnet.resolve().parent)
    env['MOSAIC_SCENE_OUT'] = str(args.out.resolve())
    if args.pmx:
        env['MOSAIC_PMX_PATH'] = str(args.pmx.resolve(strict=True)); env['MOSAIC_PMX_SCALE'] = str(args.scale)
    version = subprocess.run([str(args.godot),'--headless','--version'],env=env,capture_output=True,text=True,check=True,timeout=15).stdout.strip()
    if not version.startswith('4.5.2.stable.mono.'): parser.error('Godot 4.5.2 stable .NET edition is required')
    # Godot's project runner loads Debug assemblies. Changing only Configuration to Release
    # builds a different location and can leave it executing an old, unoptimized binary.
    # A preceding test build can leave Core's unoptimized DLL in the incremental cache.
    # Rebuild project references so the requested setting also reaches the loaded Core binary.
    # The rebuild takes 7-21 s per launch; it is skipped when a stamp proves nothing it depends on changed (client_build_needed).
    sources = client_sources_sha256(args.optimize_managed, args.dotnet)
    try: saved = json.loads(CLIENT_BUILD_STAMP.read_text(encoding='utf-8'))
    except (OSError, ValueError): saved = None
    if args.force_build or client_build_needed(sources, saved, loaded_client_dlls()):
        subprocess.run([str(args.dotnet),'build',str(ROOT/'clients/godot-scene/MosaicScene.csproj'),'--nologo','--no-incremental',
                        '-p:Optimize='+str(args.optimize_managed).lower()], cwd=ROOT,env=env,check=True,timeout=args.timeout or 120)
        CLIENT_BUILD_STAMP.parent.mkdir(parents=True, exist_ok=True)
        CLIENT_BUILD_STAMP.write_text(json.dumps(dict(sources_sha256=sources, dlls=loaded_client_dlls()), indent=1) + '\n', encoding='utf-8')
        print('client build: rebuilt', flush=True)
    else:
        print('client build: skipped (sources, optimisation, SDK and loaded assemblies unchanged since the last launcher build)', flush=True)
    # Live behaviour events arrive in wall time, so such sessions run the 240 Hz physics tick in real time (no --fixed-fps);
    # determinism is kept by the tick-stamped behavior-live-replay.json.
    # Movie Maker: 30 rendered frames per second = 8 of the 240 Hz physics ticks = one diagnostic clip frame per video frame.
    fps = '30' if args.write_movie is not None else '60'
    command = [str(args.godot),'--path',str(ROOT/'clients/godot-scene')]+([] if args.realtime or args.behavior_live is not None else ['--fixed-fps',fps])
    if args.write_movie is not None: command += ['--write-movie',str(args.write_movie.resolve())]
    if args.headless: command.append('--headless')
    else: command += ['--rendering-method','gl_compatibility' if args.renderer=='compatibility' else 'forward_plus']
    result = subprocess.run(command,cwd=ROOT,env=env,timeout=args.timeout or (None if args.interactive and not args.commands else max(90,duration*20+30)))
    if result.returncode==0 and args.physics and args.physics_backend=='bullet':
        close=args.out/'bullet-session-close.json'
        if not close.is_file(): raise SystemExit('Bullet worker cleanup receipt missing')
        record=json.loads(close.read_text(encoding='utf-8'))
        if record.get('exit_code')!=0 or record.get('forced_kill') or record.get('failures')!=0: raise SystemExit('Bullet worker did not exit cleanly')
    if result.returncode==0 and args.interactive and not args.commands:
        if not (args.out/'playback-controls.json').exists(): raise SystemExit('Interactive control receipt missing')
        if args.live_endpoint and (args.live_idle_fallback or args.live_fade):
            # Arbitrated live sessions are re-checked by the independent trace verifier before success is reported.
            check=subprocess.run([sys.executable,str(ROOT/'tools/verify_native_live_arbitration.py'),str(args.out/'live-controls.json'),'--out',str(args.out/'live-arbitration-verification.json')],cwd=ROOT,timeout=60)
            raise SystemExit(check.returncode)
        raise SystemExit(0)
    if result.returncode == 0:
        record = json.loads((args.out/'result.json').read_text())
        if record.get('schema') != 'mosaic-native-scene-diagnostic-v1' or record.get('gravity_contact_diagnostic_passed') is not True:
            raise SystemExit('Missing or failed physics diagnostic')
        if not args.headless and not (args.out/'frame.png').is_file():
            raise SystemExit('Native viewport export missing')
    raise SystemExit(result.returncode)

if __name__ == '__main__': main()
