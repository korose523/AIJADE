"""Bind actual retained E6 controls; never rerun the control or kernel workload."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

REPORT_SHA="b1d98ed33773cde90a3e2487b87519e8d0f1b3de61b10424f9d452358bea6adf"
PRIMARY_MANIFEST_SHA="ce57621f16befad3b90329fde4aace4e3aab28f122968aa07e1d8e1b6a5152a9"

def need(value,message):
    if not value:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def unique(pairs):
    out={}
    for k,v in pairs:
        need(k not in out,"duplicate JSON key");out[k]=v
    return out
def decode(raw):return json.loads(raw,object_pairs_hook=unique)
def safe(name):
    need(type(name) is str and name not in ("",".","..") and Path(name).name==name
         and "/" not in name and "\\" not in name and not any(ord(c)<32 for c in name),"safe sibling basename required")
    return name
def verify(packet):
    here=Path(__file__).resolve().parent
    need(not any(p.is_symlink() for p in (Path(__file__).absolute(),*Path(__file__).absolute().parents)),"companion verifier symlink")
    manifest=decode((here/"publication-companions.json").read_bytes())
    need(manifest["schema"]=="aijade.ch7.e6-publication-companions.v1","actual E6 companions schema")
    files=manifest["files"];names=[safe(row["name"]) for row in files]
    need(len(names)==len(set(names)),"duplicate companion name")
    by_name={}
    for row in files:
        name=safe(row["name"]);p=here/name
        need(p.is_file() and not p.is_symlink(),"regular sibling companion required")
        raw=p.read_bytes();need(sha(raw)==row["sha256"] and len(raw)==row["bytes"],"companion full SHA/size differs: "+name)
        by_name[name]=raw
    roles=manifest["recordedControls"]
    source_name,report_name,log_name=[safe(roles[k]) for k in ("source","report","log")]
    need(all(n in by_name for n in (source_name,report_name,log_name)),"all actual recorded-control companions required")
    need(Path(__file__).name in by_name,"verifier source must itself be bound by companions")
    need(sha(by_name[report_name])==REPORT_SHA and manifest["primaryManifestSha256"]==PRIMARY_MANIFEST_SHA,"actual final report/primary hard pins differ")
    report=decode(by_name[report_name])
    need(report["status"]=="SEVENTEEN_E6_PORTABLE_PACKET_CONTROLS_PASS_NOT_NEW_KERNEL_OR_COLD_EXECUTION"
         and type(report["passed"]) is int and report["passed"]==17 and type(report["failed"]) is int and report["failed"]==0
         and report["positive"]==1 and report["coherentlyManifestedAdverse"]==16
         and report["primaryPacketUnmodified"] is True and report["primaryManifestSha256"]==PRIMARY_MANIFEST_SHA
         and report["newKernelRequests"]==report["newColdExecutions"]==0,"actual complete17 result/scope differs")
    controls=report["controls"];case_names=[v["name"] for v in controls]
    need(len(controls)==len(set(case_names))==17 and controls[0]["status"]=="ORIGINAL_ACCEPTED"
         and all(v["status"]=="COHERENT_SEMANTIC_MUTATION_REJECTED" and v["transportCoherent"] is True for v in controls[1:]),"all17 actual distinct coherent results required")
    tree=ast.parse(by_name[source_name]);assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="CASES" for t in n.targets))
    need(isinstance(assignment.value,ast.List),"literal recorded case population required")
    source_cases=[ast.literal_eval(v.elts[0]) for v in assignment.value.elts]
    need(source_cases==case_names,"recorded source17 case population differs")
    actual_lines=[]
    for line in by_name[log_name].decode().splitlines():
        if line.startswith('{"name":'):actual_lines.append(decode(line))
    need(actual_lines==controls,"all17 actual per-case log records differ from report")
    actual=Path(packet).absolute();need(not any(p.is_symlink() for p in (actual,*actual.parents)),"packet path symlink")
    raw=(actual/"packet-manifest.json").read_bytes()
    need(sha(raw)==PRIMARY_MANIFEST_SHA,"actual supplied primary02 manifest differs")
    return dict(status="RECORDED_SEVENTEEN_CONTROLS_SOURCE_REPORT_LOG_BOUND_NOT_RERUN",
        recordedControls=17,controlSetExecutedHere=False,newKernelRequests=0,newColdExecutions=0,
        primaryManifestSha256=PRIMARY_MANIFEST_SHA,reportSha256=REPORT_SHA,companionFiles=len(files))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--packet",required=True)
    args=parser.parse_args();print(json.dumps(verify(args.packet),indent=2))
