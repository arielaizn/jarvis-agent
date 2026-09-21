"""Export only the shared, licensed avatar geometry; never user camera data."""
import json
from pathlib import Path
from core.avatar_mesh import get_head_mesh
mesh=get_head_mesh()
def plain(value):
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    if hasattr(value,'tolist'):return value.tolist()
    return value
Path('viewer/presence-mesh.js').write_text('// MediaPipe canonical geometry, Apache-2.0; see THIRD_PARTY.md.\nexport const HEAD='+json.dumps(plain(mesh),separators=(',',':'))+';\n')
