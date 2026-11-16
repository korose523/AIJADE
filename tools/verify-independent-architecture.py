#!/usr/bin/env python3
"""Read-only checks of the owned product boundary and complete src-project inventory.

Default/--check-only writes only stdout. --self-test exercises rejection controls in memory.
This guard neither starts a product service nor executes or qualifies a research experiment.
"""
import argparse
import copy
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = 'configs/companion/capabilities.json'
DOMAINS = {'identity', 'memory', 'life', 'perception', 'planning', 'execution', 'delivery', 'research', 'support'}
IMPLEMENTATIONS = {'implemented', 'configurable', 'planned', 'in_progress'}
REQUIRED_LAUNCHERS = {'tools/run-companion.sh', 'src/Aijade.Server/Program.cs',
                      'src/Aijade.Server/ServerModules.cs', 'src/Aijade.Bots/Program.cs'}
STAGE_SOURCE = 'src/Aijade.Server/Product/Stage.cs'
REQUIRED_OWNED_RUNTIME = {STAGE_SOURCE, 'src/Aijade.Server/Product/NativeStageStore.cs',
                          'tools/companion-services/server.py'}
FORBIDDEN_LAUNCH = re.compile(
    r'WorkBuddy[/\\]+MOSAIC|[/\\]MOSAIC[/\\](?:scripts|tools|src|clients|host-dotnet|\.venv)|'
    r'\bMOSAIC_ROOT\b|run-native-mmd-scene\.py|tools[/\\]live_controller\.py|'
    r'\bdsh\s+plugin\s+add\b|\bastrbot\s+(?:run|start)\b|'
    r'new\s+(?:[\w.]+\.)?MosaicRendererLink\s*\(|'
    r'Get(?:Required)?Service\s*<[^>]*\bMosaicRendererLink\b|'
    r'StageEndpoints\.Workbench\s*\(', re.IGNORECASE)
