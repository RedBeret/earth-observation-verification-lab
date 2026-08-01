# Design Decisions

Short records of the choices that shaped this lab, why they were made, and what they
cost. Each one was a real fork in the road, not a formality.

## 1. Docker Compose, not Kubernetes

**Context.** The lab needs five services, PostGIS, object storage, and a message broker,
and it has to come up reliably on one laptop and in three different CI runners.

**Decision.** Docker Compose, with a project name derived from the checkout path.

**Why.** Kubernetes would add a control plane, manifests, and a cluster dependency
without changing anything the lab is trying to demonstrate. Compose starts in under a
minute and its identity model is simple enough to guard properly.

**Cost.** No scheduling, no rolling updates, no multi-node failure modes. Those are real
distributed systems concerns the lab does not cover, and that limitation is stated rather
than papered over.

## 2. A transactional outbox instead of dual writes

**Context.** Accepting a scene or an event means both a database write and a published
message. Doing them independently means they can disagree.

**Decision.** The API writes the record and an outbox row in one transaction. A separate
publisher moves the row onto the stream and marks it published.

**Why.** A crash between the two writes is the classic distributed systems bug, and it is
the kind of thing that only shows up under load or during an outage. The outbox makes the
database the single source of truth for what was accepted.

**Cost.** One extra table, a publisher loop, and at-least-once delivery. Consumers have
to be idempotent, which they are, keyed on content digest and idempotency key.

## 3. `ST_Covers` rather than `ST_Contains`

**Context.** An event sitting exactly on a scene boundary has to resolve one way or the
other, deterministically.

**Decision.** `ST_Covers`, which includes the boundary.

**Why.** `ST_Contains` excludes boundary points, so an event on the edge silently fails to
match. For a wildfire exercise, dropping a detection because it landed on the edge of the
imagery footprint is the wrong default. A dedicated boundary fixture pins the behavior so
the choice cannot be reversed by accident.

**Cost.** Two scenes that share an edge will both match the same point. That is acceptable
here and is visible in the correlation records.

## 4. Evidence is generated, never written by hand

**Context.** The output of this project is a claim: these requirements were verified.
A claim is only worth as much as the process that produced it.

**Decision.** One typed model is built from raw runner output, then rendered into JSON,
Markdown, CSV, and JUnit, then read back and reconciled. A manifest records a SHA-256
digest for every rendered file.

**Why.** The failure mode worth designing against is not a bug, it is a report that looks
green because someone edited it, or because a test never ran. Reconciliation fails on a
missing file, zero checks, disagreeing totals, a redaction failure, or a digest mismatch.

**Cost.** Evidence cannot be patched. If something is wrong, the run has to be repeated.
That is the intended trade.

## 5. A missing observation fails

**Context.** A requirement whose test did not execute is not a passing requirement, but it
is very easy to render it as one.

**Decision.** Any requirement whose automated test is absent from the raw output is
recorded as `not observed`, and the model forces `not observed` to fail.

**Why.** Silence should never read as success. This is enforced in the model itself rather
than in a renderer, so no output format can disagree with it.

**Cost.** Running one test level and then generating evidence produces a mostly failing
report. That is correct, and the operator guide says so.

**Refined by.** Decision 11, which separates a missing observation from an executed
failure at the moment of release. Nothing recorded in the evidence model changes.

## 6. Thresholds live in one versioned file

**Context.** Performance limits were about to exist twice: once inside the k6 script and
once in whatever checked its output.

**Decision.** `performance/thresholds.json` is the only place the numbers appear. The k6
script reads it at init, and the Python gate reads it again to re-check the summary.

**Why.** Two copies of a threshold drift, and the drift is invisible until a regression
slips through. Re-checking in Python also means a k6 exit code cannot be the only thing
standing between a slow build and a green pipeline.

**Cost.** The gate has to parse a k6 summary format that may change between versions, so
k6 is pinned.

## 7. Destructive commands verify identity before acting

**Context.** Teardown runs on a developer machine that has other containers on it.

**Decision.** Every destructive action checks the Compose project name and a project label
on each container before touching it, and the clean-room proof fingerprints unrelated
containers, tears down only the verified project, and then proves the neighbours are
unchanged.

**Why.** A tool that can remove the wrong container once will not be run again. The
project name is derived from the checkout path, so two clones cannot destroy each other.

**Cost.** More code in the lifecycle path, and the clean-room proof refuses to run if no
unrelated container exists to compare against.

## 8. Scanner exceptions are narrow, named, and tested

**Context.** A secret scanner that reports its own test fixtures gets disabled. A scanner
with a blanket suppression proves nothing.

**Decision.** Two exceptions, both documented in `SECURITY.md`. Files under `tests/` may
declare a synthetic-fixture pragma; the scanner's own source may exempt itself from the
term list. Both scopes are enforced in code and covered by tests that prove the exemption
is refused elsewhere. Bandit gets a short skip list with a written reason per entry rather
than a global suppression.

**Why.** The value of a security gate is entirely in whether people trust it enough to
leave it on. Narrow and auditable beats broad and ignored.

**Cost.** Adding a legitimate fixture takes an extra line and a moment of thought.

## 9. CI runners orchestrate and nothing else

**Context.** Three pipeline definitions is three opportunities for the pipeline to test
something different from what a developer runs locally.

**Decision.** Jenkins, GitHub Actions, and GitLab may only call `./scripts/bootstrap.sh`
and `./scripts/terra.sh`. Structural tests assert that all three run the same gates in the
same order, always run diagnostics and teardown, fail on an empty artifact set, and need
no secrets.

**Why.** A green pipeline and a green local run should mean the same thing. The moment a
pipeline grows its own logic, that stops being true and nobody notices until an incident.

**Cost.** Runner-specific features go unused. Anything worth doing has to be worth adding
to the CLI first.

## 10. Documentation is verified, not trusted

**Context.** Documentation rots faster than code, and stale setup instructions are the
first thing a new reader hits.

**Decision.** Tests assert that every command and repository path named in a tracked
document exists, that every relative link resolves, and that tracked text stays in plain
ASCII punctuation.

**Why.** A command in a README is a promise. Checking it costs almost nothing and catches
the rename that would otherwise waste someone's afternoon.

**Cost.** Documenting a path that does not exist yet requires a placeholder the checker
recognises.

## 11. Publication is blocked by defects, not by silence

**Context.** Decision 5 makes any requirement whose test did not run count as a failure.
The publish gate then refused to publish while any requirement failed. Together those two
rules meant the repository could never be published until someone had run the full Docker
suite on a live host, because thirty of forty requirements are only observable there. The
gate's own comment asked for something weaker than its behaviour: that the evidence
package exist and reconcile.

**Decision.** The publish gate blocks on any check that ran and failed, and on any
evidence package that fails to reconcile. It does not block on a requirement that was
never observed. It prints the observed count instead, and the README states the same
number.

**Why.** An executed failure is a defect and is information. A missing observation is an
absence of information. Treating them identically at the point of release is what made the
gate unusable, and an unusable gate gets bypassed, which is worse than a gate that states
its own limits. `--allow-unobserved` waives only the second category, and the split is
enforced in `classify_failures` and asserted by tests rather than left to the caller.

**Cost.** A reader has to take the observed count seriously rather than reading a green
gate as full verification. That count is on the front page of the README for exactly that
reason. Anyone wanting the stricter rule still has it: `./scripts/terra.sh evidence`
without the flag fails while anything is unobserved, and that is what every CI runner
executes.
