"""Offline Python ↔ JVM bridge. Does not import or open the crawler's database."""
import argparse
import json
import os
import subprocess
import sys
from build import ROOT, BUILD, classpath, java_env


def run_jvm(mode, payload=None):
    if not (BUILD / 'classes' / 'OfflineLauncher.class').is_file():
        raise RuntimeError('Build first: python3 experiments/hgtv_offline/build.py')
    command = ['java', '-Djava.security.manager=allow', '-cp',
               str(BUILD / 'classes') + os.pathsep + classpath(True), 'OfflineLauncher', mode]
    result = subprocess.run(command, input=json.dumps(payload, ensure_ascii=False) if payload is not None else '',
                            capture_output=True, text=True, encoding='utf-8', timeout=60,
                            cwd=ROOT, env=java_env())
    if result.returncode:
        raise RuntimeError(f'Offline JVM failed ({result.returncode}): {result.stderr[-3000:]}\n{result.stdout[-1000:]}')
    return result.stdout


def parse_rows(rows):
    """Return upstream parsing plus original fields; this does not establish data provenance."""
    if not isinstance(rows, list):
        raise ValueError('rows must be a JSON array')
    return json.loads(run_jvm('bridge', {'operation': 'parse_rows', 'rows': rows}))


def verify_signing_fixtures():
    return json.loads(run_jvm('bridge', {'operation': 'verify_signing_fixtures'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['parse-rows', 'verify-signing', 'test', 'guard-check'])
    args = parser.parse_args()
    if args.operation == 'parse-rows':
        print(json.dumps(parse_rows(json.load(sys.stdin)), ensure_ascii=False, indent=2))
    elif args.operation == 'verify-signing':
        print(json.dumps(verify_signing_fixtures(), indent=2))
    else:
        print(run_jvm(args.operation), end='')