CS_NON_CODE = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|\$?@"(?:""|[^"])*"|@\$"(?:""|[^"])*"|\$?"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
FORBIDDEN_STAGE_PROXY = re.compile(
    r'\b(?:IHttpClientFactory|HttpClient)\b|'
    r'\b(?:CreateClient|GetFromJsonAsync|PostAsJsonAsync|PutAsJsonAsync|'
    r'GetAsync|PostAsync|PutAsync|DeleteAsync|SendAsync|GetStringAsync|GetStreamAsync|GetByteArrayAsync)\s*(?:<[^;{}()]*>)?\s*\(')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inside(root, path):
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def source_path(root, relative):
    require(isinstance(relative, str) and relative and '\\' not in relative, 'Unsafe source path')
    path = PurePosixPath(relative)
    require(not path.is_absolute() and not PureWindowsPath(relative).is_absolute()
            and '..' not in path.parts and ':' not in relative and relative == path.as_posix(), 'Unsafe source path: ' + relative)
    resolved = root / relative
    require(inside(root, resolved) and resolved.is_file() and not resolved.is_symlink(), 'Missing or external source: ' + relative)
    return resolved


def stage_map_code(text):
    """Inspect the real C# Map body; compatibility helpers and string messages stay outside it."""
    code = CS_NON_CODE.sub(lambda match: ' ' * len(match.group()), text)
    method = re.search(r'\bpublic\s+static\s+void\s+Map\s*\([^)]*\)\s*\{', code)
    require(method is not None, 'Native Stage.Map entry point missing')
    start = method.end() - 1
    depth = 0
    for index in range(start, len(code)):
        if code[index] == '{':
            depth += 1
        elif code[index] == '}':
            depth -= 1
            if depth == 0:
                return code[start:index + 1]
    raise ValueError('Unclosed Native Stage.Map body')


def check(root, registry, text_overrides=None):
    root = root.resolve()
    overrides = text_overrides or {}
    require(registry.get('schema') == 'aijade-owned-capabilities-v1', 'Wrong capability schema')
    require(registry.get('scientificAcceptance') is False and registry.get('newExperimentsRun') == 0,
            'An architecture inventory cannot grant scientific acceptance or record a new experiment')
    require({row['id'] for row in registry['domains']} == DOMAINS and len(registry['domains']) == len(DOMAINS), 'Domain classification incomplete')
    actual = {str(path.relative_to(root)) for path in (root / 'src').glob('*/*.csproj')}
    modules = registry['modules']
    require(len({row['id'] for row in modules}) == len(modules), 'Duplicate module id')
    require(len({row['project'] for row in modules}) == len(modules), 'Duplicate module project')
    require({row['project'] for row in modules} == actual, 'Source project coverage mismatch')
    refs = 0
    for module in modules:
        path = source_path(root, module['project'])
        require(module['id'] == path.stem == path.parent.name, 'Module identity mismatch')
        require(module['primaryDomain'] in DOMAINS and set(module['additionalDomains']) <= DOMAINS, 'Unknown module domain')
        xml = ET.fromstring(overrides.get(module['project'], path.read_text()))
        for element in xml.iter():
            if element.tag.rsplit('}', 1)[-1] != 'ProjectReference':
                continue
            value = element.get('Include', '').replace('\\', '/')
            require(value and '$(' not in value and not any(ch in value for ch in '*?;')
                    and not Path(value).is_absolute() and not PureWindowsPath(value).is_absolute()
                    and ':' not in value, 'Unsafe project reference: ' + module['project'])
            target = (path.parent / value).resolve()
            require(inside(root, target) and target.is_file() and target.suffix == '.csproj',
                    'External or missing project reference: ' + module['project'] + ' -> ' + value)
            refs += 1
    capabilities = registry['capabilities']
    require(capabilities and len({row['id'] for row in capabilities}) == len(capabilities), 'Duplicate or empty capability population')
    for item in capabilities:
        require(item['domain'] in DOMAINS and item['implementation'] in IMPLEMENTATIONS, 'Unknown capability classification')
        require(item['sources'] and item['entrypoints'], 'Capability has no source or entry point: ' + item['id'])
        require(item['verification']['kind'] == 'source_inventory' and item['verification']['scope'], 'Inventory verification scope missing')
        for relative in item['sources']:
            source_path(root, relative)
    require({row['domain'] for row in capabilities} == DOMAINS, 'Empty capability domain')
    launchers = registry['productLaunchers']
    require(set(launchers) == REQUIRED_LAUNCHERS and len(launchers) == len(REQUIRED_LAUNCHERS), 'Product launcher coverage mismatch')
    for relative in launchers:
        path = source_path(root, relative)
        text = overrides.get(relative, path.read_text())
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith(('#', '//', '/*', '*')):
                continue
            require(not FORBIDDEN_LAUNCH.search(line), 'External product launch dependency: ' + relative + ':' + str(number))
    owned_runtime = registry['ownedRuntimeSources']
    require(set(owned_runtime) == REQUIRED_OWNED_RUNTIME and len(owned_runtime) == len(REQUIRED_OWNED_RUNTIME),
            'Owned runtime source coverage mismatch')
    for relative in owned_runtime:
        source_path(root, relative)
    stage_path = source_path(root, STAGE_SOURCE)
    stage_map = stage_map_code(overrides.get(STAGE_SOURCE, stage_path.read_text()))
    require('NativeStageStore' in stage_map, 'Stage.Map must use the owned NativeStageStore')
    require(not FORBIDDEN_STAGE_PROXY.search(stage_map), 'External HTTP workbench proxy in Native Stage.Map')
    exceptions = registry['historicalResearchExceptions']
    require(exceptions and all(row['kind'] == 'research_adapter' and row['reason'] for row in exceptions), 'Unexplained research exception')
    for row in exceptions:
        for relative in row['paths']:
            source_path(root, relative)
            require(relative.startswith(('experiments/ch7/', 'src/Aijade.Integrations/Renderer/')), 'Exception outside historical research boundary')
            require(relative not in launchers, 'Research adapter cannot be a product launcher')
    return {'status': 'OWNED_ARCHITECTURE_SOURCE_BOUNDARIES_PASS', 'sourceProjects': len(actual),
            'internalProjectReferences': refs, 'domains': len(DOMAINS), 'capabilityFamilies': len(capabilities),
            'capabilityStatuses': {name: sum(item['implementation'] == name for item in capabilities) for name in sorted(IMPLEMENTATIONS)},
            'productLaunchers': len(launchers), 'historicalResearchExceptionGroups': len(exceptions),
            'ownedRuntimeSources': len(owned_runtime), 'nativeStageProxyGuard': 'PASS',
            'scientificAcceptance': False, 'newExperimentsRun': 0, 'servicesStarted': 0,
            'scope': 'Source inventory and dependency boundaries only; no claim of live platform, model, rendering, physical or scientific acceptance.'}


def controls(root, registry):
    rejected = []
    def reject(name, altered=None, texts=None):
        try:
            check(root, altered if altered is not None else registry, texts)
        except (ValueError, KeyError, ET.ParseError) as error:
            rejected.append({'name': name, 'rejected': True, 'reason': str(error)})
        else:
            raise AssertionError('Control unexpectedly accepted: ' + name)

    altered = copy.deepcopy(registry); altered['modules'].pop()
    reject('unclassified-source-project', altered)
    altered = copy.deepcopy(registry); altered['capabilities'][0]['sources'] = ['../MOSAIC/source.cs']
    reject('parent-escaping-capability-source', altered)
    altered = copy.deepcopy(registry); altered['capabilities'][0]['sources'] = ['/Users/mac/WorkBuddy/MOSAIC/source.cs']
    reject('absolute-capability-source', altered)
    altered = copy.deepcopy(registry); altered['capabilities'][0]['sources'] = ['src/missing-capability-source.cs']
    reject('missing-capability-source', altered)
    project = 'src/Aijade.Bots/Aijade.Bots.csproj'
    xml = ET.fromstring((root / project).read_text())
    ET.SubElement(xml, 'ProjectReference', {'Include': '../../../../MOSAIC/project.csproj'})
    reject('project-reference-outside-repository', texts={project: ET.tostring(xml, encoding='unicode')})
    launcher = 'tools/run-companion.sh'
    reject('external-mosaic-launcher', texts={launcher: (root / launcher).read_text() + '\nexec /Users/mac/WorkBuddy/MOSAIC/.venv/bin/python run-native-mmd-scene.py\n'})
    bot = 'src/Aijade.Bots/Program.cs'
    reject('legacy-renderer-instantiation', texts={bot: (root / bot).read_text() + '\nvar forbidden = new Aijade.Integrations.Renderer.MosaicRendererLink(1);\n'})
    altered = copy.deepcopy(registry); altered['scientificAcceptance'] = True
    reject('inventory-promoted-to-scientific-acceptance', altered)
    stage = (root / STAGE_SOURCE).read_text()
    injected = re.sub(r'(public\s+static\s+void\s+Map\s*\([^)]*\)\s*\{)',
                      r'\1\n var retired = http.CreateClient("stage");', stage, count=1)
    reject('stage-workbench-http-proxy-reintroduced', texts={STAGE_SOURCE: injected})
    return rejected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Read-only default; output JSON to stdout')
    parser.add_argument('--self-test', action='store_true', help='Also exercise in-memory rejection controls')
    args = parser.parse_args()
    try:
        registry = json.loads((ROOT / REGISTRY).read_text())
        result = check(ROOT, registry)
        if args.self_test:
            result['negativeControls'] = controls(ROOT, registry)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, ET.ParseError, OSError) as error:
        print(json.dumps({'status': 'FAIL', 'error': str(error), 'scientificAcceptance': False}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
