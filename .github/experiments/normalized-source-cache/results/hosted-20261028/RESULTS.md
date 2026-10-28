# Normalized source hash sharing: experimental results

28 October 2026. Experiments on the public `manasjoshi14/gradle` fork. No upstream issue or pull request has been created. No paid compute has been provisioned.

The proposed route shows a reproducible benefit in the tested synthetic fresh-checkout workload. Three generated-Java repetitions also show lower elapsed time, with measured-task cache-hit assertions and retained traces. This is an experiment, not a merge-readiness claim or a forecast for production backend builds.

## Proposed behavior and motivation

The `FileSystemLocationSnapshot` overload in `SplitResourceSnapshotterCacheService` delegates to the existing Gradle user-home normalized-hash cache for ordinary source files as well as immutable global files. It caches the mapping from raw file content hash and normalizer configuration hash to normalized content hash. Separate worktrees with identical file contents can therefore reuse that calculation.

The `RegularFileSnapshotContext` classpath-resource overload retains its existing global/local split. File snapshots, checkout paths, compiled outputs, cache keys, cache serialization and remote transport are unchanged. A remote task-output cache can supply compiled outputs, but it does not itself share this local normalized-hash index.

The original split, introduced by Stefan Oehme in 2018 (`908c6ab6c80b861f506c4f4dc91f0a523c27209e`, PR 5472), shared immutable dependency metadata while keeping ordinary mutable project metadata local. The ordinary-file overload followed in Gary Hale's 2021 separation of resource and file-system-location hashers (`dbb44838a83719c4ded07072b390f2e66262ad8d`). That use case remains valid. Frequent fresh checkouts motivate testing a different sharing and retention tradeoff for the content-keyed ordinary-file normalization cache.

## Source and environment

- Baseline: `e04ee63317eeb36ac5102b6a3aa7e6cd931850a2`.
- Synthetic campaign source: `ac1f5a9b4d31e0adaeb48e642743f2938ad07fe1`.
- First successful native source: `6d71cfde127381d9a907f2c2427654db65ab3621`.
- Cache-hit-verified native repeat source: `007fb3d547fc8547f8216ac15b7fc6547de83c52`.
- Temurin JDK `25.0.3+9`, standard public GitHub-hosted `ubuntu-24.04` VMs. Source builds finish before measurement.
- Each VM compares both variants. Variants use separate user homes. The synthetic suite uses separate task-output cache directories; the native suite clears its local task-output cache at the start of each version. Caches are populated through ordinary builds; binary metadata indexes are never copied between variants.
- Fork workflow, collection and analysis files support the experiment. The production change remains the single routing change and its updated class documentation.
- Hosted VMs are shared infrastructure. Their results avoid laptop contention but do not provide dedicated-machine isolation.

## Correctness evidence

Every successful source-preparation job passed the original 16 unit cases. The seven new routing cases produce exactly two expected reuse failures under the original route, then all 23 selected unit cases pass with the candidate. Ten existing native integration cases pass: eight line-ending sensitivity/API/path-sensitivity combinations and two Java compilation line-ending cases. Performance scenario metadata validation also passes. These are targeted checks, not the complete Gradle test suite.

The portable fixture additionally performs 16 real build invocations per session covering relocation, CRLF-equivalent text, changed text, binary fallback and two simultaneous builds sharing a user home. Independent SHA-256 output expectations, baseline/candidate task-key equality, output equality and expected execution/cache outcomes are checked. The large campaign has 540 successful real build invocations including functional checks, seeds, warmups and measured invocations; this count is not 540 independent performance samples.

## Synthetic results

Three fresh VMs each ran 10 measured baseline/candidate pairs after two warmup pairs for the large cases. Each corpus has 50,000 distinct ordinary files of 8,192 bytes: 409,600,000 bytes total. Baseline-first and candidate-first order alternates. The marker task restores a tiny output and isolates source fingerprinting overhead; it does not model compilation or unpacking a backend build.

| Session | Baseline median | Candidate median | Paired median seconds saved | Paired median reduction | Input fingerprinting reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| session-1 | 21.350 s | 13.008 s | 8.416 s | 39.52% | 49.14% |
| session-2 | 20.145 s | 12.210 s | 8.009 s | 39.61% | 50.65% |
| session-3 | 20.728 s | 12.587 s | 8.189 s | 39.48% | 50.54% |

The fresh-checkout elapsed reduction is 39.48–39.61%, about 8.0–8.4 seconds per invocation. Input fingerprinting falls by 49.14–50.65%. Within-session bootstrap 95% intervals for paired elapsed savings are 7.61–9.12 s, 7.77–9.07 s and 7.80–8.76 s. These intervals resample pairs within each session and do not establish independence across hosted machines.

| Control | Dimensions | Observation across three sessions |
| --- | --- | --- |
| 1% changed source in fresh checkout | 50,000 files; 10 pairs per session | 32.45–34.56% lower elapsed time; correct changed output/key |
| Existing checkout | 50,000 files; 10 pairs per session | No clear elapsed difference; all within-session intervals include zero |
| Raw inputs without normalization | 50,000 files; 10 pairs per session | No clear elapsed difference; all intervals include zero |
| Empty user home and task-output cache | 1,000 files; 3 pairs per session | No consistent elapsed difference; all intervals include zero |
| Two concurrent fresh checkouts | 1,000 files; 10 paired groups per session | Per-worker input fingerprinting improves 25–29%; elapsed intervals include zero in two sessions |

Fresh normalized inputs restore task outputs from cache. Existing-checkout controls are up to date. Raw-input and cold-cache controls retain their intended behavior. Concurrent elapsed time covers the overlapping group interval; per-worker fingerprinting durations are not summed.

