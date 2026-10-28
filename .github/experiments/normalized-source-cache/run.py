#!/usr/bin/env python3
"""Exercise supplied Gradle distributions without changing installed Gradle caches."""

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import time
import zipfile
from pathlib import Path

SUITE = Path(__file__).resolve().parent
TASK = 'fingerprintNormalized'
ROUTER = 'org/gradle/api/internal/changedetection/state/SplitResourceSnapshotterCacheService.class'


def identity(executable, java_home, user_home):
    executable = Path(executable).resolve()
    env = dict(os.environ, JAVA_HOME=str(java_home), GRADLE_USER_HOME=str(user_home))
    version = subprocess.check_output([str(executable), '--version'], env=env, text=True)
    core = next(executable.parent.parent.glob('lib/gradle-core-[0-9]*.jar'))
    with zipfile.ZipFile(core) as archive:
        router_hash = hashlib.sha256(archive.read(ROUTER)).hexdigest()
    return {'executable': str(executable), 'version': re.search(r'^Gradle (.+)$', version, re.M)[1],
            'router_class_sha256': router_hash, 'version_output': version}


def contents(index, size=256):
    text = f'package p{index // 100:04d};\npublic class Source{index:06d} {{ int value() {{ return {index}; }} }}\n'
    return (text + '/*' + 'x' * max(0, size - len(text) - 5) + '*/\n').encode()


def expected_marker(project, task=TASK):
    digest = hashlib.sha256()
    for source in sorted((project / 'src').rglob('*.java')):
        data = source.read_bytes()
        if task == TASK and b'\0' not in data:
            data = data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
        digest.update(data)
    return digest.hexdigest()


