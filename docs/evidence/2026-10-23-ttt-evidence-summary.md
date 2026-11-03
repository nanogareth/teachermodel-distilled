# Train-the-trainer evidence summary (SWE)

Status: reference, 2026-10-23. Source: deep research run of 23 Oct 2026 (chat), weighted
evidence base > operational practice > AI-era shifts. Ratings:
**strong** = meta-analyses of causal studies or replicated RCTs; **moderate** = single RCTs,
quasi-experiments, multi-site or large-sample reliability studies; **weak** = single classrooms,
self-report, experience reports, company claims. Rule: only **strong** findings change
`standards/` (decision 0002).

## Adopted

Adopted as strong on 2026-10-23. Re-graded against the definition above on 2026-11-03 (owner): two of the five are strong. The
observation, calibration and audit rules rest on the other three, so they do not yet meet the rule in decision 0002.

| Finding | Population | Grade | Used in |
| --- | --- | --- | --- |
| Coaching: +0.49 SD on practice, +0.18 SD on achievement, 60 causal studies; virtual comparable; smaller in large programmes ([Kraft, Blazar & Hogan 2018](https://scholar.harvard.edu/files/mkraft/files/kraft_blazar_hogan_2018_teacher_coaching.pdf)) | K-12, literacy-heavy | Strong: meta-analysis | W7, `coaching` rules |
| Single observer on single lesson: reliability ~.27–.45; a second observer beats a second lesson by the same observer; 15-minute observation ~60% of full reliability in <1/3 time ([Ho & Kane 2013](https://files.eric.ed.gov/fulltext/ED540957.pdf)) | K-12: videos of 67 teachers in one district | Moderate: reliability study | W4, W6, `clearance`, `audit`, `quality` rules |
| Observer certification on pre-scored video, audit a subset ([MET, Seeing it clearly](https://usprogram.gatesfoundation.org/-/media/dataimport/resources/pdf/2016/11/met-seeing-it-clearly-v2.pdf)) | K-12 | Not graded: a practice guide, not a study | W5, W6 |
| Expertise reversal: support that helps novices harms learners with more prior knowledge; asymmetric (Kalyuga, Ayres, Chandler & Sweller 2003; [2025 meta-analysis](https://www.sciencedirect.com/science/article/pii/S0959475225000660)) | Broad | Strong: meta-analysis | `prior-knowledge` domain, module `pre_check` |
| Peer instruction halved fail rates in four CS courses; learning occurs in discussion ([Porter, Bailey Lee & Simon 2013](https://neverworkintheory.org/2013/03/08/halving-fail-rates-using-peer-instruction.html)) | University CS | Moderate: non-randomised comparison | `conceptual-questioning` domain, module `misconceptions` |

## Deferred (below strong)

| Finding | Rating | Candidate change |
| --- | --- | --- |
| Experts omit ~70% of decisions ([Sullivan et al. 2014](https://pubmed.ncbi.nlm.nih.gov/24667500/)) | Moderate | Decision-extraction interview in W12 |
| Expert blind spot ([Nathan & Petrosino 2003](https://www.proquest.com/scholarly-journals/expert-blind-spot-among-preservice-teachers/docview/200440373/se-2)) | Moderate | SME + professional pairing by default |
| AI assistance cut quiz scores 67% → 50%, d = 0.74, n = 52 ([Anthropic 2026](https://www.anthropic.com/research/AI-assistance-coding-skills)) | Moderate | Verification-first modules on coding agents |
| Experienced devs 19% slower, believed 20% faster, n = 16 ([METR 2025](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)) | Moderate | Exclude self-reported speed-up from outcomes |
| Subgoal labels, Parsons problems | Moderate (novices) | Ordering tasks in module templates |
| Live coding: no learning gain shown ([Shah et al. 2023](https://dl.acm.org/doi/abs/10.1145/3568813.3600122)) | Weak | Rubric guidance |
| Microteaching (Hattie ~0.88) | Weak–moderate | Gated microteaching in W1 |
| Self-selected SMEs score higher ([Google re:Work](https://rework.withgoogle.com/intl/en/guides/employee-led-learning-principles-and-practice)) | Weak | Selection by self-nomination + interview |
| Carpentries demo gate; ~55% certification ([2021 report](https://carpentries.github.io/2021_IT_report/index.html)) | Weak | 5-minute demo gate |
| Split content currency from teaching certification | Untested design | Per-release content check |

## Gaps

No rigorous study found of professional software engineers becoming instructors, or of
train-the-trainer for AI tooling. Running this system with two-observer data would generate
evidence nobody else has; consider publishing (open decision).
