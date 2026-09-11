# NGS / PRomop Genomics integration contract

Status: proposed design, 2026-09-11; no runtime changes in this PR. Supplements
[alignment §10.3](promop-alignment.md#103-ngs-report--structured-finding-with-linked-attributes).
PRomop implementation tracking: [#1179](https://github.com/healthkey-ai/promop/issues/1179),
[#1180](https://github.com/healthkey-ai/promop/issues/1180),
[#1181](https://github.com/healthkey-ai/promop/issues/1181).

## Why change the original example?

The original gene/HGVS Measurement and separate origin Observation had no stable
finding relationship. Its snippet also contained pathogenicity and VAF that the
structured output omitted. Gene/date cannot distinguish multiple variants,
specimens, repeat tests or amended reports. Holding only origin commits an
incomplete finding.

Retain one logical `genomic_variant` object through extraction and review.
PRomop owns its parent Measurement and linked attribute Measurements/Observations.
CDEW does not invent OMOP concept IDs, source keys or event links.

## Variant attributes

These are keys in the PRomop Genomics implementation under review, **not a promise
about the deployed API**. Pin a validated receiving-contract version.

| Group | Source keys | Meaning / review guidance |
|---|---|---|
| Identity | `gene`, `variant_name`, `variant`, `variant_description` | Symbol; short name; transcript DNA change / legacy variant string; full verbatim description. A display name is not a stable identity. |
| Reference / change | `genome_assembly`, `transcript_reference_sequence_id`, `genomic_reference_sequence_id`, `genomic_dna_change`, `amino_acid_change` | Preserve versioned accessions and stated HGVS; DNA and protein changes stay separate. |
| Location / class | `chromosome`, `cytogenetic_location`, `variant_category`, `zygosity` | Include structural findings, not just substitutions; do not infer zygosity from VAF. |
| Origin / result | `origin`, `genomic_source_class`, `assessment` | Preserve independently. Assessment: present, absent, not_tested, no_call, indeterminate; never infer from an empty priority row. |
| Quantification | `allelic_frequency`, `allelic_frequency_unit` | Sample **variant allele frequency (VAF)**, not population frequency. `%`: 0–100; `1`: 0–1. Zero is real. Current precision: five decimal places. |
| Interpretation | `interpretation`, `classification_framework`, `interpretation_date`, `evidence_source` | Reported interpretation, framework/version and evidence. Pathogenicity is not synonymous with treatment actionability. |
| Assay / provenance | `test_date`, `variant_analysis_method_type`, `specimen_id`, `specimen_type`, `collection_date`, `report_id`, `laboratory` | Stated identifiers and dates; collection, testing, report issuance and reinterpretation are distinct events. |

Only `gene` is required at extraction; missing receiver-required values hold the
fact for review rather than encouraging invention. If no gene is stated for a
structural finding, preserve it in report staging until an appropriate receiving
contract exists; do not manufacture a gene to satisfy this interface.

Keep API names for compatibility; prefer UI labels **Sample VAF**, **Transcript
DNA change**, **Protein change**, **Reported interpretation**, **Analysis method**.
Do not send new aliases such as `protein_hgvs` unless accepted by the pinned schema.
Copy separately stated DNA/protein substrings with evidence; do not calculate one
from the other during extraction.

The MM/FL/BC/MCL/CLL priority catalog guides review, not which findings may be
extracted. Missing priority rows mean no recorded data, not negative tests. Retain
arbitrary genes and repeated findings. Never auto-select example variants or
normalize uncertain gene names without an expert-approved migration.

## Report context and proposed extensions

Store shared report context once in CDEW and reference it from findings. The first
PRomop API carries a limited subset per finding; it does **not** expose normalized
report, specimen, assay or interpretation-history resources.

| Level | Additional attributes / objects proposed for design |
|---|---|
| Report | Accession namespace/ID, issued date, preliminary/final/amended status, report version and superseded report, source document, laboratory. |
| Assay / specimen | Panel name/version, genes/regions actually tested, specimen type/ID/collection date, tumor content/purity, detection limits, coverage and assay limitations. |
| Variant | Reference/alternate alleles, genomic coordinates and convention, HGNC/external variant IDs, read depth/alternate reads, copy number, fusion partners/breakpoints. |
| Interpretation | Separate pathogenicity, somatic evidence tier and therapeutic implication; disease context, framework/version, evidence and dated history. |
| Assay biomarkers | TMB, MSI, HRD as separate results with units/methods/report links, not invented genes or fields repeated on every variant. |

These are **proposed extensions**, not accepted Genomics payload keys. Retain them
in versioned staging with provenance and visible not-yet-committed status until
receiving schemas are implemented. Never silently discard or squeeze them into
unrelated fields. Keep negative/no-variant reports even when `facts=[]`: a negative
finding applies only within the assay's tested scope and detection limits.

This separation follows the
[HL7 Genomics Reporting overview](https://www.hl7.org/fhir/uv/genomics-reporting/STU3/general.html)
and [variant reporting guidance](https://www.hl7.org/fhir/uv/genomics-reporting/STU3/sequencing.html).
It is not a claim of complete FHIR profile conformance by either application.

## Commit contract and release gates

The PRomop Genomics implementation provides:

- `GET/POST /api/v1/patient-records/{person_id}/genomics/`;
- `GET/PATCH/DELETE /api/v1/patient-records/{person_id}/genomics/{variant_id}/`;
- `GET /api/v1/patient-records/{person_id}/genomics-catalog/?disease=BC`;
- named PatientRecord list PATCH, e.g. `genomics_brca1`. This **replaces the marker's
  list**; `[]` clears it. CDEW incremental imports must not use replacement lists.

After the gates below pass, submit complete approved findings. PRomop validates
mappings, writes parent and components atomically and returns the parent Measurement
`id`. Store it with source report/finding identity, patient, organization and CDEW
provenance. Correct by ID and retract through specialized DELETE, not generic CRUD
that retracts only the parent.

Live CDEW genomic commit requires these capabilities on the deployed PRomop version:

1. **Idempotency/reconciliation:** server-side identity scoped by authenticated
   organization, patient, source system, report identity/version and stable source
   finding identity. Concurrent retries and timeout-after-commit return the same ID.
   Gene/date, short variant names and extraction-run IDs are insufficient. A new
   extractor version must reconcile source findings, not duplicate them. Define
   amendment replacement/retraction without erasing history. Plain Genomics POST
   does not currently provide this guarantee.
2. **Document provenance:** a supported adapter records DOCUMENT_EXTRACTION and
   links the result to document/extraction/reviewer versions. Source spans remain
   CDEW-owned. The current Genomics payload does not accept `source` or an arbitrary
   provenance envelope; an ignored extra field is not integration.
3. **Explicit dates:** undated extracted findings must not use the interactive
   writer's default of today as their test date. Hold for review or agree a receiving
   missing-date policy. Do not substitute upload/report date for collection/testing
   without an explicit reviewed rule.
4. **Versioned schema/round trip:** publish the custom action schema and prove
   populated attributes survive re-derivation. Until then, use a reviewed captured
   contract fixture for offline extraction tests only.

Hold the **whole finding** until these gates pass. Do not report success after only
gene/HGVS was saved. Mixed documents show per-fact committed/held state; there is
no assumed document-wide transaction across adapters.

### Why not generic FHIR sync now?

PRomop `patient_portal/api/fhir/sync.py::_parse_obs` truncates `valueString` to 60
characters and does not parse the genomic component/report graph.
`_insert_discrete_observations` deduplicates on date/datetime, concept/source and
numeric value, not variant text or specimen/report identity. Same-gene qualitative
variants can collapse. `_upsert_clinical` has a different source/date identity;
neither is a source-finding import contract.

A future FHIR adapter can accept DiagnosticReport/GenomicsReport references,
variant Observation components, specimen links and `hasMember`/`derivedFrom`.
Valid FHIR does not establish that PRomop ingests those relationships. Keep the
base-object FHIR adapter; do not extend it to Genomics without contract tests.

## Acceptance tests

Cover two variants in one gene/date; identical variants from distinct specimens;
zero/percent/fraction VAF; descriptions over 60 characters; independent origin/source
class; interpretation/provenance round trips; missing dates; negative/no-call/untested
versus missing; reports with no variants; amendments; timeout-after-commit/concurrent
retry; source-version reruns; one-finding correction/retraction; patient/org isolation;
unapproved mappings; and no clinical writes from disease-priority placeholders.

## Expert review questions

- Which report/accession namespaces, specimen IDs and panel versions are mandatory?
- What coverage/detection limits make a negative result interpretable? How should
  report-only negative statements be represented?
- Which structural/copy-number/fusion attributes and coordinate conventions come
  first? How should findings without a specific gene be represented?
- Which frameworks distinguish germline pathogenicity from somatic tier/actionability?
  Should interpretations be separate dated records?
- How should tumor-only origin uncertainty, tumor content and sample VAF be displayed?
- Agree source-finding identity and amendment rules; assign ownership and a deployment
  version for the receiving import contract.
