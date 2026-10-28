# Normalized source hash cache experiment

This suite evaluates a single routing change in `SplitResourceSnapshotterCacheService`. It does not copy binary cache indexes between Gradle user homes. Each distribution populates its own caches through ordinary builds.

The pinned source baseline is `e04ee63317eeb36ac5102b6a3aa7e6cd931850a2`.

[Results from 28 October 2026](results/hosted-20261028/RESULTS.md) include three synthetic sessions, three trace-verified native Java sessions, controls, raw sample summaries, hardware and limitations.

## Free GitHub Actions experiment

The `Normalized source cache experiment` workflow runs only by manual dispatch on the public `manasjoshi14/gradle` fork. It uses standard `ubuntu-24.04` runners, performs no Actions cache or artifact upload, and has read-only repository permissions. It creates no issues or pull requests.

Each session builds both source distributions on the same VM. The baseline restores only the routing source to the pinned revision; all other production sources must match that revision. It checks the original 16 unit cases, confirms the two new reuse cases fail under the original routing, checks all 23 candidate unit cases, and runs the 10 existing native integration cases plus performance scenario metadata verification. Source-build test retries are disabled so expected failures and flaky failures remain visible in the exact test counts.

The portable functional check and paired benchmark cases run after source builds finish. Fresh checkouts and the raw-input negative control use the requested file count. Cold-cache and concurrent cases use at most 1,000 files; the cold-cache control uses at most three measured pairs to bound disk use. Actual dimensions are recorded in each report. Up to three matrix sessions run in parallel on separate fresh VMs, each comparing both variants within its own job.

The first hosted VM reported about 85 GiB free before building. Available space is not assumed for subsequent jobs: conservative retained-workspace byte and inode estimates are checked before measurements. File-count choices extend to 150,000. With 8 KiB per file, 10 measured pairs and two warmup pairs, the fresh normalized case plus raw control at 150,000 files requires an estimated 65.8 GiB and 8.36 million free inodes. The all-six-case choice requires more space and may be refused. Different file-count workflow dispatches may run concurrently; each session still compares both distributions serially on its own VM.

These are exploratory measurements on shared hosted infrastructure. Repeat sessions and retain adverse results; a successful workflow alone does not establish a performance benefit.

The final workflow step writes a checksummed ZIP containing raw JSON, XML and build logs as Base64 chunks prefixed with `EXPERIMENT_EVIDENCE_CHUNK` in the job log. The enclosing begin marker supplies its SHA-256. No runtimes, source workspaces, or caches are included. This preserves evidence without creating billable Actions artifacts. Download the job logs and decode the chunks separately for each session.

After a run completes, the collection helper downloads its logs through the authenticated GitHub CLI, verifies each evidence checksum, and extracts the sessions. It performs read-only GitHub calls. Supply an empty output directory for a new run:

```bash
python3 .github/experiments/normalized-source-cache/collect.py \
  --run-id 40632716920 \
  --output /tmp/normalized-cache-synthetic-results
python3 .github/experiments/normalized-source-cache/analyze.py \
  /tmp/normalized-cache-synthetic-results
```

`analyze.py` retains every measured pair, verifies equal outputs and task keys, and calculates paired medians and within-session bootstrap intervals. These intervals do not establish independence between shared hosted VMs.

For a native run, use `analyze-native.py` on its collected output directory instead. Add `--require-traces` for runs with retained measured-build logs. It verifies five measured samples per version, two warmups per version, and a `:compileJava FROM-CACHE` trace for every measured sample. Native samples run in version blocks and are summarized without treating them as interleaved pairs.

## Build the two distributions

Use two clean local checkouts of the pinned revision. Export `git diff e04ee63317eeb36ac5102b6a3aa7e6cd931850a2 HEAD` from the experiment branch to a patch and apply it only to the candidate checkout. Keep build outputs and Gradle user homes outside the source directories that the benchmark will create. This preparation happens before measurement.

Build both checkouts with the same JDK 25, the same timestamp, and the same command:

```bash
./gradlew :distributions-full:binDistributionZip \
  -PignoreIncomingBuildReceipt=true \
  -PbuildTimestamp=20261026160000+0000 \
  --max-workers=4 \
  --console=plain
```

