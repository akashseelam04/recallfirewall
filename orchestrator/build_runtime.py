"""Reproducible MIT-licensed RocketRide runtime bundle without adm-zip.

Input is the original sponsor SDK tarball. Omit its unused bundled CLI (which
provisions docs archives); replace app-pack ZIP creation with fflate. Cloud
client, account, tool, chat and deployment APIs retain their original code.
"""
import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    vendor = root / 'vendor'
    vendor.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        unpacked = Path(temporary)
        with tarfile.open(args.source) as archive:
            archive.extractall(unpacked, filter='data')
        package = unpacked / 'package'
        manifest_path = package / 'package.json'
        manifest = json.loads(manifest_path.read_text())
        assert manifest['name'] == 'rocketride' and manifest['version'] == '1.3.0'
        manifest['version'] = '1.3.0-rf.1'
        manifest['dependencies'].pop('adm-zip')
        manifest['dependencies']['fflate'] = '0.8.3'
        manifest.pop('bin', None)
        manifest.get('devDependencies', {}).pop('@types/adm-zip', None)
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        shutil.rmtree(package / 'dist/cli')
        for kind in ['esm', 'cjs']:
            path = package / 'dist' / kind / 'app-pack/index.js'
            text = path.read_text()
            old_import = "import AdmZip from 'adm-zip';" if kind == 'esm' else 'const adm_zip_1 = __importDefault(require("adm-zip"));'
            new_import = "import { zipSync } from 'fflate';" if kind == 'esm' else 'const { zipSync } = require("fflate");'
            constructor = 'const zip = new AdmZip();' if kind == 'esm' else 'const zip = new adm_zip_1.default();'
            replacements = [(old_import, new_import), (constructor, 'const zip = Object.create(null);'),
                            ('zip.addFile(file.zipPath, bytes);', 'zip[file.zipPath] = new Uint8Array(bytes);'),
                            ('const buffer = zip.toBuffer();', 'const buffer = Buffer.from(zipSync(zip));')]
            for old, new in replacements:
                assert text.count(old) == 1, 'Sponsor bundle changed; inspect before patching'
                text = text.replace(old, new)
            text = text.replace('adm-zip/ignore', 'fflate/ignore').replace('//# sourceMappingURL=index.js.map', '')
            path.write_text(text)
            path.with_suffix('.js.map').unlink(missing_ok=True)
        output = vendor / 'rocketride-1.3.0-rf.1.tgz'
        with tarfile.open(output, 'w:gz') as archive:
            archive.add(package, arcname='package')
        (vendor / 'provenance.json').write_text(json.dumps({
            'upstream_version': '1.3.0', 'runtime_version': manifest['version'],
            'upstream_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
            'runtime_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'changes': ['Remove unused bundled CLI and its docs extraction code',
                        'Use fflate 0.8.3 for app-pack ZIP creation; no archive extraction API']
        }, indent=2) + '\n')
        print('Built runtime bundle without adm-zip; Cloud API implementation preserved.')


if __name__ == '__main__':
    main()
