# Designing an AI-Assisted Personal Knowledge Management System: A Research Synthesis & Build Blueprint

## TL;DR
- **Build the Karpathy "LLM Wiki" pattern as your core, not a notes app**: an append-only `raw/` source folder, an AI-maintained `wiki/` of concept/entity pages in Markdown inside Obsidian, and a schema file (`CLAUDE.md`/`SCHEMA.md`) that disciplines a Claude-powered agent — this delivers ~80% of the value with the least maintenance and fits your n8n/Claude/Python stack exactly.
- **The decisive principle from 60+ years of PKM research is "connect, don't collect"**: every failed system dies from the Collector's Fallacy (saving ≠ understanding). Your AI layer's job is to force the synthesis step automatically and to make retrieval drive structure — store atomic, concept-oriented, densely-linked *ideas* (Luhmann/Matuschak), not documents.
- **Stage the build in three versions**: V1 = ingest→summarize→atomic-note agents over Obsidian + SQLite metadata; V2 = pattern detection + a Neo4j knowledge graph (Source→Idea→Concept→Pattern→Insight→Decision→Outcome) + vector search; V3 = full multi-agent system (Contrarian, Opportunity, Investment Research) orchestrated in n8n. Judge it on output (insights, decisions, theses written), never on note count.

---

## Key Findings

1. **The literature converges on one idea**: knowledge work compounds only when you externalize *ideas* (atomic, in your own words, linked by concept) and continually re-process them. Luhmann's Zettelkasten, Ahrens, Matuschak's evergreen notes, Novak's concept maps, and Locke's commonplace books independently arrive here. Forte's *Building a Second Brain* adds the actionability/output lens (CODE + PARA).
2. **AI changes the economics of the expensive step**: historically the bottleneck was the human labor of distilling, linking, and resurfacing. LLMs now do extraction, summarization, cross-linking, contradiction detection, and pattern surfacing cheaply. The Karpathy LLM Wiki pattern (April 2026, 16M+ views) and Microsoft GraphRAG are the two most important applied templates.
3. **The dominant failure mode is human, not technical**: the Collector's Fallacy, tool-hopping, productivity theater (endless system-tweaking), and "note graveyards." The system must be designed against these — automate processing, track output, prune ruthlessly.
4. **Hybrid retrieval beats either extreme**: at personal scale the LLM-wiki/long-context approach works without a vector DB; beyond ~100 articles/400k words you want hybrid search (BM25 + vector + graph traversal / GraphRAG).
5. **Your profile (manufacturer + investor + automation builder) maps unusually well onto a graph+agent architecture**: companies, industries, mental models, decisions, and outcomes are natural graph entities, and your decision/investment use cases reward the contradiction-detection and pattern layers that generic note-takers ignore.

---

## Details

### PART 1 — Literature Review

**Building a Second Brain (Tiago Forte, 2022).** *Core thesis*: the brain is for having ideas, not storing them; externalize knowledge so it's findable and usable for output. *Key ideas*: CODE (Capture, Organize, Distill, Express); PARA (Projects, Areas, Resources, Archives) organizes by **actionability**, not topic; Progressive Summarization; Intermediate Packets. *Strengths*: output-oriented, tool-agnostic, low theory barrier; proven at scale (WSJ bestseller, used inside Genentech, Toyota, the Inter-American Development Bank). *Weaknesses*: light on idea-linking and genuine synthesis; progressive summarization can become highlighting theater; organizing by project weakens long-term accretion. *Borrow*: actionability lens, CODE loop, capture-only-what-resonates. *Avoid*: over-investing in PARA folder hierarchies; treating capture as the goal.

**Zettelkasten (Niklas Luhmann; systematized by Sönke Ahrens, *How to Take Smart Notes*, 2017).** *Core thesis*: writing is the medium of thinking; a slip-box of atomic, linked notes becomes a "communication partner" that generates ideas. Luhmann built a Zettelkasten of ~90,000 index cards from 1952–53 onward and credited it for his prolific output — counts vary by source (Wikipedia: ~50 books and 550 articles; zettelkasten.de: 50 books, 600+ articles, plus 150+ unfinished manuscripts in his estate). *Key ideas*: three note types — fleeting, literature, permanent (Zettel); atomicity (one idea per note); links over hierarchy; write in your own words; let writing emerge by assembling notes. *Strengths*: unmatched for insight accumulation and emergent connection; the most rigorously validated method. *Weaknesses*: high discipline cost; slow; ambiguous terminology in Ahrens; "where does this note go?" friction. *Borrow*: atomicity, concept-linking, "connect not collect," writing-as-thinking. *Avoid*: dogmatic Folgezettel numbering; manual-only linking (AI can now assist).

