#!/usr/bin/env python3
"""Summarize native profiler samples and verify retained measured-build traces."""

import argparse
import csv
import json
from pathlib import Path
import statistics

BASE = 'e04ee63317eeb36ac5102b6a3aa7e6cd931850a2'


def analyze(session, require_traces):
    run = json.loads((session / 'native-run.json').read_text())
    assert run['returncode'] == 0, run
    sources = list((session / 'native').rglob('benchmark.csv'))
    assert len(sources) == 1, sources
    samples = {'baseline': [], 'candidate': []}
    warmups = {'baseline': [], 'candidate': []}
    tools = {}
    with sources[0].open(newline='') as stream:
        for row in csv.DictReader(stream):
            if row['Sample'] != 'total execution time':
                continue
            assert row['Tasks'] == 'assemble', row
            label = 'baseline' if 'commit-' + BASE in row['Tool'] else 'candidate'
            tools[label] = row['Tool']
            target = samples if row['Phase'] == 'MEASURE' else warmups
            assert row['Phase'] in ('MEASURE', 'WARM_UP'), row
            target[label].append(float(row['Duration']) / 1000)
    assert set(tools) == {'baseline', 'candidate'}, tools
    assert all(len(values) == 5 for values in samples.values()), samples
    assert all(len(values) == 2 for values in warmups.values()), warmups
    traces = {'baseline': [], 'candidate': []}
    for path in sorted((session / 'native').rglob('build-MEASURE-*.log')):
        label = 'baseline' if BASE in str(path) else 'candidate'
        hit = '> Task :compileJava FROM-CACHE' in path.read_text().splitlines()
        assert hit, path
        traces[label].append(str(path.relative_to(session)))
    if require_traces:
        assert all(len(paths) == 5 for paths in traces.values()), traces
    medians = {label: statistics.median(values) for label, values in samples.items()}
    return {'session': session.name, 'source_csv': str(sources[0].relative_to(session)),
            'tools': tools, 'measured_seconds': samples, 'warmup_seconds': warmups,
            'baseline_median_seconds': medians['baseline'],
            'candidate_median_seconds': medians['candidate'],
            'median_seconds_saved': medians['baseline'] - medians['candidate'],
            'median_reduction_percent': 100 * (medians['baseline'] - medians['candidate']) / medians['baseline'],
            'measured_compile_java_cache_hit_traces': traces,
            'cache_hit_trace_verified': all(len(paths) == 5 for paths in traces.values()),
            'order': 'candidate version block first, baseline version block second; not paired/interleaved',
            'samples_dropped': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--require-traces', action='store_true')
    args = parser.parse_args()
    sessions = [path for path in sorted(args.directory.glob('session-*'))
                if (path / 'native-run.json').is_file()]
    assert sessions, args.directory
    results = [analyze(path, args.require_traces) for path in sessions]
    output = {'exploratory_shared_runner_results': True, 'sessions': results,
              'uncertainty_note': 'Five observations per version in ordered blocks. Repetition across hosted VMs does not establish dedicated-machine stability or remove version-order effects.'}
    (args.directory / 'native-analysis.json').write_text(json.dumps(output, indent=2) + '\n')
    for result in results:
        print(json.dumps({key: result[key] for key in (
            'session', 'baseline_median_seconds', 'candidate_median_seconds',
            'median_seconds_saved', 'median_reduction_percent', 'cache_hit_trace_verified')}))


if __name__ == '__main__':
    main()
