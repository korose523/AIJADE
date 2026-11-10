#!/usr/bin/env python3
"""Draw all configured product policy loss decompositions from the validated summary.

One quantitative panel; values are conversation-macro evidence shares, not answer accuracy.
The paired result table reports uncertainty. Unknown prompt attribution is an explicit band.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

CELLS = ['6-newest', '6-server', '60-newest', '60-server']
COLORS = ['#3C78A8', '#A796BE', '#D7A27A', '#BC8795', '#D8B75F', '#D8D9DC']
LABELS = ['Complete in prompt', 'Unattributed evidence band', 'Prompt budget / assembly',
          'Client selection', 'Threshold / server cutoff', 'Outside candidate pool']


def main(args):
    summary = json.loads(args.summary.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for mode in ['text', 'embedding']:
        primary = summary['product'][mode]['populations']['answerable']
        assert primary['population']['eligibleQuestions'] == 1536
        for cell in CELLS:
            recall = primary['policies'][cell]['recall']
            prompt = recall['prompt']
            low = prompt['mean'] if prompt['pointIdentified'] else prompt['identificationBounds'][0]
            high = prompt['mean'] if prompt['pointIdentified'] else prompt['identificationBounds'][1]
            parts = [low, high - low, recall['planned']['mean'] - high,
                     recall['response']['mean'] - recall['planned']['mean'],
                     recall['pool']['mean'] - recall['response']['mean'], 1 - recall['pool']['mean']]
            assert all(x >= -2e-6 for x in parts) and abs(sum(parts) - 1) < 2e-6
            rows.append({'mode': mode, 'cell': cell, **dict(zip(LABELS, [max(0, x) for x in parts]))})
    with (args.out / 'policy_loss_source.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['mode', 'cell', *LABELS])
        writer.writeheader(); writer.writerows(rows)
    plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Arial', 'Helvetica', 'DejaVu Sans'],
                         'font.size': 8, 'svg.fonttype': 'none',
                         'pdf.fonttype': 42, 'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.spines.left': False, 'axes.linewidth': .6, 'legend.frameon': False})
    fig, ax = plt.subplots(figsize=(7.2, 4.35))
    fig.subplots_adjust(left=.27, right=.98, top=.97, bottom=.34)
    y = list(range(8))
    left = [0.0] * 8
    handles = []
    for label, color in zip(LABELS, COLORS):
        widths = [row[label] for row in rows]
        if label == 'Unattributed evidence band' and max(widths) == 0:
            continue
        bars = ax.barh(y, widths, left=left, height=.65, color=color, edgecolor='white', linewidth=.5,
                       label=label, hatch='////' if label == 'Unattributed evidence band' else None)
        handles.append(bars)
        for i, (start, width) in enumerate(zip(left, widths)):
            if width >= .065 or (label == 'Complete in prompt' and width >= .03):
                ax.text(start + width / 2, i, f'{100 * width:.1f}', ha='center', va='center', fontsize=7,
                        color='white' if label == 'Complete in prompt' else '#202020')
        left = [a + b for a, b in zip(left, widths)]
    ax.set_yticks(y, [f"{'Text' if row['mode'] == 'text' else 'Embedding'}  ·  {row['cell'].split('-')[0]} / {'Newest' if row['cell'].endswith('newest') else 'Server'}" for row in rows])
    ax.invert_yaxis(); ax.set_xlim(0, 1)
    ax.tick_params(axis='y', length=0, pad=8)
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel('Conversation-macro evidence share', labelpad=6)
    ax.axhline(3.5, color='#777777', linewidth=.5)
    ax.legend(loc='upper left', bbox_to_anchor=(-.36, -.22), ncol=2, fontsize=7.3,
              columnspacing=2.0, handlelength=1.8, borderaxespad=0, labelspacing=.8)
    fig.text(.018, .025, 'All eight policies; 10 conversations; five-item cap and the same 4,000 UTF-16-unit budget.', fontsize=7)
    fig.canvas.draw()
    bounds = list(ax.get_window_extent().transformed(fig.dpi_scale_trans.inverted()).bounds)
    (args.out / 'policy_loss.alignment.json').write_text(json.dumps({'status': 'NOT_APPLICABLE_SINGLE_PANEL',
        'quantitativeAxes': 1, 'axesBoundsInches': bounds, 'tolerancePt': 1.5}, indent=2) + '\n')
    fig.savefig(args.out / 'policy_loss.svg', bbox_inches='tight', facecolor='white')
    fig.savefig(args.out / 'policy_loss.pdf', bbox_inches='tight', facecolor='white')
    fig.savefig(args.out / 'policy_loss.png', dpi=600, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    (args.out / 'policy_loss.provenance.json').write_text(json.dumps({'summarySha256': hashlib.sha256(args.summary.read_bytes()).hexdigest(),
        'scriptSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'matplotlibVersion': matplotlib.__version__,
        'rows': 8, 'excludedCells': [], 'center': 'conversation macro evidence fraction',
        'intervals': 'in the paired result table, not marginal error bars on stacked components',
        'unknownAttribution': 'explicit band; no zero imputation', 'imageGenerationModelCalls': 0}, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('summary', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    main(parser.parse_args())
