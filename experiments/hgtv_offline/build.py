"""Build the pinned signer/parser subset. Only dependency download uses network."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / '.build'
DEPS = ROOT / '.deps'
ARTIFACTS = [
    ('org.jetbrains.kotlin', 'kotlin-compiler-embeddable', '2.1.20'),
    ('org.jetbrains.kotlin', 'kotlin-stdlib', '2.1.20'),
    ('org.jetbrains.kotlin', 'kotlin-script-runtime', '2.1.20'),
    ('org.jetbrains.kotlin', 'kotlin-reflect', '1.6.10'),
    ('org.jetbrains.kotlin', 'kotlin-daemon-embeddable', '2.1.20'),
    ('org.jetbrains.intellij.deps', 'trove4j', '1.0.20200330'),
    ('org.jetbrains.kotlinx', 'kotlinx-coroutines-core-jvm', '1.8.0'),
    ('org.jetbrains', 'annotations', '13.0'),
    ('org.bouncycastle', 'bcprov-jdk18on', '1.79'),
    ('org.json', 'json', '20240303'),
    ('junit', 'junit', '4.13.2'),
    ('org.hamcrest', 'hamcrest-core', '1.3'),
]
RUNTIME = {'kotlin-stdlib', 'annotations', 'bcprov-jdk18on', 'json', 'junit', 'hamcrest-core'}


def jar(group, artifact, version):
    return DEPS / f'{artifact}-{version}.jar'


def classpath(runtime=False):
    return os.pathsep.join(str(jar(*a)) for a in ARTIFACTS if not runtime or a[1] in RUNTIME)


def java_env():
    return {k: v for k, v in os.environ.items()
            if k not in {'JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS'}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--offline', action='store_true', help='Require all pinned jars locally')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'upstream.json').read_text())
    for entry in manifest['files']:
        data = (ROOT / entry['path']).read_bytes()
        digest = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
        if digest != entry['git_blob_sha']:
            raise ValueError(f"Upstream source differs: {entry['path']}")
    DEPS.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)
    lock_path = ROOT / 'dependencies.lock.json'
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    for group, artifact, version in ARTIFACTS:
        path = jar(group, artifact, version)
        url = f'https://repo.maven.apache.org/maven2/{group.replace(".", "/")}/{artifact}/{version}/{path.name}'
        if not path.exists():
            if args.offline:
                raise FileNotFoundError(f'Missing cached dependency: {path.name}')
            print(f'Downloading {path.name}', flush=True)
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
            with urllib.request.urlopen(url + '.sha1', timeout=20) as response:
                expected = response.read().decode().split()[0].lower()
            if hashlib.sha1(data).hexdigest() != expected:
                raise ValueError(f'Maven checksum mismatch: {path.name}')
            path.write_bytes(data)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name in lock and lock[path.name]['sha256'] != digest:
            raise ValueError(f'Pinned checksum mismatch: {path.name}')
        if args.offline and path.name not in lock:
            raise ValueError(f'Dependency is not pinned: {path.name}')
        lock[path.name] = {'url': url, 'sha256': digest}
    lock_path.write_text(json.dumps(lock, indent=2) + '\n')
    sources = sorted(str(p) for p in (ROOT / 'vendor').glob('*.kt')) + [str(ROOT / 'Bridge.kt')]
    subprocess.run(['java', '-cp', classpath(), 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                    '-no-stdlib', '-no-reflect', '-jvm-target', '17', '-classpath', classpath(True),
                    '-d', str(BUILD / 'classes'), *sources], check=True, env=java_env())
    subprocess.run(['javac', '--release', '17', '-cp', classpath(True), '-d', str(BUILD / 'classes'),
                    str(ROOT / 'OfflineLauncher.java')], check=True, env=java_env())
    (BUILD / 'classes' / 'signing.json').write_bytes((ROOT / 'vendor' / 'signing.json').read_bytes())
    print('Built unchanged upstream signer/parser and tests; JVM target 17. No Android SDK or HTTP transport.')


if __name__ == '__main__':
    main()
