"""Concept-family maps for Exp 1A task generation.

The corrected Synthea embedded export used for ``synthea-scale-mid-fhirfix``
preserves medication ``DESCRIPTION`` and ``CODE`` fields, but it does not carry
an authoritative ATC class column in the normalized row payload. These maps are
therefore deliberately small substring maps over medication descriptions. They
exist only to create same-family distractors for the benchmark; they are not a
clinical terminology system.

The values are stable benchmark families used by
``SyntheaQAGenerator.generate_*_tasks``. If a future export adds first-class ATC
or indication fields, replace the substring maps with those authoritative
fields and keep the public task schema unchanged.
"""

from __future__ import annotations

ATC_CLASS_MAP: dict[str, str] = {
    "penicillin": "antibacterial_penicillin",
    "amoxicillin": "antibacterial_penicillin",
    "augmentin": "antibacterial_penicillin",
    "cefuroxime": "antibacterial_cephalosporin",
    "nitrofurantoin": "urinary_antibacterial",
    "acetaminophen": "analgesic_acetaminophen",
    "ibuprofen": "analgesic_nsaid",
    "naproxen": "analgesic_nsaid",
    "oxycodone": "opioid_analgesic",
    "hydrocodone": "opioid_analgesic",
    "nitroglycerin": "antianginal_nitrate",
    "clopidogrel": "antiplatelet",
    "simvastatin": "lipid_lowering_statin",
    "atorvastatin": "lipid_lowering_statin",
    "amlodipine": "antihypertensive_calcium_channel_blocker",
    "captopril": "antihypertensive_ace_inhibitor",
    "lisinopril": "antihypertensive_ace_inhibitor",
    "losartan": "antihypertensive_arb",
    "furosemide": "loop_diuretic",
    "metformin": "diabetes_biguanide",
    "insulin": "diabetes_insulin",
    "liraglutide": "diabetes_glp1",
    "albuterol": "asthma_rescue_beta_agonist",
    "fluticasone": "asthma_controller_inhaled_steroid",
    "salmeterol": "asthma_controller_laba",
    "alendronic": "osteoporosis_bisphosphonate",
    "galantamine": "dementia_cholinesterase_inhibitor",
    "donepezil": "dementia_cholinesterase_inhibitor",
    "memantine": "dementia_nmda_antagonist",
    "loratadine": "allergy_antihistamine",
    "diphenhydramine": "allergy_antihistamine",
    "cetirizine": "allergy_antihistamine",
    "epinephrine": "emergency_epinephrine",
    "depo-provera": "contraceptive_hormonal",
    "mirena": "contraceptive_hormonal",
    "nexplanon": "contraceptive_hormonal",
    "nuvaring": "contraceptive_hormonal",
    "jolivette": "contraceptive_hormonal",
    "camila": "contraceptive_hormonal",
}

INDICATION_MAP: dict[str, str] = {
    "penicillin": "infection",
    "amoxicillin": "infection",
    "augmentin": "infection",
    "cefuroxime": "infection",
    "nitrofurantoin": "urinary_tract_infection",
    "acetaminophen": "pain_or_fever",
    "ibuprofen": "pain_or_inflammation",
    "naproxen": "pain_or_inflammation",
    "oxycodone": "pain",
    "hydrocodone": "pain",
    "nitroglycerin": "coronary_heart_disease",
    "clopidogrel": "coronary_or_stroke_prevention",
    "simvastatin": "lipid_management",
    "atorvastatin": "lipid_management",
    "amlodipine": "hypertension",
    "captopril": "hypertension",
    "lisinopril": "hypertension",
    "losartan": "hypertension",
    "furosemide": "fluid_or_blood_pressure_control",
    "metformin": "diabetes",
    "insulin": "diabetes",
    "liraglutide": "diabetes",
    "albuterol": "asthma_or_copd",
    "fluticasone": "asthma_or_copd",
    "salmeterol": "asthma_or_copd",
    "alendronic": "osteoporosis",
    "galantamine": "dementia",
    "donepezil": "dementia",
    "memantine": "dementia",
    "loratadine": "allergy",
    "diphenhydramine": "allergy",
    "cetirizine": "allergy",
    "epinephrine": "allergic_emergency",
    "depo-provera": "contraception",
    "mirena": "contraception",
    "nexplanon": "contraception",
    "nuvaring": "contraception",
    "jolivette": "contraception",
    "camila": "contraception",
    "paclitaxel": "cancer_treatment",
    "oxaliplatin": "cancer_treatment",
    "cisplatin": "cancer_treatment",
    "etoposide": "cancer_treatment",
}

CHRONIC_CONDITION_SET: set[str] = {
    "38341003",  # Hypertension
    "44054006",  # Diabetes
    "53741008",  # Coronary Heart Disease
    "195967001",  # Asthma
    "13645005",  # Chronic obstructive bronchitis
    "26929004",  # Alzheimer's disease
    "64859006",  # Osteoporosis
}
