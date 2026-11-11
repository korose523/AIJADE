#!/usr/bin/env python3
"""One quantitative panel from complete audited real text-policy measurements. No sample or demo data."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

POLICIES=['6-newest','6-server','60-newest','60-server']
STAGES=['stored','pool','response','kept','planned','prompt']
LABELS=['Stored','Candidate\npool','Response\nunion','After echo\nremoval','Five items\nplanned','Complete in\nprompt']
STYLES={
    '6-newest':dict(color='#315E86',linestyle='--',marker='o',label='6 responses / Newest five'),
    '6-server':dict(color='#315E86',linestyle='-',marker='s',label='6 responses / Response-union order'),
    '60-newest':dict(color='#92588A',linestyle='--',marker='^',label='60 responses / Newest five'),
    '60-server':dict(color='#92588A',linestyle='-',marker='D',label='60 responses / Response-union order'),
}


def main(args):
    data=json.loads(args.summary.read_text());accepted=json.loads(args.acceptance.read_text())
    assert accepted['kernel']==accepted['product']=='PASS'
    assert data['status']=='complete-audited' and data['primaryFrame']=='answerable-v2'
    assert data['primaryQuestions']==470 and data['rawQuestions']==500 and data['captures']==2000 and data['writes']==246738
    assert set(data['policies'])==set(POLICIES)
    rows=[];values={}
    for policy in POLICIES:
        q=data['policies'][policy];assert q['questions']==470
        known=[q['stages'][stage]['mean'] for stage in STAGES[:-1]]
        low,high=q['promptLower']['mean'],q['promptUpper']['mean']
        assert all(math.isfinite(v) and 0<=v<=1 for v in [*known,low,high])
        assert all(a>=b-1e-12 for a,b in zip(known,known[1:])) and 0<=low<=high<=known[-1]+1e-12
        values[policy]=(known,low,high)
        for stage,value in zip(STAGES[:-1],known):
            rows.append(dict(policy=policy,stage=stage,meanLower=value,meanUpper=value,questions=470,sourceAttributionUnknown=q['unknown']))
        rows.append(dict(policy=policy,stage='prompt',meanLower=low,meanUpper=high,questions=470,sourceAttributionUnknown=q['unknown']))
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/'longmem_delivery_source.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    plt.rcParams.update({
        'font.family':'sans-serif','font.sans-serif':['Arial','Helvetica','DejaVu Sans'],
        'font.size':7.5,'axes.labelsize':8,'xtick.labelsize':7.5,'ytick.labelsize':7.5,
        'legend.fontsize':7.3,'svg.fonttype':'none','pdf.fonttype':42,
        'axes.spines.right':False,'axes.spines.top':False,'axes.linewidth':.65,'legend.frameon':False,
    })
    width_mm,height_mm=174,100
    fig,ax=plt.subplots(figsize=(width_mm/25.4,height_mm/25.4))
    fig.subplots_adjust(left=.105,right=.98,top=.79,bottom=.25)
    unknown_band=False
    for policy in POLICIES:
        known,low,high=values[policy];style=STYLES[policy]
        ax.plot(range(5),known,linewidth=1.1,markersize=4,
                markerfacecolor='white' if policy.endswith('newest') else style['color'],
                markeredgewidth=.8,**style)
        if abs(high-low)<1e-12:
            ax.plot([4,5],[known[-1],low],color=style['color'],linestyle=style['linestyle'],linewidth=1.1)
            ax.plot([5],[low],color=style['color'],marker=style['marker'],markersize=4,
                    markerfacecolor='white' if policy.endswith('newest') else style['color'],markeredgewidth=.8)
        else:
            unknown_band=True
            # Identification endpoints only; no invented midpoint or point estimate for unresolved attribution.
            ax.fill_between([4,5],[known[-1],low],[known[-1],high],color=style['color'],alpha=.12)
            for endpoint in [low,high]:
                ax.plot([4,5],[known[-1],endpoint],color=style['color'],linestyle=':',linewidth=.75)
                ax.plot([5],[endpoint],marker=style['marker'],markersize=4,markerfacecolor='white',markeredgecolor=style['color'])
            ax.vlines(5,low,high,color=style['color'],linewidth=1)
    ax.set_xticks(range(6),LABELS)
    ax.set_xlim(-.15,5.15);ax.set_ylim(-.025,1.035)
    ax.set_yticks([0,.2,.4,.6,.8,1]);ax.yaxis.set_major_formatter(PercentFormatter(1,decimals=0))
    ax.set_ylabel('Mean marked-turn evidence recall',labelpad=7)
    ax.grid(axis='y',color='#E6E6E6',linewidth=.5);ax.set_axisbelow(True)
    ax.tick_params(axis='x',length=0,pad=8)
    fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.55,.98),ncol=2,
               columnspacing=1.8,handlelength=2.6,labelspacing=.85)
    fig.text(.105,.09,'470 fixed question histories; source sessions overlap. Text policies only.',fontsize=7)
    fig.text(.105,.045,'Prompt endpoints bound unknown attribution; they are not confidence intervals.',fontsize=7)
    fig.canvas.draw()
    bounds=ax.get_window_extent().transformed(fig.dpi_scale_trans.inverted()).bounds
    (args.out/'longmem_delivery.alignment.json').write_text(json.dumps(dict(status='NOT_APPLICABLE_SINGLE_PANEL',quantitativeAxes=1,
        axesBoundsInches=list(bounds),tolerancePt=1.5,dimensionsMm=[width_mm,height_mm]),indent=2)+'\n')
    prefix=args.out/'longmem_delivery'
    # Fixed physical canvas; no tight-bbox resizing after final dimensions are declared.
    fig.savefig(str(prefix)+'.pdf',facecolor='white')
    fig.savefig(str(prefix)+'.svg',facecolor='white')
    fig.savefig(str(prefix)+'.png',dpi=600,facecolor='white')
    fig.savefig(str(prefix)+'.tiff',dpi=600,facecolor='white',pil_kwargs={'compression':'tiff_lzw'})
    plt.close(fig)
    caption=('Complete text-policy delivery on the corrected LongMemEval_s frame. All four prespecified response-limit/selection cells '
             'are shown under the same five-item cap and 4,000 UTF-16-unit memory budget. Points before prompt assembly are means '
             'of per-question marked-turn evidence fractions over 470 eligible histories. Where attribution is unresolved, the final '
             'endpoints bound the complete-turn evidence fraction; no midpoint is an estimate. These are identification bounds, '
             'not confidence intervals. Source sessions overlap; this plot is conditional on the compiled histories. Partial turns '
             'may still contain an answer, whose quality was not evaluated. Visibility is measured at a captured outgoing request, intercepted with a fixed local reply; no model answered. Source data: longmem_delivery_source.csv.')
    (args.out/'longmem_delivery.caption.md').write_text(caption+'\n')
    provenance=dict(summarySha256=hashlib.sha256(args.summary.read_bytes()).hexdigest(),acceptanceSha256=hashlib.sha256(args.acceptance.read_bytes()).hexdigest(),
        scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),matplotlib=matplotlib.__version__,rows=len(rows),
        backend='python',archetype='quantitative grid, single panel',center='question-case mean marked-turn evidence fraction',
        frame='answerable-v2',questions=470,policies=POLICIES,excludedCells=[],unknownIdentificationBand=unknown_band,
        sourceCaseDependence='Shared sessions; no independent-user or population inference',
        intervals='Only source-attribution identification endpoints, not sampling intervals; planned paired sensitivities are in the result table',
        imageIntegrity='Data marks drawn from complete audited JSON; no crop, smoothing, sampling, generative image or invented values',
        dimensionsMm=[width_mm,height_mm],rasterDpi=600,renderedQa='PENDING separate final-size text/collision/visual audits')
    (args.out/'longmem_delivery.provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--summary',type=Path,required=True);parser.add_argument('--acceptance',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    main(parser.parse_args())