The earlier 1,000-file pilot is retained: five measured pairs showed roughly 3.8% paired elapsed improvement for fresh normalized inputs. Its three-pair cold control was around 4% slower; that slowdown was not consistent in the larger campaign. No slow observations were dropped. Laptop timings remain fixture smoke checks and are excluded from performance conclusions.

## Native generated-Java benchmark

The added Gradle performance scenario runs `clean assemble with local cache and cold project cache` on `largeMonolithicJavaProject`: 50,000 Java source files. It clears the project cache before every invocation, retains the user-home metadata and local task-output cache, disables file watching and uses a cold daemon. The project path stays the same; the separate portable fresh-checkout case tests changing paths.

First successful session: baseline median 29.36687 s versus candidate 25.26934 s, a 4.09753 s / 13.95% reduction. Measured values in seconds:

| Variant | All five measured values |
| --- | --- |
| Baseline | 29.71656, 29.36687, 29.93870, 29.35137, 29.08729 |
| Candidate | 25.39503, 25.71354, 24.60235, 24.97926, 25.26934 |

Two warmups per version are excluded from these medians. The native infrastructure executes the candidate version block first and the baseline block second; these are not paired or interleaved observations. The first run retained timing CSV and native test XML but no authoritative per-invocation `compileJava` cache-hit trace. Source-build `FROM-CACHE` lines are not evidence for the measured Java workload. Three further sessions passed the explicit cache-hit assertion. All 30 measured invocations report `:compileJava FROM-CACHE` in retained per-build logs. Each session contributes five measured invocations per version after two warmups.

| Native session | Allocated CPU / host CPU model | Baseline median | Candidate median | Seconds saved | Median reduction |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | 4 vCPU / AMD EPYC 7763 64-Core Processor | 27.924 s | 24.089 s | 3.835 s | 13.73% |
| 2 | 4 vCPU / AMD EPYC 9V74 80-Core Processor | 20.457 s | 16.948 s | 3.509 s | 17.15% |
| 3 | 4 vCPU / AMD EPYC 7763 64-Core Processor | 27.853 s | 24.012 s | 3.841 s | 13.79% |

The three trace-verified native sessions save 3.51–3.84 seconds, or 13.73–17.15%. The first native pilot and the three synthetic sessions used AMD EPYC 7763 hosts; native repeat 2 used an AMD EPYC 9V74 host. Each VM exposes four vCPUs and reports about 15 GiB RAM. Absolute timings differ between hosts, so comparisons are made within each session. The first untraced native pilot remains a separate preliminary result. Native version block ordering is not counterbalanced, and no outliers are removed.

## Costs and limits

The candidate global normalized-hash index was 3,343,285 bytes after the 50,000-file seed. In the changed-source case it grew to 3,744,229 bytes over two warmups and ten measured 1%-edit iterations. This is only the global index: baseline project-local indexes and complete cache storage are not included. It is not a comparison of total disk cost.

The global in-memory decorator has a reference size of 400,000 entries versus 800,000 for the local decorator, scaled by JVM heap. These reference sizes are not disk-retention bounds. The corpus does not saturate those limits. Long-lived daemon memory, peak RSS, eviction pressure, cleanup and sustained worktree churn remain unmeasured.

OS file caches are retained and corpus verification/copying happens before timing. This is not a cold-machine test. The reported improvements concern line-ending-normalized ordinary inputs; raw inputs and the unchanged classpath-resource route do not inherit the reported benefit. Native block ordering and shared-host interference limit causal certainty. No production backend build was benchmarked with the candidate.

The workflows use only standard public runners and upload no Actions artifacts or caches. Checksummed evidence is exported through job logs and decoded locally. The billing audit found zero artifact objects and zero active Actions caches. [GitHub billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions) states that standard public runners are free and logs do not count toward artifact storage.

## Reproducibility and decision

- [Experiment source and suite](https://github.com/manasjoshi14/gradle/tree/infra/normalized-source-cache-experiment/.github/experiments/normalized-source-cache).
- [Successful 1,000-file pilot](https://github.com/manasjoshi14/gradle/actions/runs/40630741821).
- [Three-session synthetic campaign](https://github.com/manasjoshi14/gradle/actions/runs/40632716920).
- [First successful native Java comparison](https://github.com/manasjoshi14/gradle/actions/runs/40636971330).
- [Cache-hit-verified native repetitions](https://github.com/manasjoshi14/gradle/actions/runs/40642071983), all three sessions passed.

Two setup failures are retained: [expected-failure test retries](https://github.com/manasjoshi14/gradle/actions/runs/40628793889) and [unreferenced shallow baseline tree](https://github.com/manasjoshi14/gradle/actions/runs/40634378583). Neither produced valid performance samples. Fixes disable test retries and give the pinned baseline a reachable local branch with an early clone probe.

Keep the candidate for further evaluation: the tested fresh-checkout benefit is substantial and repeatable, and the controls show no consistent elapsed regression at their tested dimensions. The native cache-hit-verified repetitions passed. Upstream discussion remains on hold as requested. Inspect long-lived cache costs and assess a representative build before making broader performance or merge-readiness claims. The first-build and concurrency controls here use only 1,000 files and do not establish their costs at 50,000 files. If those checks remove the meaningful benefit or reveal unacceptable costs, discard the change.

Gradle AI policy and contributor/test guidelines were reviewed. Any future contribution remains a human-owned decision requiring understanding, active review participation, significant-AI disclosure in the PR conversation and human DCO attestation. No AI co-author or DCO trailer has been added.

Local evidence includes raw profiler CSV, per-measured-build cache-hit logs, functional build-operation captures, source/test logs, test XML and SHA-256-verified evidence bundles. `synthetic-summary.csv`, `native-summary.csv`, `runner-hardware.json` and both analysis helpers expose the numbers used above.