Extract each resulting `packaging/distributions-full/build/distributions/gradle-*-bin.zip` into a separate directory. The portable fixture needs no downloaded dependencies and runs offline. The distributions used for the local functional checks were frozen copies of the source-built core installation; those macOS binaries are not included in the portable bundle.

The patch also contains the new regression tests and Java performance scenario. It adds no remote cache transport or new cache format.

## Correctness

`run.py --mode functional` exercises identical relocated inputs, CRLF equivalence, changed text, binary fallback, and simultaneous builds in two directories sharing a Gradle user home. Every build output is checked against an independently calculated digest. Build operation captures verify task cache keys and outcomes.

The repository unit tests additionally distinguish normalizer configurations, failed calculations, null results, and the unchanged classpath-resource overload.

## Measurements

`run.py --mode benchmark` consumes two built Gradle distributions reporting the same Gradle version. It checks the routing class digest and refuses identical implementations unless `--smoke` is supplied. The caller must build both distributions from the pinned source revision, with only the proposed routing change in the candidate.

Both variants run on one machine. The order alternates between baseline-first and candidate-first. Each variant has an independent user home and task-output cache. Corpus creation, copying checkouts, and independent output verification happen outside the measured invocation.

The default scenario uses a new project directory and cold daemon for every invocation, while retaining that variant's Gradle user home and cached task outputs. OS file caches are retained. The scenario is not a cold-machine benchmark.

The marker task isolates source input fingerprinting and restores a tiny output. Its total time includes startup and configuration. It does not model Java compilation or materializing the backend's compiled outputs. Use the additional repository Java performance scenario to assess cached Java build wall time.

The `warm`, `cold`, and `churn` scenarios respectively retain the project cache, start with empty Gradle and task caches, and change approximately one percent of source files per iteration. The `concurrent` scenario measures multiple new checkouts sharing each variant's warm user home; use `--parallel-checkouts` to set the count. Parallel samples are separate from serial samples. Group wall time covers the overlapping invocation interval, while the group's input-fingerprinting metric is the median per-worker duration; these durations are not summed.

Repeat the fresh-checkout benchmark with `--task fingerprintRaw` as a negative control. This task does not normalize line endings and should not benefit from the proposed routing change.

All workspaces, logs, operation captures, raw measurements, and the exact harness source are retained. Final JVM heap use is recorded as a diagnostic; it is not peak heap or process RSS. A 50,000-file corpus with 8 KiB per file consumes about 400 MB per checkout, so provision sufficient runner disk space for retained repetitions and parallel workers.

## Runner invocation

Run on an otherwise idle dedicated machine with fixed JDK, hardware, and filesystem. Build distributions and resolve prerequisites before starting measurements.

```bash
python3 run.py \
  --baseline /opt/gradle-baseline/bin/gradle \
  --candidate /opt/gradle-candidate/bin/gradle \
  --java-home /opt/jdk-25 \
  --source-revision e04ee63317eeb36ac5102b6a3aa7e6cd931850a2 \
  --output /data/normalized-cache-run-001 \
  --mode all \
  --scenario fresh \
  --files 50000 \
  --bytes-per-file 8192 \
  --warmups 3 \
  --runs 10 \
  --runner-description 'Dedicated runner; record CPU, RAM, disk, OS and background load'
```

The output directory must not already exist. Use a new output directory for each scenario and repeat the experiment in multiple sessions. Compare paired distributions of input-fingerprinting time and wall time, retaining variability and adverse results. Cache size and host load are recorded per invocation. The suite does not automatically declare an optimization successful.

Run the same command separately for each of these cases, changing `--scenario`, `--task`, and `--output`:

| Scenario | Task | Purpose |
| --- | --- | --- |
| fresh | fingerprintNormalized | New checkout with populated user-home metadata and task cache |
| warm | fingerprintNormalized | Existing checkout regression control |
| cold | fingerprintNormalized | Empty user-home and task-cache regression control |
| churn | fingerprintNormalized | Repeated source edits and cache growth |
| concurrent | fingerprintNormalized | Shared-cache contention across checkouts |
| fresh | fingerprintRaw | Input fingerprinting without normalization |

