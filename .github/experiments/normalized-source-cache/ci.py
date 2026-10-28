#!/usr/bin/env python3
"""Build and compare the pinned experiment on free GitHub-hosted runners."""

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

SUITE = Path(__file__).resolve().parent
REPO = SUITE.parents[2]
BASE = 'e04ee63317eeb36ac5102b6a3aa7e6cd931850a2'
SOURCE = 'subprojects/core/src/main/java/org/gradle/api/internal/changedetection/state/SplitResourceSnapshotterCacheService.java'
OUT = Path(os.environ.get('EXPERIMENT_ROOT', '/tmp/normalized-cache-experiment'))
CORE_RESULTS = 'subprojects/core/build/test-results'
JAVA_RESULTS = 'platforms/jvm/language-java/build/test-results'
NORMALIZATION_RESULTS = 'platforms/core-execution/normalization-java/build/test-results'


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2) + '\n')


def invoke(command, name):
    target = OUT / 'logs' / (name + '.log')
    target.parent.mkdir(parents=True, exist_ok=True)
    print('Running:', ' '.join(command), flush=True)
    with target.open('w') as stream:
        process = subprocess.Popen(command, cwd=REPO, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            stream.write(line)
            print(line, end='', flush=True)
        return process.wait()


def gradle(tasks, name):
    return invoke(['./gradlew', *tasks, '--no-daemon', '--max-workers=2',
                   '--init-script', str(SUITE / 'no-test-retries.init.gradle'),
                   '--console=plain', '--stacktrace', '-PignoreIncomingBuildReceipt=true',
                   '-PbuildTimestamp=20261026160000+0000'], name)


def test_results(name, directories):
    destination = OUT / 'tests' / name
    destination.mkdir(parents=True, exist_ok=True)
    suites = []
    for directory in directories:
        for source in (REPO / directory).glob('TEST-*.xml'):
            result = ET.parse(source).getroot()
            suites.append({'class': result.get('name'), **{
                key: int(result.get(key, '0')) for key in ('tests', 'failures', 'errors', 'skipped')}})
            shutil.copy2(source, destination / source.name)
    if not suites:
        raise AssertionError(f'No XML test results for {name}')
    save(name + '.json', suites)
    return {key: sum(suite[key] for suite in suites) for key in ('tests', 'failures', 'errors', 'skipped')}


def require_tests(actual, tests, failures=0):
    assert actual == {'tests': tests, 'failures': failures, 'errors': 0, 'skipped': 0}, actual


def freeze(label):
    source = REPO / 'testing/distributions-core/build/bin distribution'
    target = OUT / 'runtimes' / label
    assert (source / 'bin/gradle').is_file(), source
    shutil.copytree(source, target, symlinks=False)


def build():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE, 'HEAD'], cwd=REPO, text=True).splitlines()
    allowed = {SOURCE, '.teamcity/performance-tests-ci.json',
               'subprojects/core/src/test/groovy/org/gradle/api/internal/changedetection/state/SplitResourceSnapshotterCacheServiceTest.groovy',
               'testing/performance/src/performanceTest/groovy/org/gradle/performance/regression/buildcache/TaskOutputCachingJavaPerformanceTest.groovy',
               '.github/workflows/normalized-source-cache.yml'}
    allowed.add('.github/workflows/normalized-source-cache-native.yml')
    assert all(path in allowed or path.startswith('.github/experiments/normalized-source-cache/') for path in changed), changed
    save('provenance.json', {'base': BASE, 'candidate_commit': head, 'changed_files': changed,
         'platform': platform.platform(), 'cpu_count': os.cpu_count(),
         'java_home': os.environ['JAVA_HOME'], 'java_version': subprocess.check_output(
             ['java', '-version'], stderr=subprocess.STDOUT, text=True),
         'runner_name': os.environ.get('RUNNER_NAME'), 'run_id': os.environ.get('GITHUB_RUN_ID'),
         'session': os.environ.get('EXPERIMENT_SESSION'), 'dedicated_machine': False,
         'runner_kind': 'standard GitHub-hosted ubuntu-24.04',
         'initial_free_bytes': shutil.disk_usage(OUT).free})
    production = REPO / SOURCE
    candidate = production.read_bytes()
    baseline = subprocess.check_output(['git', 'show', BASE + ':' + SOURCE], cwd=REPO)
    assert candidate != baseline
    validation = {}
    try:
        production.write_bytes(baseline)
        assert gradle([':core:test', '--tests', '*DefaultResourceSnapshotterCacheServiceTest',
                       ':normalization-java:test', '--tests', '*LineEndingNormalizingFileSystemLocationSnapshotHasherTest',
                       ':distributions-core:binInstallation'], 'baseline-build') == 0
        validation['baseline_unit'] = test_results('baseline-unit', [CORE_RESULTS + '/test', NORMALIZATION_RESULTS + '/test'])
        require_tests(validation['baseline_unit'], 16)
        freeze('baseline')
        code = gradle([':core:test', '--tests', '*SplitResourceSnapshotterCacheServiceTest'], 'expected-reuse-failures')
        validation['baseline_reuse_guard'] = test_results('baseline-reuse-guard', [CORE_RESULTS + '/test'])
        assert code != 0
        require_tests(validation['baseline_reuse_guard'], 7, failures=2)
    finally:
        production.write_bytes(candidate)
        save('validation.json', validation)
    assert gradle([':core:test', '--tests', '*ResourceSnapshotterCacheServiceTest',
                   ':normalization-java:test', '--tests', '*LineEndingNormalizingFileSystemLocationSnapshotHasherTest',
                   ':distributions-core:binInstallation'], 'candidate-build') == 0
    validation['candidate_unit'] = test_results('candidate-unit', [CORE_RESULTS + '/test', NORMALIZATION_RESULTS + '/test'])
    require_tests(validation['candidate_unit'], 23)
    freeze('candidate')
    assert gradle([':core:forkingIntegTest', '--tests', '*CachedLineEndingSensitivityIntegrationSpec.input files properties can ignore line endings when specified*',
                   ':language-java:forkingIntegTest', '--tests', '*JavaCompileLineEndingSensitivityIntegrationTest',
                   ':performance:verifyPerformanceScenarioDefinitions'], 'candidate-native-integration') == 0
    validation['candidate_native_integration'] = test_results('candidate-native-integration', [CORE_RESULTS + '/forkingIntegTest', JAVA_RESULTS + '/forkingIntegTest'])
    require_tests(validation['candidate_native_integration'], 10)
    validation['performance_scenario_definition_verified'] = True
    save('validation.json', validation)