class Experiment:
    def __init__(self, args):
        self.args = args
        self.output = Path(args.output).resolve()
        if self.output.is_relative_to(SUITE):
            raise ValueError('Put results outside the runner suite directory')
        self.output.mkdir(parents=True, exist_ok=False)
        shutil.copytree(SUITE, self.output / 'harness', ignore=shutil.ignore_patterns('__pycache__'))
        self.runtimes = {label: identity(getattr(args, label), args.java_home, self.output / ('identity-' + label))
                         for label in ('baseline', 'candidate')}
        if len({item['version'] for item in self.runtimes.values()}) != 1:
            raise ValueError('Both distributions must report the same Gradle version')
        identical = len({item['router_class_sha256'] for item in self.runtimes.values()}) == 1
        if identical and not args.smoke:
            raise ValueError('Identical routing implementations: use --smoke only to validate the harness')
        self.report = {'schema': 1, 'mode': args.mode, 'smoke_only': args.smoke,
                       'source_revision': args.source_revision, 'runtimes': self.runtimes,
                       'environment': {'platform': platform.platform(), 'cpu_count': os.cpu_count(),
                                       'java_home': str(Path(args.java_home).resolve()),
                                       'runner': args.runner_description},
                       'files': args.files, 'bytes_per_file': args.bytes_per_file,
                       'scenario': args.scenario, 'task': args.task,
                       'warmups': args.warmups, 'runs': args.runs,
                       'parallel_checkouts': args.parallel_checkouts,
                       'order_strategy': 'alternating baseline-first and candidate-first',
                       'records': [], 'comparison_eligible': False}
        self.save()

    def save(self):
        target = self.output / 'report.json'
        temporary = target.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(self.report, indent=2) + '\n')
        temporary.replace(target)

    def project(self, name, corpus=None):
        project = self.output / 'workspaces' / name
        project.mkdir(parents=True, exist_ok=False)
        for source in (SUITE / 'fixture').iterdir():
            shutil.copy2(source, project / source.name)
        if corpus:
            shutil.copytree(corpus, project / 'src')
        else:
            (project / 'src').mkdir()
            (project / 'src' / 'Source.java').write_bytes(contents(1))
        return project

    def run(self, label, name, project, *, task=TASK, cold=False, expected=None):
        group = self.output / label
        group.mkdir(exist_ok=True)
        user_home = group / ('home-' + name if cold else 'user-home')
        task_cache = group / ('outputs-' + name if cold else 'task-cache')
        operations = group / (name + '.operations.json')
        log = group / (name + '.log')
        command = [self.runtimes[label]['executable'], '-p', str(project), '-g', str(user_home),
                   '--no-daemon', '--no-watch-fs', '--no-configuration-cache', '--offline',
                   '--build-cache', '--max-workers=1', '--console=plain',
                   '-I', str(SUITE / 'operations.init.gradle'),
                   '-Dexperiment.operations=' + str(operations),
                   '-Dexperiment.taskCache=' + str(task_cache), task]
        expected = expected if expected is not None else expected_marker(project, task)
        load_before = os.getloadavg() if hasattr(os, 'getloadavg') else None
        start = time.monotonic_ns()
        with log.open('w') as stream:
            result = subprocess.run(command, env=dict(os.environ, JAVA_HOME=self.args.java_home),
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=900)
        end = time.monotonic_ns()
        wall = (end - start) / 1_000_000_000
        if result.returncode:
            raise RuntimeError(f'{label}/{name} failed; inspect {log}')
        capture = json.loads(operations.read_text())
        if capture['errors']:
            raise RuntimeError(f'Build-operation capture failed: {capture["errors"]}')
        measured = capture['tasks'][':' + task]
        if measured.get('failed'):
            raise RuntimeError(f'{label}/{name}: task failed')
        marker = (project / 'build' / (task + '.txt')).read_text().strip()
        if marker != expected:
            raise AssertionError(f'{label}/{name}: output differs from independently calculated digest')
        cache_bytes = sum(path.stat().st_size for path in user_home.rglob('resourceHashesCache.bin'))
        record = dict(measured, label=label, name=name, kind='invocation', wallSeconds=wall, output=marker,
                      invocationStartNs=start, invocationEndNs=end,
                      finalHeapUsedBytes=capture.get('finalHeapUsedBytes'),
                      finalHeapCommittedBytes=capture.get('finalHeapCommittedBytes'),
                      heapMaxBytes=capture.get('heapMaxBytes'),
                      resourceCacheBytes=cache_bytes, loadBefore=load_before,
                      loadAfter=os.getloadavg() if hasattr(os, 'getloadavg') else None)
        return record

    def record(self, result):
        self.report['records'].append(result)
        self.save()
        print(json.dumps(result), flush=True)
        return result

    def functional(self, label):
        results = []
        for name, data in [('original', contents(1)), ('relocated', contents(1)),
                           ('crlf', contents(1).replace(b'\n', b'\r\n')),
                           ('changed', contents(1).replace(b'return 1;', b'return 2;')),
                           ('binary-lf', b'\0binary\n'), ('binary-crlf', b'\0binary\r\n')]:
            project = self.project(label + '-functional-' + name)
            (project / 'src' / 'Source.java').write_bytes(data)
            results.append(self.record(self.run(label, 'functional-' + name, project)))
        original, relocated, crlf, changed, binary_lf, binary_crlf = results
        assert original['outcome'] == 'EXECUTED'
        assert original['key'] == relocated['key'] == crlf['key']
        assert relocated['outcome'] == crlf['outcome'] == 'FROM-CACHE'
        assert original['key'] != changed['key'] and changed['outcome'] == 'EXECUTED'
        assert binary_lf['key'] != binary_crlf['key']
        assert binary_lf['outcome'] == binary_crlf['outcome'] == 'EXECUTED'
        projects = [self.project(label + '-parallel-' + str(i)) for i in range(2)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.run, label, 'parallel-' + str(i), project)
                       for i, project in enumerate(projects)]
            for future in futures:
                result = self.record(future.result())
                assert result['key'] == original['key'] and result['outcome'] == 'FROM-CACHE'

    def concurrent_iteration(self, label, name, corpus):
        projects = [self.project(f'{label}-{name}-worker-{index}', corpus)
                    for index in range(self.args.parallel_checkouts)]
        expected = expected_marker(projects[0], self.args.task)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(projects)) as executor:
            futures = [executor.submit(self.run, label, f'{name}-worker-{index}', project,
                                       task=self.args.task, expected=expected)
                       for index, project in enumerate(projects)]
            results = [self.record(future.result()) for future in futures]
        assert all(result['outcome'] == 'FROM-CACHE' for result in results)
        assert len({result['key'] for result in results}) == 1
        assert results[0].get('key')
        assert all(result.get('inputSnapshotMs') is not None for result in results)
        start = min(item['invocationStartNs'] for item in results)
        end = max(item['invocationEndNs'] for item in results)
        return dict(label=label, name=name, kind='parallel-group', workers=len(results),
                    key=results[0]['key'], output=results[0]['output'], outcome='FROM-CACHE',
                    invocationStartNs=start, invocationEndNs=end,
                    wallSeconds=(end - start) / 1_000_000_000,
                    inputSnapshotMs=statistics.median(item['inputSnapshotMs'] for item in results),
                    inputSnapshotStatistic='median-per-worker')

    def benchmark(self):
        corpus = self.output / 'corpus'
        corpus.mkdir()
        for index in range(self.args.files):
            path = corpus / f'p{index // 100:04d}' / f'Source{index:06d}.java'
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(contents(index, self.args.bytes_per_file))
        self.report['corpus_bytes'] = sum(path.stat().st_size for path in corpus.rglob('*.java'))
        warm_projects = {}
        for label in self.runtimes:
            project = self.project(label + '-seed', corpus)
            warm_projects[label] = project
            seed = self.run(label, 'seed', project, task=self.args.task)
            seed['phase'] = 'seed'
            self.record(seed)
        pairs = []
        for iteration in range(self.args.warmups + self.args.runs):
            order = ['baseline', 'candidate'] if iteration % 2 == 0 else ['candidate', 'baseline']
            pair = {}
            for label in order:
                name = f'iteration-{iteration:03d}'
                if self.args.scenario == 'concurrent':
                    result = self.concurrent_iteration(label, name, corpus)
                    result['phase'] = 'warmup' if iteration < self.args.warmups else 'measure'
                    pair[label] = self.record(result)
                    continue
                if self.args.scenario == 'warm':
                    project = warm_projects[label]
                else:
                    project = self.project(label + '-' + name, corpus)
                if self.args.scenario == 'churn':
                    for index in range(iteration % 100, self.args.files, 100):
                        path = project / 'src' / f'p{index // 100:04d}' / f'Source{index:06d}.java'
                        path.write_bytes(contents(index, self.args.bytes_per_file) + f'// edit {iteration}\n'.encode())
                result = self.run(label, name, project, task=self.args.task,
                                  cold=self.args.scenario == 'cold')
                result['phase'] = 'warmup' if iteration < self.args.warmups else 'measure'
                self.record(result)
                if self.args.scenario == 'fresh':
                    assert result['outcome'] == 'FROM-CACHE'
                    assert result.get('key') and result.get('inputSnapshotMs') is not None
                pair[label] = result
            assert pair['baseline']['key'] == pair['candidate']['key']
            assert pair['baseline']['output'] == pair['candidate']['output']
            if iteration >= self.args.warmups:
                pairs.append(pair)
        if not self.args.smoke:
            self.report['paired_median_wall_difference_seconds'] = statistics.median(
                pair['baseline']['wallSeconds'] - pair['candidate']['wallSeconds'] for pair in pairs)
            input_differences = [pair['baseline']['inputSnapshotMs'] - pair['candidate']['inputSnapshotMs']
                                 for pair in pairs
                                 if pair['baseline'].get('inputSnapshotMs') is not None
                                 and pair['candidate'].get('inputSnapshotMs') is not None]
            self.report['paired_median_input_difference_ms'] = (
                statistics.median(input_differences) if input_differences else None)
            self.report['comparison_eligible'] = bool(self.args.runner_description)
        self.report['measured_pairs'] = len(pairs)
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'java-home', 'output', 'source-revision'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--mode', choices=['functional', 'benchmark', 'all'], default='all')
    parser.add_argument('--scenario', choices=['fresh', 'warm', 'cold', 'churn', 'concurrent'], default='fresh')
    parser.add_argument('--parallel-checkouts', type=int, default=2)
    parser.add_argument('--task', choices=[TASK, 'fingerprintRaw'], default=TASK)
    parser.add_argument('--files', type=int, default=1000)
    parser.add_argument('--bytes-per-file', type=int, default=8192)
    parser.add_argument('--warmups', type=int, default=3)
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--runner-description', default='')
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    if args.files < 1 or args.bytes_per_file < 128 or args.warmups < 0 or args.runs < 1 or args.parallel_checkouts < 1:
        parser.error('Invalid corpus size or iteration counts')
    experiment = Experiment(args)
    if args.mode in ('functional', 'all'):
        for label in experiment.runtimes:
            experiment.functional(label)
        baseline_records = {record['name']: record for record in experiment.report['records']
                            if record['label'] == 'baseline'}
        for record in experiment.report['records']:
            if record['label'] == 'candidate':
                baseline = baseline_records[record['name']]
                assert baseline['key'] == record['key']
                assert baseline['output'] == record['output']
        experiment.report['functional_passed'] = True
        experiment.save()
    if args.mode in ('benchmark', 'all'):
        experiment.benchmark()


if __name__ == '__main__':
    main()
