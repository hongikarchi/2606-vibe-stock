# GROUNDING-DISCIPLINE Defense vs TRAINING/PRIOR-KNOWLEDGE Bias

Interpretation-integrity layer plugging into the extraction + analysis layers of the main KG architecture
(`research/01-architecture-workflow-raw.json`). Targets ONE bias: shared parametric blind spots
(training/prior-knowledge). Integrates shared machinery (span-grounding, bi-temporal stamps, source
credibility/independence, entity resolution) — does NOT re-derive it.

## Root cause (principle, not a mechanism)
Debate among same-family models is the NULL operation for this bias: a shared base model = a shared
parametric prior = a shared blind spot, and "independent" critics that share a base model have CORRELATED
errors (arXiv:2506.07962 — correlation is higher for same-developer / same-base-architecture models).
The only real adversary is therefore non-parametric: structural set-difference checks, a CROSS-FAMILY
NLI verifier, and an as-of-T background KB. LLM-as-bias-judge is disqualified as the primary check by
self-preference bias (arXiv:2410.21819; NeurIPS 2024 — self-recognition linearly predicts self-favoring;
arXiv:2604.06996 — persists even with objective rubrics).

## Honest boundary
Grounding guarantees faithfulness-TO-SOURCE, not TRUTH. A source repeating a training-era falsehood is
faithfully extracted as a falsehood — that is the credibility / corroboration / source-independence layer's
job, NOT grounding's. Grounding kills PARAMETRIC INJECTION, not SOURCE ERROR.

## Two distinct output paths (consistency with "expose-don't-collapse")
- Parametric injection detected -> ERROR -> quarantine (drop from graph-of-record, log for human review).
- Source-vs-background-KB CONFLICT -> DISPERSION -> surface to human as a first-class flagged node, never
  silently resolved.

## (a) Closed-book / grounded extraction protocol  [cheap-on-everything]
Prompt discipline the doc lacks: the doc has span fields (lines 259-265) but never forbids parametric
assertion. Add explicit closed-book instruction: extract ONLY from the provided text; every node/edge MUST
carry source_span char offsets + doc_id + event_time/ingest_time; emit `unknown`/abstain rather than fill
from world knowledge. Enforced through the existing strict function-calling schema (line 235-241) by making
span offsets a REQUIRED field. Structural validator (non-LLM): the cited offsets must EXIST in the source
doc — fabricated/out-of-range spans are rejected before the DB. Abstention is a feature (AI structures,
human judges). Refs: anchor-constrained provenance MDPI 15(3):178; context-faithful prompting arXiv:2303.11315.

## (b) Groundedness verification — CROSS-FAMILY NLI  [expensive-on-salient-only]
Do NOT add a new NLI layer — line 654 already flags over-verification ("pick one"). REUSE the doc's existing
DeBERTa/multilingual NLI (lines 275-281), reframed: the point is not just accuracy, it is INDEPENDENCE. The
verifier must be a DIFFERENT family from the extractor (e.g. Claude extracts -> DeBERTa-v3-mnli / Korean NLI
checks), so the checker's parametric prior cannot collude with the extractor's. Premise = cited span;
hypothesis = extracted triple; entailment below threshold -> flag/quarantine. A small NLI model is cheap,
local, and a genuinely cross-family adversary. Gate to high-stakes / low-credibility-but-high-rank edges
(existing salience+credibility gate). Refs: HALT-RAG arXiv:2509.07475; Auto-GDA arXiv:2410.03461 (cheap
domain-adapted grounding verifier); TRUE entailment framing.

## (c) Knowledge-cutoff LEAKAGE test — NER + set-difference  [cheap-on-everything] — STRONGEST non-LLM adversary
Pure structural test, no LLM. For each extracted node/edge, decompose to atomic claims and check every
salient TOKEN — named entities, NUMBERS, DATES, and RELATION triples — is traceable to
(cited source span  UNION  alias-table expansion of those spans). Anything traceable to NEITHER = parametric
injection candidate -> quarantine + human review.
- INTEGRATION SEAM with entity resolution: a node carrying `005930` / CIK / "Samsung Electronics" when the
  source said 삼성전자 is the RESOLUTION layer doing its job (alias expansion), NOT injection — must be
  whitelisted, or every resolved node false-positives.
- The dangerous finance injection is a NUMBER (a revenue figure) or an EDGE (a supply-chain link) the model
  "knows" but the span does not contain — claim-level decomposition catches exactly this. Refs:
  "All Leaks Count" arXiv:2602.17234 (Shapley-DCLR claim-level temporal leakage); Look-Ahead-Bench
  arXiv:2601.13770; ExAnte arXiv:2505.19533.

## (d) Legitimately-needed background knowledge without contamination  [cheap KB lookup; expensive only on conflict]
Closed-book != no background; it means no UNCITED background. Needed background ("HBM is a memory chip",
sector membership) comes from a CURATED, BI-TEMPORAL (as-of-T) KB and is CITED + provenance-tagged exactly
like a source span. Anything traceable to neither the document nor the KB = injection (path c).
Two hard consequences:
1. The KB MUST be queried as-of-T (event-time) or it reintroduces LOOKAHEAD bias — background must not be
   newer than the analysis date. Ties into the bi-temporal layer.
2. A CONFLICT between source and background-KB is SURFACED to the human (dispersion), never silently
   resolved. Refs: recall-based prompting / constraining to the past arXiv:2606.05804; FaithfulRAG
   arXiv:2506.08938; ParamMute (suppress knowledge-critical FFNs).

## Cost cascade summary
- On EVERYTHING (cheap, structural/non-LLM): (a) closed-book + span-existence check, (c) leakage
  set-difference, (d) KB-lookup-or-flag.
- On SALIENT only (expensive): (b) cross-family NLI entailment, (d) conflict adjudication/surfacing.
Primary fix = structural (a/c/d). Second LLM opinion helps ONLY if cross-family AND gated to salient
contested items; same-family debate is the null operation for this bias.
