#!/usr/bin/env python3
"""Recover checksummed experiment evidence from completed GitHub job logs."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--job-id')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    repo = 'manasjoshi14/gradle'
    metadata = json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{repo}/actions/runs/{args.run_id}'], text=True))
    (args.output / 'workflow-run.json').write_text(json.dumps(metadata, indent=2) + '\n')
    if args.job_id:
        job = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/actions/jobs/{args.job_id}'], text=True))
        assert job['status'] == 'completed', job['status']
        assert str(job['run_id']) == args.run_id
        (args.output / ('job-' + args.job_id + '.json')).write_text(json.dumps(job, indent=2) + '\n')
        raw = subprocess.check_output(['gh', 'api', f'repos/{repo}/actions/jobs/{args.job_id}/logs'])
        (args.output / ('job-' + args.job_id + '.log')).write_bytes(raw)
        documents = [('job-' + args.job_id, raw)]
    else:
        assert metadata['status'] == 'completed', metadata['status']
        raw = subprocess.check_output(['gh', 'api', f'repos/{repo}/actions/runs/{args.run_id}/logs'])
        (args.output / 'github-logs.zip').write_bytes(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as logs:
            documents = [(name, logs.read(name)) for name in logs.namelist()]
    seen = set()
    for name, document in documents:
        content = document.decode(errors='replace')
        if 'EXPERIMENT_EVIDENCE_BEGIN' not in content:
            continue
        digest = re.search(r'EXPERIMENT_EVIDENCE_BEGIN ([0-9a-f]{64})', content)
        if not digest or digest[1] in seen:
            continue
        chunks = re.findall(r'EXPERIMENT_EVIDENCE_CHUNK ([A-Za-z0-9+/=]+)', content)
        data = base64.b64decode(''.join(chunks))
        assert hashlib.sha256(data).hexdigest() == digest[1], name
        with zipfile.ZipFile(io.BytesIO(data)) as evidence:
            assert evidence.testzip() is None
            if 'provenance.json' in evidence.namelist():
                provenance = json.loads(evidence.read('provenance.json'))
                session = provenance['session']
            else:
                session = 'setup-failure-' + str(len(seen) + 1)
            assert re.fullmatch(r'[A-Za-z0-9_-]+', str(session)), session
            destination = args.output / ('session-' + str(session))
            destination.mkdir(exist_ok=True)
            for entry in evidence.namelist():
                path = Path(entry)
                assert not path.is_absolute() and '..' not in path.parts, entry
            evidence.extractall(destination)
            (destination / 'evidence.zip').write_bytes(data)
            (destination / 'evidence-sha256.txt').write_text(digest[1] + '\n')
            print(json.dumps({'session': session, 'files': len(evidence.namelist()),
                              'bytes': len(data), 'evidence_sha256': digest[1]}))
        seen.add(digest[1])
    print(json.dumps({'run_id': args.run_id, 'conclusion': metadata['conclusion'],
                      'evidence_bundles': len(seen)}))


if __name__ == '__main__':
    main()