**Evergreen Notes (Andy Matuschak).** *Core thesis*: "Better note-taking misses the point; what matters is better thinking." Notes should be **atomic, concept-oriented, densely linked**, and written to **evolve and accrete across projects**. *Key ideas*: concept-orientation over source-orientation; "note titles are like APIs"; associative ontologies over hierarchical taxonomies; reading inbox + writing inbox; number of evergreen notes/day as a leading indicator. *Strengths*: the clearest articulation of how knowledge compounds. *Weaknesses*: very high effort; weak feedback loop (Matuschak's own caveat: note-writing provides weak feedback and few people have a serious context of use). *Borrow*: concept-orientation, dense linking, accretion. *Avoid*: perfectionism; writing notes with no downstream use.

**MyLifeBits (Gordon Bell & Jim Gemmell, with Roger Lueder; Microsoft Research, 1998–2007).** *Core thesis*: capture everything ("Total Recall"); bio-memory becomes a URL/index into e-memory. *Key ideas*: lifelogging, full-text search, annotations, SQL-backed personal store. *Strengths*: visionary on capture + retrieval infrastructure; pioneered faceted personal databases. *Weaknesses*: capture-maximalism produced low usable value — Bell told *Computerworld* (Mike Elgan, "Lifelogging is dead (for now)," 2016) the project "wasn't something that was bringing a lot of value to my life," and noted the smartphone effectively ended the effort. *Borrow*: durable storage, metadata, the e-memory-as-index idea. *Avoid*: capturing everything; storage as an end in itself. (Notably, Bell — who died in 2024 — had a vision only now viable *because* of LLM synthesis.)

**Concept Maps (Joseph Novak, Cornell, 1972; grounded in Ausubel's assimilation theory).** *Core thesis*: meaningful learning = assimilating new concepts into existing cognitive structure. Ausubel's founding principle (*Educational Psychology: A Cognitive View*, 1968, p. vi): "If I had to reduce all of educational psychology to just one principle, I would say this: The most important single factor influencing learning is what the learner already knows. Ascertain this and teach him accordingly." *Key ideas*: node-link diagrams with **labeled** relationships (propositions); hierarchical concept structure; the Vee heuristic. *Strengths*: makes relationships explicit and labeled (exactly what a knowledge-graph edge needs); strong metacognitive value. *Weaknesses*: manual maps don't scale; can become cluttered. *Borrow*: labeled, typed relationships; explicit propositions as the unit of a graph edge. *Avoid*: hand-drawn maps as the primary store.

**Commonplace Books (John Locke, *A New Method of Making Common-Place-Books*, 1685/1706).** *Core thesis*: curate "choice and excellent" excerpts, indexed for retrieval and recombination. *Key ideas*: a formal index (Locke's head/vowel scheme) enabling later retrieval and "tangled" recombination across topics. Historian Robert Darnton ("Extraordinary Commonplaces," *New York Review of Books* 47(20), Dec 21, 2000, pp. 82, 86) describes the practice: "They broke texts into fragments and assembled them into new patterns by transcribing them in different sections of their notebooks. Then they reread the copies and rearranged the patterns while adding more excerpts." *Strengths*: ~400 years of evidence that curation + indexing + recombination works; aggressive filtering ("not what comes next"). *Weaknesses*: linear medium; manual indexing. *Borrow*: curation discipline, indexing for retrieval, recombination as the value source. *Avoid*: rigid alphabetical indexing (vector + graph search supersedes it).

**Sensemaking (Karl Weick; also Klein, Dervin, Snowden, Russell).** *Core thesis*: people enact and *retrospectively* construct meaning from ambiguous cues; sensemaking ≠ rational decision analysis. Weick's "cosmology episode" (Mann Gulch) shows what happens when frames collapse. *Borrow*: design the system to support **framing and reframing**, not just storage; surface cues that challenge current frames (this motivates the Contrarian agent). Klein's work on mental models and pattern recognition motivates the pattern-detection layer.

**Knowledge Synthesis / Systematic Review Methods (PRISMA 2020).** *Core thesis*: transparent, reproducible synthesis via a 27-item checklist and a 4-stage flow — **Identification → Screening → Eligibility → Inclusion** — then structured extraction and synthesis. *Borrow*: explicit inclusion/exclusion criteria for what enters the permanent store; documented provenance; dual-coding/structured extraction templates; synthesis over collection. *Avoid*: full academic heaviness for personal use — adopt the *spirit* (provenance, structured extraction).

**Information Retrieval / Vector & Semantic Search / RAG.** *Core ideas*: embeddings place text in semantic space; retrieval finds nearest neighbors; chunk size is a key hyperparameter (too big = generic, too small = incoherent); hybrid search (keyword BM25 + vector + re-ranking) outperforms either alone; GraphRAG adds multi-hop reasoning over a knowledge graph and reduces hallucination via explicit relationships and an audit trail. *Borrow*: hybrid retrieval, chunking discipline, GraphRAG for multi-hop/cross-document questions. *Avoid*: assuming pure vector RAG suffices for relational "what connects X and Y" queries.

**Cognitive Science of Learning.** The most rigorous synthesis (Dunlosky, Rawson, Marsh, Nathan & Willingham, "Improving Students' Learning With Effective Learning Techniques," *Psychological Science in the Public Interest* 14(1):4–58, 2013) reviewed 10 techniques and rated only two — **practice testing (retrieval) and distributed practice (spacing)** — as "high utility"; elaborative interrogation, interleaving, and self-explanation rated *moderate*; highlighting and rereading rated *low*. The practitioner-friendly "six strategies" framing (spaced practice, retrieval practice, interleaving, elaborative interrogation, concrete examples, dual coding) comes from the Learning Scientists (Weinstein/Sumeracki) and blends Dunlosky with later work. Spacing is among the most robust findings in the field: Cepeda, Pashler, Vul, Wixted & Rohrer (*Psychological Bulletin* 132(3):354–380, 2006) reported 839 assessments of distributed practice across 317 experiments in 184 articles. *Borrow*: optional spaced-repetition prompts from notes (Matuschak's "expert response heuristic"); elaborative interrogation ("why is this true? what would falsify it?") as an AI distillation prompt; dual coding (pair text with diagrams). *Avoid*: confusing storage with learning — the system should occasionally *test* you.

**Learning in Public.** *Core thesis* (and the practical cure for the Collector's Fallacy cited by multiple practitioners): producing public output (essays, theses, newsletters) forces synthesis and exposes gaps. *Borrow*: make "Express" a first-class output of the system (the Writing agent).

**Research Workflows / Citation Managers (Zotero, Mendeley).** *Core role*: in a Zettelkasten, the reference manager is a distinct component from the slip-box (Ahrens's architecture: slip-box + reference manager + editor). *Borrow*: keep bibliographic/source metadata structured and separate from your thinking; Zotero's open data model and BetterBibTeX export integrate cleanly with a Markdown/Obsidian flow. *Avoid*: conflating source notes with permanent/idea notes.

**Human-AI Collaborative Knowledge Systems (2022–2025).** Recent HCI/IS research (e.g., the "Sensemaking AI" research agenda in *EPJ Data Science*; collaborative human-AI sensemaking for intelligence analysis; AI-augmented KJ-Ho/affinity-diagramming studies) converges on a **hybrid division of labor**: AI handles schematization, clustering, hypothesis-generation, and visualization; humans retain **integrative sensemaking, framing, and value judgments.** A repeatedly flagged risk is **de-skilling / erosion of critical thinking** (Sellen & Horvitz) when AI over-automates the thinking. *Borrow*: keep the human in the framing/judgment loop; use AI as scaffolding (Vygotsky) and embrace "creative tension" (Senge) — let the AI surface disagreement. *Avoid*: full automation of synthesis (both a quality and a de-skilling risk).

### PART 2 — Comparative Analysis

Scores are 1–10; for **Cognitive Load, higher = lower load** (10 = very low load). These are reasoned synthesis judgments calibrated to a sophisticated solo user building an AI layer, not measured benchmarks.

| System | Capture | Retrieval | Insight Gen | Scalability | Cog. Load (10=low) | AI Compat. | Long-term Use |
|---|---|---|---|---|---|---|---|
| Zettelkasten | 5 | 7 | 9 | 8 | 3 | 7 | 9 |
| PARA | 8 | 6 | 4 | 7 | 7 | 6 | 6 |
| Evergreen Notes | 4 | 7 | 9 | 8 | 3 | 8 | 9 |
| Commonplace Book | 7 | 4 | 5 | 4 | 6 | 5 | 6 |
| Concept Maps | 3 | 5 | 8 | 3 | 4 | 6 | 5 |
| Knowledge Graphs | 4 | 8 | 9 | 9 | 3 | 9 | 9 |
| Research DBs (Zotero/Mendeley) | 8 | 7 | 3 | 8 | 6 | 7 | 8 |
| Obsidian linked notes | 7 | 7 | 7 | 8 | 6 | 9 | 9 |
| AI-native (Mem/Notion AI/Roam) | 9 | 8 | 6 | 7 | 8 | 8 | 5 |

**Qualitative analysis.** *Zettelkasten/Evergreen* score highest on insight generation but worst on cognitive load — precisely the load AI can now absorb. *PARA* is easiest to adopt and best for action, but weak on insight/accretion. *Knowledge Graphs* and *Obsidian linked notes* are the best long-term, AI-compatible substrates; Obsidian's local Markdown ("file over app") gives durability and zero lock-in, while a graph layer adds relational reasoning. *AI-native tools (Mem, Notion AI, Roam)* win on capture and zero-setup but score lowest on long-term usefulness due to lock-in, opaque AI organization, and weaker data ownership — independent 2026 testing found most note-app "AI" is shallow (summarize-one-note chatbots), with only a few (e.g., Reflect's cross-note synthesis) genuinely leveraging the note graph. *Research DBs* are excellent for source metadata but not for thinking. **Verdict: the winning architecture is Obsidian (durable Markdown substrate) + a knowledge graph (relational reasoning) + AI agents (absorbing the cognitive load Zettelkasten/Evergreen demand) — not any single off-the-shelf tool.**

### PART 3 — Design Principles (first-principles rules)

1. **Connect, don't collect.** Saving ≠ understanding (Collector's Fallacy, Christian Tietze). *Op*: nothing enters permanent `wiki/` without being paraphrased, summarized, and linked — the ingest agent enforces this.
2. **Store ideas, not documents.** *Op*: the atomic unit is a concept/claim note; raw clips live in append-only `raw/`.
3. **Atomicity.** One idea per note. *Op*: the Concept Extractor splits multi-idea sources.
4. **Concept-orientation over source-orientation.** *Op*: file by concept; sources link *to* concept pages (Matuschak).
5. **Separate source knowledge from personal thinking.** *Op*: three layers — `raw/` (immutable), `wiki/` (synthesized), and explicitly tagged "MyThinking" blocks.
6. **Every note will be re-encountered.** *Op*: replace "what topic?" with "in what future context do I want to stumble on this?" (Ahrens). Orphan notes get flagged.
7. **Retrieval drives structure.** *Op*: design notes/metadata around the queries you'll run (opportunity scans, thesis support, contradiction checks).
8. **Knowledge evolves (accretion).** *Op*: pages are living; the agent updates concept pages and flags where new sources contradict old claims (Karpathy pattern).
9. **Dense, typed, labeled links.** *Op*: edges carry a relationship type and description (Novak propositions; GraphRAG relationship_description + strength).
10. **Provenance is mandatory.** *Op*: every claim traces to a `raw/` source span (PRISMA discipline; GraphRAG TextUnit breadcrumbs).
11. **Confidence is explicit.** *Op*: claims/edges carry a confidence score; low-confidence items surfaced for review.
12. **Capture only what resonates; filter aggressively.** *Op*: Locke's "choice and excellent," Forte's resonance test — capture is a curation step.
13. **Track output, not input.** *Op*: dashboard counts insights, theses, decisions — not notes.
14. **Prune ruthlessly; trust recurrence.** *Op*: scheduled pruning; important ideas recur and are re-captured.
15. **Minimize infrastructure tinkering (anti-productivity-theater).** *Op*: freeze the toolset ≥6 months; budget a fixed "complexity allowance."
16. **Human keeps framing/judgment; AI does schematization.** *Op*: AI proposes; you decide what's an insight, opportunity, thesis.
17. **Write in your own words.** *Op*: the summarizer paraphrases; quotes kept separately with provenance.
18. **Plain text, local-first, open formats.** *Op*: Markdown + SQLite/Neo4j files you own (file-over-app).
19. **Spaced resurfacing.** *Op*: optional spaced-repetition prompts + a "resurface old relevant notes" job.
20. **Make contradiction a feature.** *Op*: a dedicated agent looks for cross-source disagreement (creative tension; Weick's reframing).
21. **Idempotent, append-only ingestion.** *Op*: `raw/` is never edited; re-running ingest doesn't corrupt the graph (entity merge by name+type).
22. **Schema as code.** *Op*: one `SCHEMA.md`/`CLAUDE.md` governs page structure, entity types, and ingestion rules (Karpathy layer 3).
23. **Design for multi-hop questions.** *Op*: graph + GraphRAG so "what connects supplier risk in X to my thesis on Y?" is answerable.
24. **Decisions are first-class objects.** *Op*: decision logs with predictions + confidence enable calibration review (Farnam Street).
25. **Close the loop: Decision → Outcome.** *Op*: outcomes link back to the decisions and insights that drove them, so the graph learns what worked.

### PART 4 — Ideal End-to-End Workflow

For each stage: **Inputs → Outputs | Human role | AI role | Data structure | Metadata.**

1. **Reading Source.** In: article/book/paper/newsletter/podcast/meeting. Out: a capture decision. Human: chooses, reads, reacts. AI: none (or recommends based on graph gaps). Structure: external.
2. **Capture.** In: source + highlight/voice note. Out: a `raw/` Markdown file (full text/transcript) + front matter. Human: clip what resonates. AI: clean to Markdown, pull YouTube/podcast transcripts, OCR. Structure: `raw/*.md`. Metadata: `source_title, url, author, date_saved, type, tags, hash`.
3. **Summarization.** In: `raw/` file. Out: structured summary (thesis, key claims, evidence, caveats). Human: spot-check. AI (Summarizer): paraphrase, elaborative-interrogation pass. Structure: summary block. Metadata: `summary_confidence, model, date`.
4. **Idea Extraction.** In: summary. Out: candidate atomic claims (subject-predicate-object where possible). Human: approve/merge. AI (Concept Extractor): split into atomic claims. Metadata: `claim_type, status, source_span`.
5. **Concept Identification.** In: claims. Out: concept pages created/updated in `wiki/`. Human: rename/merge. AI: match to existing concepts (exact+semantic), create new. Structure: `wiki/concepts/*.md`. Metadata: `concept_id, aliases, definition, links`.
6. **Mental-Model Detection.** In: claims+concepts. Out: tags linking content to mental models. Human: confirm. AI: classify against your model library. Structure: `wiki/models/*.md` + edges.
7. **Pattern Matching.** In: graph state. Out: recurring themes/entities/analogies. Human: judge relevance. AI (Pattern agent): frequency + embedding clustering + analogy prompts. Metadata: `pattern_type, support_count, confidence`.
8. **Cross-Linking.** In: new + existing notes. Out: typed edges. Human: prune false links (avoid apophenia — syntactic ≠ semantic). AI: propose typed, labeled relationships with strength. Metadata: `edge_type, description, strength, confidence`.
9. **Knowledge Graph Update.** In: entities/edges/claims. Out: updated Neo4j + vector index. Human: periodic audit. AI (KG agent): upsert with entity resolution + provenance. Structure: Neo4j + Chroma. Metadata: `created_by, updated_at, provenance`.
10. **Insight Generation.** In: graph + community summaries. Out: candidate insights. Human: accept → Insight note. AI: synthesize across communities (GraphRAG global query). Structure: `wiki/insights/*.md`. Metadata: `insight_id, supporting_nodes, confidence, novelty`.
11. **Decision Support.** In: a question/decision. Out: for/against evidence brief. Human: decide, log. AI (Retrieval + Contrarian): assemble context, surface counter-evidence. Structure: decision log. Metadata: `decision_id, options, confidence, review_date`.
12. **Opportunity Discovery.** In: patterns + insights + your context (manufacturing/portfolio). Out: business/investment candidates. Human: filter, pursue. AI (Opportunity + Investment agents): cross-reference trends with capabilities/holdings. Structure: `wiki/opportunities/*.md`. Metadata: `opportunity_id, thesis_link, time_sensitivity, confidence`.

### PART 5 — Knowledge Model / Ontology

A **labeled property graph** (Neo4j): nodes carry typed labels + properties; relationships are directed, typed, and carry properties (description, strength, confidence, provenance). An OWL/Protégé layer is optional for formal inference but unnecessary for V1–V2.

- **Source** — `id, title, type{Article|Book|Paper|Newsletter|Podcast|Meeting}, author(s), publisher, date, url, hash, raw_path, credibility`. Rel: `WRITTEN_BY→Author`, `ABOUT→Concept/Company`, `MENTIONS→Entity`, `SUPPORTS/CONTRADICTS→Claim`. *Ex*: "Stratechery, 'AI Integration,' 2026-01."
- **Author** — `id, name, affiliation, domains, reliability`. Rel: `AFFILIATED_WITH→Company`, `EXPERT_IN→Industry/Concept`. *Ex*: Ben Thompson.
- **Company** — `id, name, ticker, industry, role{supplier|competitor|target|holding}, stage`. Rel: `OPERATES_IN→Industry`, `COMPETES_WITH→Company`, `SUPPLIES→Company`, `SUBJECT_OF→Thesis`. *Ex*: TSMC.
- **Industry** — `id, name, value_chain_position, growth, cyclicality`. Rel: `CONTAINS→Company`, `DRIVEN_BY→Pattern/Event`. *Ex*: Advanced packaging.
- **Concept** — `id, name, aliases, definition, domain`. Rel: `RELATED_TO→Concept`, `INSTANCE_OF→Framework`, `APPEARS_IN→Source`. *Ex*: Operating leverage.
- **Framework** — `id, name, steps, domain, source`. Rel: `COMPOSED_OF→Concept`, `APPLIES_TO→Industry/Decision`. *Ex*: Porter's Five Forces.
- **Mental Model** — `id, name, discipline, description`. Rel: `EXPLAINS→Pattern/Event`, `USED_IN→Decision`. *Ex*: Second-order effects.
- **Pattern** — `id, name, type{theme|trend|analogy|recurrence}, support_count, first_seen, confidence`. Rel: `OBSERVED_IN→Source(s)`, `SUGGESTS→Opportunity`, `CONTRADICTS→Pattern`. *Ex*: "Reshoring of precision manufacturing."
- **Event** — `id, name, date, type, magnitude`. Rel: `AFFECTS→Company/Industry`, `EVIDENCE_FOR→Pattern`. *Ex*: "Export controls, Oct 2025."
- **Decision** — `id, statement, options, chosen, confidence, state_of_mind, date, review_date`. Rel: `INFORMED_BY→Insight/Source`, `RESULTED_IN→Outcome`. *Ex*: "Add second CNC line."
- **Insight** — `id, statement, supporting_nodes, confidence, novelty, date`. Rel: `DERIVED_FROM→Pattern/Concept`, `SUPPORTS→Thesis/Decision`. *Ex*: "Lead-time compression is becoming a moat."
- **Hypothesis** — `id, statement, status{open|supported|refuted}, confidence`. Rel: `TESTED_BY→Source/Event`, `BECOMES→Insight`. *Ex*: "Copper tariffs raise our COGS >8%."
- **Opportunity** — `id, description, type{business|investment}, time_sensitivity, confidence`. Rel: `BASED_ON→Pattern/Insight`, `TARGETS→Company/Industry`. *Ex*: "Acquire distressed supplier."
- **Project** — `id, name, status, goal, deadline`. Rel: `USES→Insight/Resource`, `PRODUCES→Decision/Output`. *Ex*: "ERP migration Q3."
- **Outcome** — `id, description, date, delta_vs_expected`. Rel: `RESULT_OF→Decision`, `VALIDATES/REFUTES→Insight/Hypothesis`.

### PART 6 — Output Templates (Markdown, AI-retrieval-optimized)

All templates open with YAML front matter for machine parsing. Common front matter: `id, type, title, created, updated, source_path, tags, entities, confidence`.

**1. Article Note**
```
---
type: article
title:
author:
url:
date_published:
date_saved:
tags: []
entities: {companies: [], people: [], concepts: []}
---
## TL;DR (3 bullets)
## Key Claims (atomic, with source span)
## Evidence & Data
## My Thinking / Reactions
## Contradicts / Confirms (links)
## Extracted Concepts → [[concept]]
## Open Questions
```
**2. Book Note**: adds `## Thesis`, `## Chapter Distillations`, `## Mental Models present`, `## Most useful idea`, `## Disagreements`.
**3. Research Paper Note**: adds `## Question/Hypothesis`, `## Method`, `## Findings`, `## Effect sizes/limits`, `## Replication/credibility`, `## Citations to chase`.
**4. Newsletter Issue Note**: adds `## Issue/Date`, `## Signal vs noise`, `## Companies/tickers mentioned`, `## Trend updates`.
**5. Podcast Note**: adds `## Guest & credibility`, `## Timestamped key points`, `## Quotes (verbatim + time)`, `## Follow-ups`.
**6. Meeting Note**: adds `## Attendees`, `## Decisions made → [[decision]]`, `## Action items (owner/date)`, `## Commitments`, `## Risks raised`.
**7. Mental Model Note**: `## Definition`, `## Discipline`, `## When it applies`, `## Examples in my domain`, `## Failure cases`, `## Linked decisions`.
**8. Concept Note (evergreen)**: `## One-sentence definition (API-like title)`, `## Explanation`, `## Related concepts`, `## Instances/evidence`, `## Provenance`.
**9. Insight Note**: `## Statement`, `## Supporting evidence (nodes)`, `## Confidence & novelty`, `## So what / implication`, `## Decisions/opportunities it informs`.
**10. Business Opportunity Note**: `## Opportunity`, `## Underlying pattern/insight`, `## Why now (time sensitivity)`, `## Fit with my capabilities`, `## Risks/unknowns`, `## Next action`.
**11. Investment Thesis Note**: `## Thesis (one line)`, `## Company/asset`, `## Variant perception (why the market is wrong)`, `## Key drivers & KPIs`, `## Valuation`, `## Risks & disconfirming evidence`, `## Catalysts`, `## Position & review trigger`.
**12. Decision Log (Farnam Street style)**: `## Decision & date`, `## Situation/context`, `## Options considered`, `## Chosen + rationale`, `## Confidence (%)`, `## Expected outcome`, `## Mental/physical state`, `## Review date`, `## Outcome (filled later)`, `## Lessons`.

### PART 7 — Pattern Discovery Layer

For each discovery type: detection method + AI prompt/architecture.

- **Repeated themes**: embedding-cluster all atomic claims (Chroma); for each cluster, prompt the LLM to name the theme and count supporting sources → Pattern nodes with `support_count`. Scheduled batch job.
- **Emerging trends**: time-windowed frequency of concepts/entities; compute slope over rolling windows; LLM labels rising clusters. Prompt: "Given these concept-mention counts by month, identify which are accelerating and summarize the trend with supporting sources."
- **Contradictions between sources** (highest-value, hardest layer): use a **hybrid pipeline** — (1) semantic-similarity filtering to select candidate claim pairs (cuts the O(N²) pair space); (2) a **Natural Language Inference (NLI)** classifier (RoBERTa/BART-large fine-tuned on MNLI, or PubMedBERT for technical text) labeling pairs entailment/neutral/**contradiction**; (3) an **LLM judge** confirming and explaining, with confidence-weighted scoring and human review of low-confidence cases. Model six contradiction types (negation, numerical, temporal, authority, scope, causal), per recent multi-agent contradiction-mining work (e.g., the ContraGen framework). **Honor this caveat in the build**: ContraDoc (Li et al. 2023) and the RAG context-validator study (arXiv:2504.00180) find even GPT-4 is unreliable on subtle/cross-document contradictions — treat output as review candidates, not ground truth.
- **Missing knowledge gaps**: query the graph for concepts with few inbound links, theses lacking disconfirming evidence, or industries with stale sources. Prompt: "Given my thesis on X and its evidence nodes, what evidence is missing or one-sided?"
- **Cross-domain analogies**: embed concepts; find high-similarity pairs whose `domain` attributes differ; prompt: "These two concepts from different domains are structurally similar — describe the analogy and whether it yields a transferable insight." Guard against apophenia — require structural, not lexical, similarity.
- **Repeatedly used mental models**: count `USED_IN`/`EXPLAINS` edges from Mental Model nodes; surface most- and least-used models (Munger latticework gap analysis).
- **Frequent entities (companies/people/concepts)**: graph degree centrality; dashboard of top entities by period, with alerting when a previously rare entity spikes.

**Overall architecture pattern** (Microsoft GraphRAG): extract entities/relationships/claims per text chunk ("TextUnit," default 1200 tokens) using a delimited-tuple extraction prompt with multi-round "gleanings" (self-reflection re-prompts to boost recall), detect **communities via the hierarchical Leiden algorithm** (Traag, Waltman & van Eck 2019), generate **community summaries bottom-up**, and run **map-reduce global queries** for synthesis-level questions. Claim ("covariate") extraction is a separate, prompt-tuned step (disabled by default in GraphRAG) that captures subject/object/type/status/description/source-span/dates.

### PART 8 — Knowledge Graph Design

**Pipeline: Source → Idea → Concept → Pattern → Insight → Decision → Outcome.**

- **Node types**: as in Part 5. Common attributes: `id, label, name, created_at, updated_at, confidence, provenance[]`.
- **Edge types & semantics**: `WRITTEN_BY, ABOUT, MENTIONS, SUPPORTS, CONTRADICTS, RELATED_TO, INSTANCE_OF, EXPLAINS, OBSERVED_IN, DERIVED_FROM, INFORMED_BY, RESULTED_IN, TARGETS, COMPETES_WITH, SUPPLIES`. Every edge is **directed** with `type, description, strength(1–10), confidence(0–1), source_span`.
- **Relationship-strength scoring**: adopt GraphRAG's integer 1–10 relationship-strength from the extraction prompt; reinforce when a relationship recurs across sources.
- **Confidence scores**: per claim/edge (0–1), seeded by the extractor, raised by recurrence and human confirmation. Use a **noisy-OR update** so repeated independent evidence raises confidence: `s = 1 − (1 − s)·(1 − s′)` (pattern from MedKGent, arXiv:2508.12393). Low-confidence items are flagged.
- **Time dimension**: store `created_at/updated_at` on nodes and edges; keep claims with `valid_from/valid_to`; never edit `raw/` (append-only) so history is reconstructable; when a new source contradicts an old claim, *flag rather than overwrite* (knowledge evolves). For conflicting relationship types, resolve with an LLM at low temperature considering confidence + recency.
- **Provenance**: persist triples as nodes/edges linked to originating document IDs and, when available, page/sentence spans (pattern from SSKG Hub, arXiv:2603.00669). Consider **reified triples** (turning a triple into a node) when you need rich per-claim metadata (confidence, source, time).
- **Visualization**: Obsidian's native graph view for casual browsing; Neo4j Bloom / Cypher for relational queries; a dashboard (simple web view or Obsidian Bases/Dataview) for top entities, trend slopes, and the contradiction queue. Keep `index.md` (catalog) and `log.md` (append-only timeline) as human-navigable steering files.

### PART 9 — AI Agent Architecture

Orchestration: a **coordinator/hierarchical pattern** — centralized control reduces error amplification (research finds independent agents amplify errors ~17× vs ~4× for centralized). Each agent = role + tools + memory. Recommended prompt skeleton for all: *role → task → input schema → output schema (strict JSON/Markdown) → constraints → few-shot example.* Use structured output / function-calling to enforce schema.

1. **Reader Agent** — *Resp*: normalize raw content (HTML/PDF/transcript) to clean Markdown + front matter. *I/O*: raw bytes/URL → `raw/*.md`. *Prompt*: extraction + cleanup, no interpretation. *Memory*: stateless; dedupe via hash.
2. **Summarizer Agent** — *Resp*: thesis + atomic key claims + caveats, in own words, with source spans; elaborative-interrogation pass. *I/O*: raw note → summary block. *Memory*: short (current doc).
3. **Concept Extractor** — *Resp*: split into atomic concepts/claims; match to existing concept pages (exact + semantic). *I/O*: summary → concept/claim list (subject-predicate-object). *Memory*: reads concept index.
4. **Knowledge Graph Agent** — *Resp*: upsert entities/edges/claims with entity resolution (merge by name+type/label) and provenance; attach strength/confidence. *I/O*: claims → Neo4j + Chroma. *Prompt*: GraphRAG-style delimited tuples `("entity"|"relationship"|...)` or Neo4j JSON `{nodes:[...], relationships:[...]}` (the neo4j-graphrag `ERExtractionTemplate`). *Memory*: graph schema + entity index.
5. **Pattern Detection Agent** — *Resp*: themes, trends, recurrences, analogies (Part 7). *I/O*: graph/embeddings → Pattern nodes. *Memory*: long (historical counts).
6. **Contrarian Agent** — *Resp*: surface contradictions and steelmanned counter-views (NLI + LLM-judge hybrid). *I/O*: claim/thesis → contradiction list with confidence. *Memory*: reads related claims; flags for human.
7. **Opportunity Agent** — *Resp*: map patterns/insights to your manufacturing capabilities; generate business opportunities. *I/O*: patterns + profile → Opportunity notes. *Memory*: your context profile + graph.
8. **Investment Research Agent** — *Resp*: build/maintain theses, KPIs, variant perception, risks; cross-link companies/industries/events. *I/O*: company/industry query → thesis note + evidence. *Memory*: portfolio context + market events.
9. **Retrieval Agent** — *Resp*: hybrid retrieval (BM25 + vector + graph traversal / GraphRAG local+global) and context assembly with citations. *I/O*: question → ranked context. *Memory*: indices.
10. **Writing Agent** — *Resp*: draft outputs (memos, theses, newsletter sections) from the knowledge base with citations to `wiki/`/`raw/`. *I/O*: brief + retrieved context → draft. *Memory*: style guide + retrieved notes.

Memory tiers: **working** (current task context window), **episodic** (`log.md`, decision logs), **semantic** (graph + concept pages), **vector** (embeddings).

### PART 10 — Implementation Recommendation (Claude API, Obsidian, Markdown, SQLite, optional Neo4j, optional Chroma/Weaviate, Python, n8n)

**MVP / "80% value" architecture (build first).** The Karpathy LLM Wiki, instantiated for you:
- **One Obsidian vault, three layers**: `raw/` (append-only, fed by Obsidian Web Clipper + transcript pulls), `wiki/` (AI-maintained concept/source/entity pages), plus `SCHEMA.md` (your ontology + page rules), `index.md` (catalog), `log.md` (append-only timeline).
- **Agent**: Claude (via API, or Claude Code/CLI operating on local files) running ingest → summarize → concept-extract → cross-link → update-wiki, governed by `SCHEMA.md`.
- **Metadata**: a SQLite source registry (id, hash, type, dates, paths, tags) — lightweight, queryable, no server.
- **Orchestration**: an n8n flow on a schedule/new-file trigger: detect new `raw/` files → call Claude with the ingest prompt → write/update `wiki/` pages → append `log.md`.
- **Retrieval**: at MVP scale (<~100–150 sources) rely on long-context Claude over selected wiki pages — **no vector DB yet**.
- *Complexity*: low. With your existing n8n + Claude + Python, this is days, not months. *Why it's 80%*: it automates the processing step (kills the Collector's Fallacy), produces synthesized, linked, durable Markdown you own, and answers real questions immediately. (Tobi Lütke's QMD — hybrid BM25/vector search over Markdown with LLM re-ranking, available as CLI and MCP server — is a good search layer once the vault grows.)

**Version 1 — Core system with basic agents.** Add Reader, Summarizer, Concept Extractor, Retrieval, Writing agents as discrete Python functions/prompts invoked by n8n. Introduce the 12 templates. Add a nightly "lint" pass (broken links, orphan notes, missing provenance). Add embeddings + **ChromaDB** when the corpus outgrows long-context. *Tech*: Python, Claude API, Chroma (local/embedded), SQLite. *Flow*: clip → raw → summarize → atomic notes → embed → wiki update → index. *Complexity*: moderate.

**Version 2 — Pattern detection + knowledge graph.** Stand up **Neo4j**; the KG Agent upserts entities/edges/claims with provenance, strength, confidence (GraphRAG-style extraction; entity resolution by name+type). Implement **GraphRAG** indexing: Leiden communities + bottom-up community summaries + map-reduce global queries. Add Pattern Detection and Contrarian agents (HuggingFace NLI model + Claude judge). Build a contradiction queue and trends dashboard. *Tech*: Neo4j, `neo4j-graphrag-python` or Microsoft GraphRAG lib, an NLI model, Chroma. *Complexity*: substantial — this is where relational/multi-hop and "what's changing" questions become answerable.

**Version 3 — Full multi-agent + opportunity generation.** Add Opportunity and Investment Research agents fed by your manufacturing context profile and (optionally) market data feeds. Coordinator orchestration in n8n (hierarchical planner invoking specialists; one-way handoffs for reliability). Add spaced-resurfacing jobs, decision→outcome loop closure, and a Writing agent drafting theses/memos/newsletter sections with citations. Optional: swap Chroma→Weaviate for scale/hybrid server features; optional OWL/Protégé layer for formal inference. *Complexity*: high, but incremental on V2.

### PART 11 — Final Recommendation

**1. Simplest system delivering 80% (the pragmatic path).** The MVP above: Obsidian vault (`raw/` + `wiki/` + `SCHEMA.md`/`index.md`/`log.md`), one Claude-driven ingest/synthesis loop in n8n, SQLite source registry, long-context retrieval. Resist adding Neo4j/vector DB until you feel real pain (corpus >~150 sources, or relational questions you can't answer). This single move — automating the processing step — defeats the failure mode that kills most PKM systems.

**2. Most robust long-term architecture.** Obsidian Markdown substrate (durability, no lock-in) + Neo4j property graph (relational reasoning, provenance, confidence, time) + Chroma/Weaviate vectors (semantic retrieval) + GraphRAG (community summaries + global synthesis) + a coordinator-orchestrated multi-agent layer (Reader, Summarizer, Concept Extractor, KG, Pattern, Contrarian, Opportunity, Investment, Retrieval, Writing) in n8n — with human-in-the-loop on framing, insight acceptance, and decision logging.

**3. What I'd build from scratch in 2025–2026.** Exactly the staged path above, and I would **start with Karpathy's LLM Wiki pattern on day one** rather than any commercial AI note app — because plain Markdown + an agent + your own schema gives durability, transparency (every claim cites a `raw/` span), zero lock-in, and a clean upgrade path to the graph. Given your stack (n8n, Claude, Python, Odoo, manufacturing), I'd wire the Investment and Opportunity agents to your real context early, since that's where the differentiated ROI is versus a generic second brain.

**4. Common failure modes & how to avoid them.**
- *Collector's Fallacy* (saving ≠ understanding): enforce automated processing; nothing enters `wiki/` un-synthesized.
- *Tool-hopping*: freeze tools ≥6 months; judge by output.
- *Productivity theater / over-engineering* (the IKEA effect — overvaluing systems you built): cap infrastructure time; the MVP is deliberately minimal.
- *Note graveyard*: scheduled pruning + spaced resurfacing; trust recurrence.
- *Apophenia / false links* (auto-linking creates syntactic, not semantic, connections): require typed, evidence-backed edges; human prunes.
- *Over-automation / de-skilling*: keep humans on framing and judgment; AI proposes, you dispose.
- *Contradiction over-trust*: treat AI contradiction detection as candidates (GPT-4-class models remain unreliable here).

**5. Keeping it alive after 5+ years.** Plain-text, local-first, open formats guarantee the data survives any tool's death (file-over-app). Keep `raw/` append-only and immutable so history is always reconstructable. Make the system *earn its keep weekly* by producing outputs you use (decisions, theses, drafts) — utility, not discipline, sustains it. Re-run pruning and a "what's stale / what contradicts what I now believe" pass quarterly. Let the schema evolve but version it. Above all, measure success by **insights and decisions produced**, never by notes stored — the moment the system stops generating output you act on, simplify it rather than elaborate it.

---

## Recommendations (staged, with thresholds)

1. **This month**: Build the MVP LLM Wiki (Obsidian `raw/`+`wiki/`+`SCHEMA.md`, Claude ingest loop in n8n, SQLite registry). *Advance when*: you're querying it weekly and the corpus nears ~150 sources or you hit questions long-context can't answer.
2. **Next**: Add Chroma embeddings + the 12 templates + a nightly lint pass (V1). *Advance when*: you start asking relational/multi-hop or "what's changing" questions → go to V2.
3. **Then**: Stand up Neo4j + GraphRAG + Pattern + Contrarian agents (V2). *Advance when*: the graph reliably answers cross-source questions and you want active opportunity/thesis generation → go to V3.
4. **Finally**: Add Opportunity + Investment Research + Writing agents wired to your manufacturing/portfolio context, coordinator orchestration, decision→outcome loop (V3).
5. **Always**: dashboard tracks *outputs produced*, the contradiction queue, and orphan/stale notes. If output drops, simplify — don't elaborate.

## Caveats
- **App/market facts move fast**: specific tool capabilities and prices (Mem, Notion AI, Roam, Reflect) and several cited "2026" reviews are promotional or time-sensitive — verify current features before committing budget. Independent testing finds much note-app "AI" is shallow.
- **Contradiction detection is an open research problem**: treat the Contrarian agent's output as review candidates, not ground truth (ContraDoc; RAG context-validator studies show even GPT-4 is unreliable on subtle/cross-document cases).
- **Scores in Part 2 are reasoned judgments**, not measured benchmarks; calibrate to your own use.
- **GraphRAG/Neo4j add real operational cost**: don't adopt them before the MVP proves the habit; premature infrastructure is itself a documented failure mode.
- **The Karpathy long-context claim (~100 articles/400k words without RAG)** is his reported experience, not a universal limit; your mileage depends on model context window and question type.
- **Cognitive-science nuance**: of the techniques cited, only retrieval/practice testing and spacing are rated "high utility" by Dunlosky et al. (2013); elaborative interrogation and interleaving are moderate — useful, but don't over-engineer around the weaker ones.