def benchmark(files, runs, warmups, scenario):
    estimated_bytes = files * 8192 * (2 * (runs + warmups) + 3) * (3 if scenario == 'all' else 2) + 4 * 1024 ** 3
    free_bytes = shutil.disk_usage(OUT).free
    save('capacity.json', {'free_bytes_before_measurement': free_bytes,
                          'estimated_retained_workspace_bytes': estimated_bytes,
                          'files': files, 'runs': runs, 'warmups': warmups, 'scenario': scenario})
    if free_bytes < estimated_bytes:
        raise RuntimeError(f'Insufficient runner disk: {free_bytes} free bytes; estimated {estimated_bytes} needed')
    common = [sys.executable, str(SUITE / 'run.py'),
              '--baseline', str(OUT / 'runtimes/baseline/bin/gradle'),
              '--candidate', str(OUT / 'runtimes/candidate/bin/gradle'),
              '--java-home', os.environ['JAVA_HOME'], '--source-revision', BASE,
              '--runner-description', 'Exploratory standard GitHub-hosted ubuntu-24.04; session ' + os.environ.get('EXPERIMENT_SESSION', '1')]
    functional = OUT / 'results/functional'
    assert invoke([*common, '--mode', 'functional', '--output', str(functional)], 'portable-functional') == 0
    cases = [('fresh', 'fingerprintNormalized'), ('fresh', 'fingerprintRaw')]
    if scenario == 'all':
        cases += [(name, 'fingerprintNormalized') for name in ('warm', 'cold', 'churn', 'concurrent')]
    reports = []
    for name, task in cases:
        if shutil.disk_usage(OUT).free < 1024 ** 3:
            raise RuntimeError('Less than 1 GiB free; stopping before the next case')
        count = min(files, 1000) if name in ('cold', 'concurrent') else files
        case_runs = min(runs, 3) if name == 'cold' else runs
        case_warmups = min(warmups, 1) if name == 'cold' else warmups
        destination = OUT / 'results' / (name + '-' + task)
        command = [*common, '--mode', 'benchmark', '--scenario', name, '--task', task,
                   '--files', str(count), '--bytes-per-file', '8192',
                   '--runs', str(case_runs), '--warmups', str(case_warmups),
                   '--output', str(destination)]
        assert invoke(command, name + '-' + task) == 0
        result = json.loads((destination / 'report.json').read_text())
        assert result['measured_pairs'] == case_runs
        reports.append({'scenario': name, 'task': task, 'files': count, 'measured_pairs': case_runs,
                        'wall_difference_seconds': result['paired_median_wall_difference_seconds'],
                        'input_difference_ms': result['paired_median_input_difference_ms'],
                        'free_bytes_after': shutil.disk_usage(OUT).free})
        save('benchmark-index.json', {'exploratory': True, 'cases': reports})


