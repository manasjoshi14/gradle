# Normalized source cache: size-scaling experiments

28 October 2026. Both benchmark types ran at 10,000, 50,000, 100,000 and 150,000 main source files, with three independent standard public GitHub-hosted VMs per type and size. Positive savings mean the candidate was faster. These are exploratory hosted-runner measurements, not a production-build forecast or a merge-readiness claim.

## Results

| Main source files | Source seconds saved | Source reduction | Java assemble seconds saved | Java reduction |
| ---: | ---: | ---: | ---: | ---: |
| 10,000 | 1.75–1.82 | 19.7–30.0% | 0.59–0.97 | 4.1–10.6% |
| 50,000 | 7.22–9.29 | 38.8–52.2% | 3.21–4.65 | 15.3–21.0% |
| 100,000 | 14.18–17.26 | 44.1–48.6% | 7.62–8.13 | 16.3–16.8% |
| 150,000 | 25.32–43.89 | 45.7–63.7% | 10.19–12.99 | 17.7–22.0% |

Each cell is the range across the three VM sessions, not a confidence interval. Source values are medians of paired differences and paired percentages. Java values compare the two version medians; its samples are not paired. Hardware differs across sessions, so comparisons stay within each VM. [The complete CSV](combined-summary.csv) retains every session, baseline/candidate medians, CPU model, source bytes, source intervals and Java cache-hit counts. No measured samples were dropped.

Every normalized-source session has a positive within-session 95% paired-bootstrap interval. Every raw-control interval includes zero. The intervals resample ten pairs within a session and do not account for all shared-host variability or establish dedicated-machine repeatability. Native results have five samples per version and fixed version ordering; no equivalent paired interval is reported.

## What was compared

The pinned source baseline is `e04ee63317eeb36ac5102b6a3aa7e6cd931850a2`. The candidate routes ordinary `FileSystemLocationSnapshot` normalized hashes through the existing Gradle user-home/global cache. Its key is the raw content hash plus normalizer configuration hash. The classpath-resource `RegularFileSnapshotContext` overload retains its original routing. Cache format, task keys and remote transport are unchanged.

Source timing jobs use commit `4805d27b3b45df25343145f0dd92e239d84b0caf`. Native 10k/50k jobs use `9e393c5aab6ee7d95a53f5f18eedf14fb3c71d52`; native 100k/150k jobs use `4395376fa993f4e22ae3b3ccab7857c610ab0ad5`. The production routing change is identical; later commits correct the native fixture parameterization and diagnostics. Both variants use Temurin JDK 25.0.3+9. Source preparation finishes before timing. Versions use separate user homes. The source suite also uses separate task-output cache directories; the native suite clears its local task-output cache at the start of each version. Each cache is populated through ordinary builds.

The source suite copies its fixture to a new project path for each invocation, with populated user-home metadata and task outputs. Each unique UTF-8 file is exactly 8,192 bytes: the largest corpus is 1,228,800,000 bytes. A tiny cached marker output exposes fingerprinting overhead without compilation or class-output unpacking. Each VM runs normalized inputs and a raw-input control, with two warmup pairs and ten measured pairs. Baseline-first and candidate-first order alternates. All measured task keys, output checksums and cache outcomes are verified.

The native suite uses Gradle's `largeMonolithicJavaProject` and the added cold-project-cache Java scenario. It clears the project cache and build outputs, retains user-home metadata and task outputs, disables file watching, and starts a cold daemon. The working path stays fixed; this is a cold-project-cache proxy, while the source suite exercises actual path relocation. There are two warmups and five measured cached `assemble` invocations per version. Candidate samples run as one block before the baseline block. Every measured `compileJava` must report `FROM-CACHE`. The `jar` task still executes, so the duration includes class-cache restoration and JAR packaging.

All native sizes use a 1,536 MiB target daemon heap and an 8 GiB initial/maximum compiler heap for the untimed cache-populating compilation. The generator also writes test sources; the requested counts and `assemble` workload refer to main sources. The count is an explicit JVM property and task input, preventing reuse of a template generated at a different count. Before the first warmup, both variants record and validate identical source counts and path/content SHA-256 inventories. The 100k/150k fixtures enable ZIP64 equally on both variants because their output JARs exceed 65,535 archive entries. The smaller fixture archive settings are unchanged.

