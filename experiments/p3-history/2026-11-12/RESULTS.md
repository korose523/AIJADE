# Complete configured history and recording results

All 50 trajectories and 9,930 captures completed in one admitted attempt. Independent
raw reconstruction passes all rows and 1,986 logical post-turn state triplets.
50 owned databases were cleaned; all 200 raw gzip streams close correctly.

On the 1,536 annotated answerable questions per arm, complete-prompt source recall
is 0.115977–0.119852 for static/history and 0.055463–0.059338 for all three recording
schedules. These are identification bounds, not confidence intervals. Native pool
bounds remain 0.589523–0.593398. Previously recorded questions occupy 5,815 of 7,518
selected slots in each recording arm. Current-write timing changes API evidence
coverage, but not the final prompt endpoint in these scripts. No corpus prompt is
truncated. Four source-ambiguous blocks per recording arm remain unknown.

The 1,527 fully located sensitivity questions give a conversation-mean recording
contrast of -0.060429, bootstrap interval [-0.077600,-0.042581], exact sign-flip
p=0.001953125, Holm p=0.0078125. The ten dialogue differences are negative. All
four primary contrasts retain unlocated annotation bounds and have null p-values.
Natural dialogue, generated answers, default fact maintenance, full Web/QQ races,
formal hardware qualification and independent human review remain unmeasured.

The first raw audit passed. The original corruption script then correctly exposed
its own no-op fixture: setting an already empty whole-query pool to empty made no
change. Its source and failed log remain intact. `test_rejections_v2.py` changes
only the two destructive fixture selectors to choose nonempty records; the frozen
audit/scorer and measured bytes are unchanged. Its 17 controls and seven additional
structural/coherently rebound controls pass. No corpus rerun or prefix merge was
performed. `verify_archive.py` is the complete offline verification entry.

All source-derived text retains LoCoMo CC BY-NC 4.0. Execution source and the later
archive/validation source are distinguished in the frozen build and manifest.