def native():
    if shutil.disk_usage(OUT).free < 20 * 1024 ** 3:
        raise RuntimeError('Native generated-Java comparison requires at least 20 GiB free after source preparation')
    task = 'largeMonolithicJavaProjectPerformanceAdHocTest'
    code = gradle([':performance:' + task, '--tests',
                   'org.gradle.performance.regression.buildcache.TaskOutputCachingJavaPerformanceTest.clean assemble with local cache and cold project cache',
                   '-PperformanceBaselines=9.10.0-commit-' + BASE,
                   '--warmups=2', '--runs=5', '--profiler=none', '--checks=none'], 'native-java-performance')
    destination = OUT / 'native'
    destination.mkdir(exist_ok=True)
    source = REPO / 'testing/performance/build' / task
    retained = []
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ('.csv', '.json', '.log', '.txt', '.html') and path.stat().st_size <= 4 * 1024 ** 2:
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            retained.append(str(target.relative_to(OUT)))
    save('native-run.json', {'returncode': code, 'baseline_revision': BASE,
                            'requested_warmups_per_version': 2, 'requested_measured_runs_per_version': 5,
                            'retained_reports': retained, 'checks': 'none; collect adverse measurements too',
                            'profiler': 'none'})
    if code:
        raise RuntimeError('Native Java benchmark failed; retained logs and any partial reports')
    results = test_results('native-performance', ['testing/performance/build/test-results/' + task])
    assert results['failures'] == results['errors'] == 0 and results['tests'] > results['skipped'], results
    assert any(Path(path).name == 'benchmark.csv' for path in retained), 'Missing raw profiler measurements'


def export():
    paths = set(OUT.glob('*.json'))
    paths.update((OUT / 'logs').glob('*.log'))
    paths.update((OUT / 'tests').rglob('*.xml'))
    paths.update(path for path in (OUT / 'native').rglob('*') if path.is_file())
    for result in (OUT / 'results').glob('*'):
        if (result / 'report.json').exists():
            paths.add(result / 'report.json')
        for label in ('baseline', 'candidate'):
            paths.update((result / label).glob('*.log'))
            paths.update((result / label).glob('*.operations.json'))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, path.relative_to(OUT))
    payload = buffer.getvalue()
    assert len(payload) < 8 * 1024 ** 2, 'Evidence exceeds the bounded log export size'
    encoded = base64.b64encode(payload).decode()
    print('EXPERIMENT_EVIDENCE_BEGIN ' + hashlib.sha256(payload).hexdigest())
    for index in range(0, len(encoded), 24000):
        print('EXPERIMENT_EVIDENCE_CHUNK ' + encoded[index:index + 24000])
    print('EXPERIMENT_EVIDENCE_END ' + str(len(payload)))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as stream:
            stream.write('## Normalized source cache experiment\n\n')
            stream.write('Exploratory results from a standard free GitHub-hosted runner. Positive differences mean the candidate was faster.\n\n')
            for name in ('validation.json', 'benchmark-index.json'):
                path = OUT / name
                if path.exists():
                    stream.write('```json\n' + path.read_text() + '```\n\n')
            stream.write('Raw JSON, XML and logs are retained as a checksummed ZIP encoded in this step log. No Actions artifact or cache upload is used.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'benchmark', 'native', 'export'])
    parser.add_argument('--files', type=int, default=1000)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--scenario', choices=['fresh', 'all'], default='all')
    args = parser.parse_args()
    if not 100 <= args.files <= 50000 or not 3 <= args.runs <= 10 or not 1 <= args.warmups <= 3:
        parser.error('Experiment dimensions exceed the bounded free-runner limits')
    OUT.mkdir(parents=True, exist_ok=True)
    if args.action == 'build':
        build()
    elif args.action == 'benchmark':
        benchmark(args.files, args.runs, args.warmups, args.scenario)
    elif args.action == 'native':
        native()
    else:
        export()


if __name__ == '__main__':
    main()
