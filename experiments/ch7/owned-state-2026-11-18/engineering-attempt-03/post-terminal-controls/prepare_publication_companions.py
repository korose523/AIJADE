"""Record exact finished post-terminal tools and receipts; never publish or mutate packet."""
from pathlib import Path
import json
from packet_common import read,new,encoded,file_sha,need
C=Path('/Volumes/Untitled/AIJADE/.research/runs/ch7-owned-state-20261118');T=C/'archive-tools'

def main():
    result=read(T/'packet-controls-final-15.json')
    need(result['status']=='FIFTEEN_ADVERSARIAL_POST_TERMINAL_CONTROLS_PASS' and result['passed']==15 and result['failed']==0,'actual fifteen control receipt required')
    primary=C/'audit/engineering-03-packet';need(file_sha(primary/'packet-manifest.json')==result['actualPrimaryManifestSha256'],'immutable final primary differs')
    files=[]
    def add(p,name=None):
        p=Path(p);name=p.name if name is None else name
        need(p.is_file() and name==Path(name).name and not any(v['name']==name for v in files),'plain unique companion basename')
        files.append(dict(path=str(p),name=name,sha256=file_sha(p)))
    for name in ['archive_e5_packet.py','packet_common.py','verify_e5_packet.py','e5_refusal_semantics.py','lossless_members.py',
        'inspect_partial_nested_refusal.py','test_actual_e5_packet_controls.py','test_fictitious_outer_call.py',
        'prepare_actual_e5_refusal_config.py','prepare_publication_companions.py','actual-e5-refusal-config-01.json',
        'actual-e5-refusal-config-02.json','actual-e5-source-review-01.json','prepared-config-contract.json',
        'archive-e5-attempt-01.log','archive-e5-attempt-02.log','independent-verify-python39-01.log','independent-verify-python39-02.log',
        'VERIFY-E5-PACKET.md','packet-controls-01.log','packet-controls-01.json','packet-controls-additional-15.log','packet-controls-final-15.json']:
        add(T/name)
    add(C/'audit/engineering-03-packet-preparation.json')
    for p,name in [(C/'archive-preparation/test_lossless_members.py','test_lossless_members.py'),
        (C/'archive-preparation/codec-controls-01/result.json','codec-controls-01-result.json'),
        (C/'archive-preparation/codec-controls-01.log','codec-controls-01.log'),
        (C/'archive-preparation/TRANSPORT-HANDOFF.json','TRANSPORT-HANDOFF.json')]:add(p,name)
    value=dict(status=result['status'],schema='aijade.ch7.e5-post-terminal-publication-companions.v1',files=files,
        actualPrimaryManifestSha256=result['actualPrimaryManifestSha256'],actualPrimarySummarySha256=file_sha(primary/'summary.json'),
        mutableOriginalPacket=False,publicVerifierRuntime='Python3.9+ verified with actual3.9.6; use normal module filenames in one directory',
        portableCommand='python3 -B verify_e5_packet.py --packet <packet-directory>',
        noKernelColdReplayByTransportVerifier=True,engineeringAccepted=False,backendQualified=False,
        rootPacketReviewNotIncluded='Root independently adds its actual separate packet review; this tool never invents it.')
    out=T/'publication-companions.json';new(out,encoded(value));print(json.dumps(dict(path=str(out),sha256=file_sha(out),files=len(files),status=value['status']),indent=2))
if __name__=='__main__':main()
