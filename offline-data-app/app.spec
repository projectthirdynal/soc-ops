# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SOC Data Processor — onedir mode, Windows-safe."""

import sys
from pathlib import Path

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app/ui', 'app/ui'),
        ('version.json', '.'),
    ],
    hiddenimports=[
        # uvicorn internals
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # fastapi / starlette
        'fastapi',
        'starlette',
        'starlette.routing',
        'starlette.responses',
        'starlette.staticfiles',
        'starlette.middleware',
        'starlette.middleware.cors',
        'multipart',
        # anyio
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        # data
        'duckdb',
        'polars',
        'openpyxl',
        'fastexcel',
        # scikit-learn
        'sklearn',
        'sklearn.cluster',
        'sklearn.cluster._kmeans',
        'sklearn.cluster._birch',
        'sklearn.preprocessing',
        'sklearn.preprocessing._data',
        'sklearn.metrics',
        'sklearn.metrics.cluster',
        'sklearn.utils._cython_blas',
        'sklearn.neighbors._typedefs',
        'sklearn.neighbors._partition_nodes',
        'sklearn.tree._utils',
        'numpy',
        'numpy.core',
        # pywebview — Windows backends
        'webview',
        'webview.platforms',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'clr',
        # misc
        'platformdirs',
        'multiprocessing',
        # app modules
        'app',
        'app.api',
        'app.api.routes',
        'app.api.routes.upload',
        'app.api.routes.split',
        'app.api.routes.aggregate',
        'app.api.routes.cluster',
        'app.api.routes.dashboard',
        'app.api.routes.search',
        'app.core',
        'app.core.config',
        'app.core.database',
        'app.core.splitter',
        'app.core.aggregator',
        'app.core.clusterer',
        'app.core.version',
        'app.core.updater',
        'app.core.logging_config',
        'app.api.routes.update',
        'app.api.ops_lock',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OfflineDataApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,        # Disabled — UPX triggers Windows Defender and can corrupt DLLs
    console=False,    # Hide console window for production
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='OfflineDataApp',
)
