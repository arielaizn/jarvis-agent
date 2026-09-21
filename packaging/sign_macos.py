"""Seal versioned Qt frameworks inside out, then verify the complete app."""
from pathlib import Path
import subprocess


def sign(app):
    app=Path(app).resolve()
    # Contents/Resources/PySide6/Qt/lib points to this same directory. Sign once.
    frameworks=app/'Contents/Frameworks/PySide6/Qt/lib'
    for framework in sorted(frameworks.glob('*.framework')):
        version=framework/'Versions/A'
        if not version.exists():continue
        for helper in sorted(version.glob('Helpers/*.app')):
            subprocess.run(['codesign','--force','--sign','-',str(helper)],check=True)
        subprocess.run(['codesign','--force','--sign','-',str(version)],check=True)
    subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
