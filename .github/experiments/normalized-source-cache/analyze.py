#!/usr/bin/env python3
"""Describe paired measurements without dropping slow samples."""

import argparse
import json
from pathlib import Path
import random
import statistics


def quantile(values, fraction):
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def describe(pairs, metric):
    valid = [(pair['baseline'].get(metric), pair['candidate'].get(metric)) for pair in pairs]
    valid = [(baseline, candidate) for baseline, candidate in valid if baseline is not None and candidate is not None]
    if not valid:
        return None
    differences = [baseline - candidate for baseline, candidate in valid]
    generator = random.Random(0)
    bootstrap = [statistics.median(generator.choices(differences, k=len(differences))) for _ in range(10000)]
    percentages = [100 * (baseline - candidate) / baseline for baseline, candidate in valid if baseline > 0]
    return {'pairs': len(valid), 'baseline_median': statistics.median(a for a, _ in valid),
            'candidate_median': statistics.median(b for _, b in valid),
            'paired_median_difference': statistics.median(differences),
            'paired_median_percent': statistics.median(percentages) if percentages else None,
            'paired_difference_range': [min(differences), max(differences)],
            'bootstrap_percentile_95_interval': [quantile(bootstrap, 0.025), quantile(bootstrap, 0.975)]}


def analyze(path):
    report = json.loads(path.read_text())
    grouped = {}
    for record in report['records']:
        if record.get('phase') == 'measure':
            grouped.setdefault(record['name'], {})[record['label']] = record
    pairs = list(grouped.values())
    assert len(pairs) == report['measured_pairs']
    for pair in pairs:
        assert set(pair) == {'baseline', 'candidate'}
        assert pair['baseline']['key'] == pair['candidate']['key']
        assert pair['baseline']['output'] == pair['candidate']['output']
    assert not report['smoke_only']
    assert report['runtimes']['baseline']['version'] == report['runtimes']['candidate']['version']
    assert report['runtimes']['baseline']['router_class_sha256'] != report['runtimes']['candidate']['router_class_sha256']
    return {'report': str(path), 'scenario': report['scenario'], 'task': report['task'],
            'files': report['files'], 'bytes_per_file': report['bytes_per_file'],
            'wall_seconds': describe(pairs, 'wallSeconds'),
            'input_snapshot_ms': describe(pairs, 'inputSnapshotMs'),
            'resource_cache_bytes': {label: [record['resourceCacheBytes'] for record in report['records']
                                            if record['label'] == label and 'resourceCacheBytes' in record]
                                     for label in ('baseline', 'candidate')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    results = [analyze(path) for path in sorted(args.directory.glob('session-*/results/*/report.json'))
               if path.parent.name != 'functional']
    document = {'exploratory_shared_runner_results': True,
                'positive_difference_means': 'candidate faster',
                'uncertainty_note': 'Intervals resample paired observations within one session. They do not establish dedicated-machine repeatability or independence across shared hosts.',
                'samples_dropped': 0, 'cases': results}
    target = args.directory / 'paired-analysis.json'
    target.write_text(json.dumps(document, indent=2) + '\n')
    for result in results:
        print(json.dumps({key: result[key] for key in ('scenario', 'task', 'files', 'wall_seconds', 'input_snapshot_ms')}))


if __name__ == '__main__':
    main()
