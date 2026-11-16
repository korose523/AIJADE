from pathlib import Path
from datetime import datetime, timezone
import collections, hashlib, json, xml.etree.ElementTree as ET

C = Path(__file__).resolve().parent
W = C / 'worktree'
ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
failures = []
totals = collections.Counter()
for path in sorted((C / 'default-regression').glob('*.trx')):
    root = ET.parse(path)
    for row in root.findall('.//t:UnitTestResult', ns):
        totals[row.attrib['outcome']] += 1
        if row.attrib['outcome'] == 'Failed':
            message = row.find('t:Output/t:ErrorInfo/t:Message', ns).text
            failures.append({'test': row.attrib['testName'], 'message': message,
                             'category': 'assembly_location_root_discovery' if 'Repository' in message else 'global_redis_changed_inline_fixture'})
record = {
    'status': 'DEFAULT_REGRESSION_FAILED_BEFORE_ANY_QUALIFICATION_WINDOW',
    'recordedAt': datetime.now(timezone.utc).isoformat(),
    'sourceCommit': '3dc0644da43054ad879cfeb1d2b3a57313f57ff8',
    'allResults': dict(totals), 'failures': failures,
    'failureCategories': dict(collections.Counter(x['category'] for x in failures)),
    'originalLogSha256': hashlib.sha256((C / 'complete-default-regression.log').read_bytes()).hexdigest(),
    'prospectiveCorrection': {
        'removeOnlyGlobalEnvironmentVariables': ['REDIS_URL'],
        'why': 'Default fixtures specify the inline broker; the complete suite must retain its declared semantics.',
        'artifactsRoot': str(W / '.runtime' / 'build-artifacts'),
        'whyArtifacts': 'Repository discovery walks upward from the assembly location. Keep outputs beneath the actual clean checkout; no C# source or lookup fixture changes.',
        'nativeNugetCacheRemainsInsideProject': True,
        'sourceFilesChanged': 0,
        'qualificationWindowStarted': False,
        'researchMeasurementsStarted': False,
        'rerunScope': 'clean build and complete default regression, no filtering or retries of a selected test prefix',
    },
}
out = C / 'default-regression-failure-and-prospective-correction.json'
assert not out.exists()
out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
original = (C / 'build_regression.py').read_text()
corrected = original.replace("ART=Path(os.environ['AIJADE_ARTIFACTS'])", "ART=W/'.runtime'/'build-artifacts'")
corrected = corrected.replace(",REDIS_URL='127.0.0.1:56379'", "")
corrected = corrected.replace("steps=[]", "env.pop('REDIS_URL',None)\nenv['AIJADE_ARTIFACTS']=str(ART)\nsteps=[]")
corrected = corrected.replace("clean-current-committed-source", "clean-default-env-corrected-source")
corrected = corrected.replace("complete-default-regression", "complete-default-env-corrected-regression")
corrected = corrected.replace("C/'default-regression'", "C/'default-env-corrected-regression'")
script = C / 'build_regression_corrected.py'
assert not script.exists()
script.write_text(corrected)
print(json.dumps({'failures':len(failures),'categories':record['failureCategories'],'script':str(script)}))