For a first runner session, use 1,000 files and validate correctness, outcomes, and captures. Then repeat with 10,000 and 50,000 files. Retaining 50,000-file workspaces across this matrix requires tens of gigabytes of disk. Repeat in independent sessions and estimate uncertainty from paired samples; ten runs from one session alone are not sufficient to establish a stable improvement.

## Repository Java performance scenario

The patch adds `TaskOutputCachingJavaPerformanceTest.clean assemble with local cache and cold project cache`. It retains user-home metadata and task outputs, clears the project cache before every build, disables file watching, and starts with a cold daemon. Its generated `largeMonolithicJavaProject` fixture contains 50,000 Java source files.

From the candidate checkout, the native performance infrastructure can compare against the unchanged source commit:

```bash
./gradlew :performance:largeMonolithicJavaProjectPerformanceAdHocTest \
  --tests 'org.gradle.performance.regression.buildcache.TaskOutputCachingJavaPerformanceTest.clean assemble with local cache and cold project cache' \
  -PperformanceBaselines=9.10.0-commit-e04ee63317eeb36ac5102b6a3aa7e6cd931850a2 \
  --warmups=3 \
  --runs=10 \
  --max-workers=2 \
  --console=plain
```

This command is prepared from the repository's task and baseline-resolution implementation. It has not been executed locally. The repository infrastructure builds a clean baseline commit distribution and may download its prerequisites; provision them before the measurement session. Inspect the resulting runtime provenance and task-cache hits. Its default release-version comparison would not isolate this change, so use the explicit pinned commit baseline.

The native scenario measures the same checkout with its project cache removed; the portable `fresh` scenario additionally changes the checkout path. Assess both, and compare the existing `clean assemble with local cache` scenario for ordinary builds.

The fork also provides the manually dispatched `Normalized source cache native Java benchmark` workflow. It prepares the same pinned source comparison, then runs this native scenario with two warmups and five measured invocations per version. Select one or three independent free runner sessions. Each measured invocation must report `:compileJava FROM-CACHE`; its build log is retained with the raw timing CSV. The native infrastructure runs one version's samples before the other version's samples, so these samples are not interleaved pairs. Profiling is disabled and performance regression checks are disabled for data collection; a green job means execution and cache-hit checks passed, rather than proving a speedup. Raw profiler CSV, small report files, native test XML and logs are retained in the checksummed job-log export. This workflow requires at least 20 GiB free after source preparation and uses no Actions artifact or cache upload.

For the size-scaling campaign, the native workflow accepts 10,000, 50,000, 100,000 or 150,000 main Java files. `ci.py native --files N` sets `NORMALIZED_CACHE_SOURCE_FILES` for the init script. `native-scaling.init.gradle` passes the count as an explicit JVM system property to both the generator and performance test worker, and declares it as a task input. This also avoids relying on custom environment variables that the Gradle test infrastructure filters out. The cached template cannot cross file-count settings. All four sizes use a 1,536 MiB target daemon heap and an 8 GiB initial and maximum compiler heap for the untimed cache-populating compilation; measured compilations must restore from cache. Outside the scaling environment, the original 50,000-file / 4 GiB compiler defaults remain.

Before the first warmup, each native version records its main Java file count, bytes and SHA-256 over sorted relative paths and contents. The collector retains these inventories, and the CI driver requires both variants to have the requested count and identical source inventories. This validation happens outside measured invocations. The generator also writes test sources; the requested counts and measured `assemble` workload refer to main sources.

## Decision after runner measurements

Proceed only if the new-checkout improvement is reproducible in input fingerprinting and relevant build wall time, with acceptable warm-build, first-build, cache-growth, and concurrency costs. Report variability and negative controls. If the result is noise, negligible build savings, or unacceptable regressions, discard the candidate. Long-lived daemon memory and peak process memory remain separate follow-up measurements; the portable fixture uses single-use daemons and captures only final heap diagnostics.

`--smoke` disables performance comparison and permits the same unmodified distribution on both sides. This validates the fixture and capture machinery only.

No GitHub issue, pull request, fork, or runner provisioning is performed by this suite.
