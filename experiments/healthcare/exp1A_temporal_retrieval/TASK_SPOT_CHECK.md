# Exp 1A Task Spot Check

Generated on the Hetzner experiment VM from `/root/embedded-exports` for `synthea-scale-mid-fhirfix`. I sampled 10 tasks per family after schema validation and checked that each task has a coherent query, gold interval, same-family distractors, and the expected anchor source. Exp 1A now contains only the four ranking families below; the yes/no retrospective medication-history tasks were moved to Exp 1B's `counterfactual_timing` fixture.

## supersession

- Fixture: `experiments/healthcare/tasks/exp1A_tasks_supersession_mid_fhirfix.json`
- Count checked: 10 of 250
- Anchor sources observed: ['calendar_sweep']
- Concept families observed: ['analgesic_acetaminophen', 'antibacterial_cephalosporin', 'antibacterial_penicillin', 'emergency_epinephrine']
- Checked IDs: EXP1A-SUPERSESSION-00000, EXP1A-SUPERSESSION-00025, EXP1A-SUPERSESSION-00050, EXP1A-SUPERSESSION-00075, EXP1A-SUPERSESSION-00100, EXP1A-SUPERSESSION-00125, EXP1A-SUPERSESSION-00150, EXP1A-SUPERSESSION-00175, EXP1A-SUPERSESSION-00200, EXP1A-SUPERSESSION-00225
- Observation: gold intervals contain `as_of_date`; sampled distractors are same-family alternatives outside `as_of_date`, with inferred stop dates where the source medication row was open-ended.

## regimen_change

- Fixture: `experiments/healthcare/tasks/exp1A_tasks_regimen_change_mid_fhirfix.json`
- Count checked: 10 of 250
- Anchor sources observed: ['clinical_event']
- Concept families observed: ['dementia', 'hypertension', 'infection', 'pain_or_fever', 'pain_or_inflammation']
- Checked IDs: EXP1A-REGIMEN-CHANGE-00000, EXP1A-REGIMEN-CHANGE-00025, EXP1A-REGIMEN-CHANGE-00050, EXP1A-REGIMEN-CHANGE-00075, EXP1A-REGIMEN-CHANGE-00100, EXP1A-REGIMEN-CHANGE-00125, EXP1A-REGIMEN-CHANGE-00150, EXP1A-REGIMEN-CHANGE-00175, EXP1A-REGIMEN-CHANGE-00200, EXP1A-REGIMEN-CHANGE-00225
- Observation: gold intervals contain `as_of_date`; sampled distractors are same-family alternatives outside `as_of_date`, with inferred stop dates where the source medication row was open-ended.

## recurring_condition

- Fixture: `experiments/healthcare/tasks/exp1A_tasks_recurring_condition_mid_fhirfix.json`
- Count checked: 10 of 250
- Anchor sources observed: ['clinical_event']
- Concept families observed: ['acute bronchitis', 'acute viral pharyngitis', 'viral sinusitis']
- Checked IDs: EXP1A-RECURRING-CONDITION-00000, EXP1A-RECURRING-CONDITION-00025, EXP1A-RECURRING-CONDITION-00050, EXP1A-RECURRING-CONDITION-00075, EXP1A-RECURRING-CONDITION-00100, EXP1A-RECURRING-CONDITION-00125, EXP1A-RECURRING-CONDITION-00150, EXP1A-RECURRING-CONDITION-00175, EXP1A-RECURRING-CONDITION-00200, EXP1A-RECURRING-CONDITION-00225
- Observation: gold answers identify a specific acute episode by start date; distractors are other episodes of the same condition outside the anchor date.

## dose_escalation

- Fixture: `experiments/healthcare/tasks/exp1A_tasks_dose_escalation_mid_fhirfix.json`
- Count checked: 10 of 250
- Anchor sources observed: ['calendar_sweep']
- Concept families observed: ['acetaminophen', 'donepezil hydrochloride', 'penicillin potassium']
- Checked IDs: EXP1A-DOSE-ESCALATION-00000, EXP1A-DOSE-ESCALATION-00025, EXP1A-DOSE-ESCALATION-00050, EXP1A-DOSE-ESCALATION-00075, EXP1A-DOSE-ESCALATION-00100, EXP1A-DOSE-ESCALATION-00125, EXP1A-DOSE-ESCALATION-00150, EXP1A-DOSE-ESCALATION-00175, EXP1A-DOSE-ESCALATION-00200, EXP1A-DOSE-ESCALATION-00225
- Observation: gold intervals contain `as_of_date`; sampled distractors are same-family alternatives outside `as_of_date`, with inferred stop dates where the source medication row was open-ended.

## Notes

- The medication export often omits `STOP`; the generator infers benchmark-local stop dates when a later same-family prescription begins. This is required so same-family distractors are not all active forever.
- The generator enforces at least one distractor per task and writes a summary file at `experiments/healthcare/tasks/exp1A_tasks_summary_mid_fhirfix.json`.
