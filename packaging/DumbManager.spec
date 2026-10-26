# Build candidate, not a signed installer. Runtime files remain outside the bundle.
from pathlib import Path
ROOT=Path(SPECPATH).parent
datas=[(str(ROOT/'web'),'web')]
for name in ['social_gif.js','ascii_smoke.js','social_image.ps1']:
    datas.append((str(ROOT/'backend'/'dumbapi_core'/name),'dumbapi_core'))
a=Analysis([str(ROOT/'run.py')],pathex=[str(ROOT),str(ROOT/'backend')],
           binaries=[],datas=datas,hiddenimports=['native','app','tkinter','dumbapi_core.workspace',
           'dumbapi_core.bridge','dumbapi_core.discord_bridge','dumbapi_core.manager_posts'],
           hookspath=[],hooksconfig={},runtime_hooks=[],excludes=[],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='DumbManager',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=True,
        disable_windowed_traceback=False)
