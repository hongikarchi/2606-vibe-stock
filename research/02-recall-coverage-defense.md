# RECALL / COVERAGE Defense against SELECTION / OMISSION bias

Interpretation-Integrity Layer, plugging into the main all-Postgres GraphRAG architecture
(`research/01-architecture-workflow-raw.json`). This document designs ONE of three sibling
defenses. It owns SELECTION/OMISSION only; it references (does not re-derive) the
source-credibility / independence / corroboration machinery already designed in the
analyze layer, and it hands off to the sibling CONSENSUS and TRAINING-PRIOR defenses.

---

## 0. Why debate is the wrong tool here (the thesis, made concrete)

Naive multi-agent debate cannot fix selection/omission because **both debaters receive the
same already-filtered candidate set**. The pre-filter cascade (trafilatura → lingua →
Kiwi/MeCab-ko → MinHash-LSH → BGE-M3 near-dup → salience/credibility gate) and the
extraction tiering have ALREADY thrown things away before any debate could start. Two LLMs
then argue over what is PRESENT in the surviving set; neither can argue about what is
ABSENT, because absence is not in their input. Debate optimizes the ranking of the visible;
omission is about the invisible.

The fix is not dialectical, it is **measurement**. You make omission measurable by building a
cheap, NON-LLM recall baseline that enumerates candidates EXHAUSTIVELY, then comparing what
the LLM kept/ranked against that baseline. The adversary is a structural set-difference, not
another LLM. This matters because of the root cause: an LLM critic shares the base model's
**self-preference bias** — it assigns higher scores to lower-perplexity / more-familiar text
([Self-Preference Bias in LLM-as-a-Judge, arXiv:2410.21819](https://arxiv.org/abs/2410.21819);
[Quantifying and Mitigating Self-Preference Bias of LLM Judges, arXiv:2604.22891](https://arxiv.org/abs/2604.22891)).
A same-family critic would share the omitting model's blind spots, so it is not an
independent adversary. A non-LLM enumerator has genuinely uncorrelated error.

---

## 1. TWO coverage checkpoints (not one)

Selection/omission happens at two different layers, each needing a DIFFERENT non-LLM
baseline. They CHAIN: checkpoint 2's baseline only exists for a node because checkpoint 1
didn't drop it.

| | CHECKPOINT 1 — Extraction coverage | CHECKPOINT 2 — Ranking/summarization coverage |
|---|---|---|
| **Omission** | LLM emits triples from cleaned text but drops an entity/event that WAS in the text | LLM's "important" set / map-reduce summary drops a node that IS in the graph with high structural salience |
| **Unit** | per-document / per-span | per-cluster / per-as-of-T-graph-view |
| **Non-LLM baseline** | NER + cashtag/ticker gazetteer + GDELT pre-extracted tags + event-trigger lexicon on the same span | analyze-layer credibility-weighted PPR + independence-corroboration + burst novelty (already computed) |
| **Cost tier** | CHEAP, on EVERYTHING | BATCH, reuses analyze layer; expensive critic only on contested high-salience |
| **Metric** | extraction recall@span (set overlap) | RBO + recall@k between LLM-important and structural-salient lists |

This split is load-bearing for the schema: the two `defenses[]` entries below correspond to
these two checkpoints, plus a third entry for the dedicated what's-missing critic.

---

## 2. The non-LLM recall baseline

### 2a. Extraction baseline (checkpoint 1) — runs on EVERY surviving document

Reuses machinery already in the pre-filter cascade, so marginal cost ≈ 0:
- **Korean morphological NER**: Kiwi / MeCab-ko (already in the cascade) → proper-noun /
  org / person candidates.
- **Ticker/cashtag/slang gazetteer match**: the resolve layer's time-scoped alias table
  (삼전, 하닉, $-cashtags) run as a deterministic dictionary pass over the raw span.
- **GDELT pre-extracted entities/themes/tone**: free, already ingested for the global news
  spine — a second independent extractor whose recall is uncorrelated with the LLM's.
- **Event-trigger lexicon**: closed list of catalyst verbs/nouns (유상증자, 자사주, guidance,
  recall, 공시, M&A) → event candidates.

The UNION of these is the **candidate set C_extract** for that span. The LLM's emitted
triples give the **extracted set E**. Omission candidates = `C_extract ∖ entities(E)`.

### 2b. Ranking/salience baseline (checkpoint 2) — runs in the analyze batch

This baseline is NOT new code; it is the analyze layer read out as a ranked list:
- **Structural centrality** = the existing credibility-weighted Personalized-PageRank with
  TrustRank teleport (NOT raw centrality — raw centrality ranks LOUD over TRUE).
- **Corroboration** = the existing independence-aware truth-discovery score (CIB/pump
  collapse already folds a coordinated cluster to ~one effective source).
- **Novelty/burst** = Kleinberg two-state burst-detection automaton over the document stream
  ([Kleinberg, Bursty and Hierarchical Structure in Streams, 2002](https://www.cs.cornell.edu/home/kleinber/kdd02.html)),
  i.e. terms/entities whose arrival rate spikes — first-story/novelty-detection lineage from
  Topic Detection & Tracking.

These three combine into a structural-salience score per node, producing the ranked list
**S_struct**. The LLM's GraphRAG map-reduce "important set" gives the ranked list **L_llm**.

**BLOCKING CONSTRAINT — novelty must be independence-weighted.** Naive Kleinberg burst
detection flags a pump-and-dump as "high novelty, must-cover" — the exact LOUD-over-TRUE
trap. Burst is therefore multiplied by the existing effective-independent-source count from
the CIB/pump-collapse machinery before it can raise salience. One rumor echoed across 200
종토방 posts is ONE effective source; CIB's operative test is whether accounts are "behaving
as independent humans would if they had independently reached the same conclusion"
([Detection and Characterization of Coordinated Online Behavior, arXiv:2408.01257](https://arxiv.org/html/2408.01257v1)).
Reference, do not rebuild — this is the analyze/credibility layer's machinery.

---

## 3. The coverage metric

Plain Kendall-τ / Spearman are WRONG here because the two lists are **non-conjoint**
(different membership: the LLM list and the structural list need not contain the same items)
and we care more about the TOP than the tail.

- **Set coverage**: `recall@k = |topk(L_llm) ∩ topk(S_struct)| / |topk(S_struct)|` — fraction
  of structurally-salient nodes the LLM kept ([Recall@K is the workhorse coverage metric for
  candidate-generation / RAG pipelines](https://www.emergentmind.com/topics/technical-recall-k)).
  For checkpoint 1, the analogous quantity is **extraction recall@span** =
  `|entities(E) ∩ C_extract| / |C_extract|`.
- **Ordering-aware, top-weighted, non-conjoint**: **Rank-Biased Overlap (RBO)**
  ([Webber, Moffat, Zobel, "A similarity measure for indefinite rankings", ACM TOIS 28(4),
  2010](https://dl.acm.org/doi/10.1145/1852102.1852106)). RBO handles non-conjointness,
  weights high ranks more heavily via a persistence parameter p, is monotonic with depth,
  and returns [0,1]. This is the headline divergence number between L_llm and S_struct.

**Why we need this**: position bias in LLM listwise ranking/summarization is the empirical
mechanism of the omission we are measuring — passages near the end are less likely to be
promoted, and "lost-in-the-middle" causes the model to neglect the middle of long contexts
([LLM-based Listwise Reranking under the Effect of Positional Bias, arXiv:2604.03642](https://arxiv.org/abs/2604.03642)).
RBO/recall@k is how we DETECT it without trusting another LLM.

### Divergence is BIDIRECTIONAL — the two set-differences mean different things

- `S_struct ∖ L_llm` (structurally salient but LLM dropped) = **omission candidates** →
  surface to analyst as "the structural baseline says these salient nodes were dropped."
- `L_llm ∖ S_struct` (LLM elevated but structurally weak) = EITHER the LLM caught novel KR
  slang / an emerging cashtag the NER/gazetteer missed (superior recall, good) OR a
  **hallucination / parametric assertion** (bad). This set-difference is NOT scored here; it
  is **handed off to the sibling TRAINING-PRIOR/grounding defense** (every claim must trace
  to a retrieved source span+timestamp). The coverage layer flags it and routes; it does not
  adjudicate it.

### As-of-T discipline (no lookahead through the coverage channel)

Both baselines run on the **same as-of-T candidate set** as the LLM, parameterized by
`(T_knowledge, T_valid)` exactly like the credibility machinery. Penalizing the LLM for
missing a node whose evidence arrived AFTER the window would reintroduce lookahead through
the coverage channel — the same failure the bi-temporal layer guards against in the
credibility channel. Coverage is a point-in-time quantity.

### Surface, do NOT auto-correct (STANCE compliance)

The metric emits a report — "RBO = 0.62; structural baseline flags N salient nodes the
summary dropped; here they are." It does **not** force the LLM to re-include them and does
**not** gate/block the pipeline by auto-filling. Auto-filling would collapse the dispersion
we are trying to expose. The human decides whether a dropped node matters. "Don't collapse
the distribution — show it."

---

## 4. The dedicated "what's-missing" critic

**The key design point: the critic must see the FULL candidate set, never the LLM's filtered
output.** A critic that reads only the LLM's emitted triples/important-set is structurally
incapable of naming an omission — the omitted item is, by definition, not in its input. This
is the same failure as debate. So the critic's input is `S_struct ∖ L_llm` (checkpoint 2) or
`C_extract ∖ entities(E)` (checkpoint 1) — the **already-computed structural set-difference**.

This makes the critic cost-tier-legal AND independent:
- The **divergence computation is non-LLM** (NER union, PPR, burst, set-difference, RBO). The
  structural diff IS the adversary; it has uncorrelated error vs the extractor.
- The **LLM only writes up the already-flagged divergences** for the human — "node X
  (high PPR, recent burst, 3 independent sources) is absent from the summary; likely
  relevance: …". It generates prose over a fixed, externally-computed list; it cannot quietly
  re-omit, because the list of omissions was produced before it ran.

If instead another LLM were asked "what did the first LLM miss?" over the same filtered
output, it would share the base model's selection prior (correlated error) and exhibit
self-preference — useless. The non-LLM structural diff is what breaks the correlation.

---

## 5. Cost tiering

| Stage | When | Cost | What runs |
|---|---|---|---|
| Extraction baseline (cp1) | every surviving doc, inline | CHEAP (reuses cascade NER + gazetteer + GDELT) | non-LLM only |
| Extraction recall@span gate | every doc | CHEAP | numeric; alert if recall < threshold |
| Structural-salience baseline (cp2) | analyze batch | reuses PPR/truth-discovery/burst already computed | non-LLM only |
| RBO / recall@k coverage | analyze batch, per cluster | CHEAP (arithmetic over two lists) | non-LLM only |
| What's-missing critic write-up | ONLY on contested high-salience clusters where RBO < threshold OR |S_struct∖L_llm ∩ high-trust| > 0 | EXPENSIVE (Opus-class, salient only) | LLM prose over fixed non-LLM list |
| Cross-family second opinion | rare, highest-stakes contested edges only | MOST EXPENSIVE | optional cross-provider LLM, never same-family |

Cheap structural/grounding checks on EVERYTHING; expensive multi-perspective only on
high-salience/contested items. The critic LLM is invoked on a tiny fraction of clusters,
gated by the cheap non-LLM RBO/recall metrics.

---

## 6. Honest scope boundary (goes in risks)

The baseline measures omission **relative to the crawled corpus**. It CANNOT detect what was
never ingested — the platform you don't watch, the Reddit excluded on TOS/AI-training
grounds, the Telegram channel you don't have. "Omission becomes measurable" is TRUE for
extraction/structuring omission and FALSE for ingestion omission. The only proxy for
ingestion coverage is a **source-type diversity count** (are KR Tier-1 filings, KR Tier-2
community, US filings, global news all represented for this entity/theme?), surfaced as a
separate, explicitly-labeled coverage dimension — never conflated with the structural recall
number.

**Minority-view seam (hands off to CONSENSUS defense).** S_struct is weighted by centrality +
corroboration, so a genuinely minority/dissenting view is — BY CONSTRUCTION — low-corroboration
and often low-centrality. This metric will therefore NOT flag it when the LLM drops it. That is
intentional: preserving minority/dissent as first-class, never-collapsed nodes is the sibling
CONSENSUS defense's job, not this one. Stated explicitly so a reader of this layer in isolation
does not wrongly conclude "all omission is now measurable" — high-salience omission is measurable
here; minority-view omission is covered by the consensus layer.

Secondary risks:
- The structural baseline is NOT ground truth. `L_llm ∖ S_struct` can be the LLM legitimately
  beating the NER on novel slang; only the grounding handoff distinguishes that from
  hallucination. Treating the baseline as oracle would punish good recall.
- Checkpoint 1's baseline depends on NER/gazetteer recall for KR retail slang; a weak gazetteer
  understates C_extract and hides omission. Audit with a hand-labeled KR+EN gold set
  (B-cubed / pairwise P/R), tracking abstain-rate and recall spikes as distribution-shift
  signals — consistent with the analyze layer's existing open question on the credibility
  gold set.
- Burst novelty without independence-weighting elevates pump-and-dump; the mitigation is the
  CIB-collapse multiply, which itself can OVER-suppress legitimate independent corroboration
  of one DART filing. Default to low-independence (safe) and surface the assumption.
