"""Check the literal subsequence interpretation of HumanEval/132 on its released cases."""
import argparse
import hashlib
import json
from pathlib import Path

from prepare import REFERENCE, groups, write_json


def main(out):
    for task_id,lines in groups(REFERENCE/'runs/attempt-02/pass-1/rows.jsonl.gz'):
        if task_id!='HumanEval/132':
            continue
        discrepancies=[]
        for line in lines:
            row=json.loads(line)
            text=row['input']['items'][0]['v']
            progress=0
            for char in text:
                if progress<4 and char=='[[]]'[progress]:
                    progress+=1
            subsequence=progress==4
            reference=row['output']['v']
            if subsequence!=reference:
                discrepancies.append({'case':[row['partition'],row['index']], 'reference':reference,
                                      'arbitrarySubsequence':subsequence,'inputPreview':text[:120],
                                      'typedRowSha256':hashlib.sha256(line).hexdigest()})
        result={'taskId':task_id,'caseCount':len(lines),'disagreementCount':len(discrepancies),'disagreements':discrepancies,
                'clarifiedStatement':'Return true when a contiguous balanced substring contains a nested pair of square brackets.',
                'review':'AI-assisted clarification for author review'}
        write_json(out,result)
        print(len(lines),len(discrepancies),flush=True)
        return
    raise RuntimeError('Task absent from the accepted reference stream')


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--out',type=Path,required=True);main(p.parse_args().out)
