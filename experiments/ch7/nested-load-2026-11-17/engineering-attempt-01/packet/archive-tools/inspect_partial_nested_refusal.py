"""Structural negative-record audit only; never accepts a complete workload."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

from packet_common import path,read,decode,encoded,need,inventory,file_sha,new,parent_wait_known


def inspect(args):
    root=path(args.root);terminal_path=path(args.parent_terminal);output=path(args.output)
    need(not output.exists() and root not in output.parents,'new refusal audit must be outside original run')
    terminal=read(terminal_path);wait=parent_wait_known(terminal)
    stability_path=path(args.writer_stability);stability=read(stability_path)
    need(stability['schema']=='aijade.ch7.nested-writer-stability.v1'
         and stability['sourceCommit']==args.source_commit==terminal['sourceCommit']
         and path(stability['runRoot'])==root
         and stability['parentTerminalSha256']==file_sha(terminal_path)
         and stability['writerStabilityAccepted'] is True
         and stability['allOriginalWritersTerminatedOrClosed'] is True
         and stability['unresolvedWriters']==[]
         and stability['writerProofKind']=='SOURCE_BOUND_SCOPE_CLOSE_AND_ACTUAL_PARENT_WAITS',
         'source-bound writer closure/actual wait proof required; parent exit alone is insufficient')
    before=inventory(root,absent_allowed=True)
    receipt_path=root/'receipt.json';producer=read(receipt_path) if receipt_path.is_file() else None
    need(producer is None or producer.get('status')!='ENGINEERING_REAL_NESTED_LOAD_PASS_PENDING_INDEPENDENT_AUDIT'
         or terminal.get('engineeringReportDelivered') is not True
         or stability.get('completeIndependentAuditRejected') is True,
         'a full successful producer requires the complete independent auditor, not the partial path')
    streams=[];complete_rows=0;process_rows=0;error_rows=0;parse_errors=0
    for name in before['files']:
        if not name.endswith('.jsonl'):continue
        p=root/name;physical=0;valid=0;observations=0;errors=0;malformed=[];unterminated=False
        with p.open('rb') as stream:
            for index,line in enumerate(stream,1):
                physical+=1
                if not line.endswith(b'\n'):unterminated=True
                try:
                    row=decode(line);valid+=1
                    if type(row) is dict and type(row.get('processObservation')) is dict:observations+=1
                    if type(row) is dict and ('observationError' in row or row.get('error') is not None):errors+=1
                except (ValueError,UnicodeError) as error:
                    malformed.append(dict(line=index,errorClass=type(error).__name__))
        streams.append(dict(path=name,physicalRows=physical,parseableRows=valid,
            actualProcessObservationRecords=observations,originalErrorRecords=errors,
            unterminatedLastRecord=unterminated,malformedOriginalRecords=malformed,
            note='All original bytes retained. Counts describe physical retained records, not accepted scheduled samples.'))
        complete_rows+=valid;process_rows+=observations;error_rows+=errors;parse_errors+=len(malformed)
    need(before==inventory(root,absent_allowed=True),'original refusal artifacts changed during structural inspection')
    result=dict(schema='aijade.ch7.nested-partial-negative-record-audit.v1',
        status='REFUSED_NESTED_PARTIAL_RECORDS_INVENTORIED_NOT_ENGINEERING_ACCEPTED',
        checkedAt=datetime.now(timezone.utc).isoformat(),sourceCommit=args.source_commit,
        writerStabilityAccepted=True,writerStabilityProofSha256=file_sha(stability_path),
        enclosingParentTerminalSha256=file_sha(terminal_path),actualKnownParentWait=wait,
        inputFiles=before['files'],directoryState=before,streams=streams,
        numbers=dict(originalRunFiles=len(before['files']),originalJsonlFiles=len(streams),
            parseableRetainedJsonlRecords=complete_rows,actualRetainedProcessObservationRecords=process_rows,
            originalRetainedErrorRecords=error_rows,malformedRetainedJsonlRecords=parse_errors),
        originalProducerStatus=producer.get('status') if producer else None,
        originalProducerErrors=producer.get('errors') if producer else None,
        pendingUnknowns=['No complete schedule/service/native/identity cold acceptance is granted by structural inventory.',
            'A result-specific independent refusal analysis must interpret the actual original error and cutoffs.'],
        completeEngineeringAuditAccepted=False,backendQualified=False,formalHardwareQualification=False,
        independentHumanReview=False,authorApproval=False,seedConstructed=False,heldoutComparisonComplete=False,
        oldP4RefusalChanged=False,newWindowStartedByAuditor=False,
        scope='Negative-record structural closure only. Missing phases, unfinished samples and unknown outcomes remain missing/unknown; no whole-machine/group cleanup certificate.')
    new(output,encoded(result));print(json.dumps(dict(status=result['status'],path=str(output),sha256=file_sha(output)),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--parent-terminal',required=True)
    parser.add_argument('--writer-stability',required=True)
    parser.add_argument('--source-commit',required=True)
    parser.add_argument('--output',required=True)
    inspect(parser.parse_args())
