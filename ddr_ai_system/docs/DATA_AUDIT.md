# Data Audit

Generated: 2026-07-17T03:17:27.751454+00:00

## Independently verified results

- DDR PDFs: 1000 discovered, 1000 valid, 0 invalid.
- Pages: 1765 total; distribution {'1': 237, '2': 761, '3': 2}.
- Native digital route: 1000; scanned/OCR route: 0.
- Filename/header identity matches: 1000/1000.
- Filename/period-end date matches: 1000/1000.
- Wellbores: 14; unique period-end dates: 985.
- Embedded PDF image objects: 0.
- Missing-value sentinel occurrences in extracted text: 4025.
- Suspicious period-before-spud reports: ['15_9_19_A_1980_01_01.pdf', '15_9_19_S_1992_09_09.pdf', '15_9_19_S_1992_09_10.pdf', '15_9_19_S_1992_09_11.pdf', '15_9_19_S_1992_09_12.pdf', '15_9_19_S_1992_09_13.pdf', '15_9_19_S_1992_09_14.pdf', '15_9_19_S_1992_09_15.pdf', '15_9_19_S_1992_09_16.pdf', '15_9_19_S_1992_09_17.pdf', '15_9_F_15_2007_11_19.pdf', '15_9_F_15_2007_11_20.pdf', '15_9_F_15_2007_11_21.pdf', '15_9_F_15_2007_11_22.pdf', '15_9_F_15_2007_12_23.pdf', '15_9_F_15_2007_12_24.pdf', '15_9_F_15_2007_12_25.pdf', '15_9_F_15_2007_12_26.pdf', '15_9_F_15_2007_12_27.pdf', '15_9_F_15_2007_12_28.pdf', '15_9_F_15_2007_12_29.pdf', '15_9_F_15_2007_12_30.pdf', '15_9_F_15_2007_12_31.pdf', '15_9_F_15_2008_09_07.pdf', '15_9_F_15_2008_09_08.pdf', '15_9_F_15_2008_09_09.pdf', '15_9_F_15_2008_09_10.pdf', '15_9_F_15_2008_09_11.pdf', '15_9_F_15_2008_09_19.pdf', '15_9_F_15_2008_09_20.pdf', '15_9_F_15_2008_09_21.pdf', '15_9_F_15_2008_09_22.pdf', '15_9_F_15_2008_09_23.pdf', '15_9_F_15_2008_09_24.pdf', '15_9_F_15_2008_09_25.pdf', '15_9_F_15_2008_09_26.pdf', '15_9_F_15_2008_09_27.pdf', '15_9_F_15_2008_09_28.pdf', '15_9_F_15_2008_09_29.pdf', '15_9_F_15_2008_09_30.pdf', '15_9_F_15_2008_10_01.pdf', '15_9_F_15_2008_10_02.pdf', '15_9_F_15_2008_10_03.pdf', '15_9_F_15_2008_10_04.pdf', '15_9_F_15_2008_10_05.pdf', '15_9_F_15_2008_10_06.pdf'].
- Pressure profiles: 30 valid images; dimensions {'2100x2700': 30}.
- Pressure-time plots: 30 valid images; dimensions {'2700x1500': 30}.

## Page-count distribution

- 1 page(s): 237
- 2 page(s): 761
- 3 page(s): 2

## Reports per wellbore

- 15/9-19 A: 110
- 15/9-19 B: 27
- 15/9-19 BT2: 62
- 15/9-19 S: 49
- 15/9-19 ST2: 127
- 15/9-F-10: 71
- 15/9-F-11: 17
- 15/9-F-11 A: 14
- 15/9-F-11 B: 90
- 15/9-F-11 T2: 53
- 15/9-F-12: 165
- 15/9-F-14: 134
- 15/9-F-15: 69
- 15/9-F-15 A: 12

## Section coverage

- bit_record: 52
- casing_liner_tubing: 31
- core_information: 13
- drilling_fluid: 736
- equipment_failure_information: 148
- gas_reading_information: 127
- lithology_information: 178
- log_information: 41
- operations: 995
- perforation_information: 11
- pore_pressure: 475
- stratigraphic_information: 56
- summary_activities: 1000
- summary_planned_activities: 1000
- survey_station: 186
- welltest_information: 2

## Expected versus verified

The supplied preliminary figures were treated as hypotheses. The values above were recomputed from every supplied file.
Plot digitization counts, band classifications, calibration evidence, and processing failures are added by `scripts/process_all.py` and `scripts/evaluate_pipeline.py`.

## Limitations

- Report creation timestamps are metadata only and are not used as operational dates.
- Missing sections are treated as optional, not as parser failures.
- SoR remains undefined in the supplied material.
- Pressure-time y-axis units and cross-namespace well mappings remain unresolved.

## Period-before-spud interpretation

The independent audit lists 46 raw period-before-spud comparisons. The production parser applies a greater-than-one-day tolerance to avoid flagging boundary/rounding cases; 45 reports are therefore quarantined from default trend calculations. Both counts are retained deliberately rather than forcing the audit and policy surfaces to agree.