| Files | Main-source bytes | Inventory SHA-256 |
| ---: | ---: | --- |
| 10,000 | 19,209,050 | `b6a1d4ab79a887378bb73de493c6ff6fab025f9e6b88a7a33efa70c6a0ca15bb` |
| 50,000 | 96,287,597 | `5654ba6cdd1d6b51275e45c96e4db12ec710d956286467bf69ff85e52a436173` |
| 100,000 | 192,652,853 | `6999a8e8b9f05067d2243ed8c65c8aab30cc532f2a10a2dde21c85ba8a928ecb` |
| 150,000 | 289,229,249 | `24f45fbb0aac84524db9c554f1ea560833e5d83e0df48fc17b49fba789ea51b7` |

The native and source fixtures have different bytes per file and different task work. Their timings should not be compared as equivalent workloads.

## Correctness and evidence

Every successful preparation passes the original 16 unit cases. Seven new routing guards produce exactly two expected failures against the original route; all 23 selected unit cases pass with the candidate. Ten existing integration cases cover line-ending, input API/path-sensitivity and Java compilation behavior. Scenario metadata validation passes. These are targeted checks, not the entire Gradle test suite.

The source suite also performs 16 real functional build invocations per VM covering relocation, equivalent CRLF text, changed text, binary fallback and concurrent builds. The scaling campaign contains 192 such functional invocations and 480 measured source invocations, plus seeds and warmups. All 120 measured native Java invocations have retained `compileJava FROM-CACHE` traces. These invocation counts are not independent sample counts.

Raw CSVs, task traces, XML and logs are retained in checksummed job-log exports and in the local evidence packet. `campaign.json` records commits, requests, retries and setup failures. `combined-summary.json` is the machine-readable analysis. The public workflows upload no Actions artifacts or caches.

| Files | Source comparison | Native Java comparison |
| ---: | --- | --- |
| 10,000 | [Run](https://github.com/manasjoshi14/gradle/actions/runs/40654899513) | [Run](https://github.com/manasjoshi14/gradle/actions/runs/40661322679) |
| 50,000 | [Run](https://github.com/manasjoshi14/gradle/actions/runs/40654903858) | [Run](https://github.com/manasjoshi14/gradle/actions/runs/40663940702) |
| 100,000 | [Run](https://github.com/manasjoshi14/gradle/actions/runs/40654908735) | [Run](https://github.com/manasjoshi14/gradle/actions/runs/40668040873) |
| 150,000 | [Run](https://github.com/manasjoshi14/gradle/actions/runs/40654913060) | [Run](https://github.com/manasjoshi14/gradle/actions/runs/40668047581) |

Invalid native setup attempts are retained: an unavailable JSON utility import, a source-count mismatch because the test worker filters custom environment variables, and the 100k/150k legacy archive-entry limit. None produced valid measured samples. A separate local functional check reproduced the archive failure and then produced byte-identical valid 65,538-entry ZIP64 JARs on both runtimes; no laptop timings are used as benchmark evidence. The correction passes an explicit JVM property to both generator and test worker and bounds mismatch diagnostics. Two source jobs were cancelled after more than 45 minutes without configuration progress and retried individually; their successful peers and all measured samples were retained. Attempt logs preserve the interrupted setup evidence. To recover the 50k/100k source campaigns from GitHub, run `collect.py` with `--attempt 1` followed by `--attempt 2`, using the same output directory in that order; the second attempt replaces the interrupted session and retains its successful peers. Other active campaign runs have one attempt.

## Limits and decision boundary

The benchmark requires a populated user-home normalization cache; it does not establish a speedup for the first-ever build with an empty user home. It does not transport normalized hashes through a remote task-output cache. Corpus copying and checksum verification happen before timed Gradle calls; Git/worktree creation time is not measured. OS file caches remain warm, the synthetic marker output is tiny, and native version order is not counterbalanced. No production backend build was run with the candidate, and this Gradle 9.10 source experiment does not establish behavior on a different installed Gradle version.

Long-lived daemon memory, peak RSS, sustained cache growth/cleanup, cache eviction and large concurrent worktree churn remain unmeasured. The earlier [50k campaign](../hosted-20261028/RESULTS.md) includes additional warm/churn controls and smaller cold/concurrent controls; those were not expanded to every size here. Source file count alone cannot forecast whole-build savings across a multi-project dependency graph.

The results justify further review of the sharing/retention tradeoff. They do not remove the original reason for keeping mutable project metadata local. No upstream Gradle issue or PR has been created, and no paid resources were provisioned. Standard public GitHub runners were used; evidence travels through logs. The final API audit is retained as `verification.json`. The experimental patch, harness, orchestration and analysis were prepared with significant AI assistance.
