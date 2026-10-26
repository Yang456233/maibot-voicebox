"""Build a source ZIP from a strict allowlist; never include local data or audio."""
from zipfile import ZipFile, ZIP_DEFLATED
from validate_release import ROOT, validate, release_files

manifest = validate()
out = ROOT / "dist" / f"maibot-voicebox-{manifest['version']}.zip"
out.parent.mkdir(exist_ok=True)
with ZipFile(out, "w", compression=ZIP_DEFLATED) as archive:
    for path in release_files():
        archive.write(path, path.relative_to(ROOT))
print(out)
