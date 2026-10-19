"""Ограниченная раздача заранее собранного локального dashboard."""

import re
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

ASSET = re.compile(r"assets/[A-Za-z0-9_-]+\.(?:js|css|svg|png|jpg|webp|woff2)")
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


class LocalDashboard(StaticFiles):
    def __init__(self, directory: str):
        root = Path(directory).absolute()
        error = "WEB_DIST_PATH: нужен отдельный проверенный каталог Web dist"
        if root.resolve() != root or not root.is_dir():
            raise ValueError(error)
        files = set()
        total = 0
        for count, path in enumerate(root.rglob("*"), 1):
            if count > 512 or path.is_symlink():
                raise ValueError(error)
            name = path.relative_to(root).as_posix()
            if path.is_dir():
                if name != "assets":
                    raise ValueError(error)
                continue
            if not path.is_file() or not (
                name in {"index.html", "shade.svg"} or ASSET.fullmatch(name)
            ):
                raise ValueError(error)
            total += path.stat().st_size
            if total > 32 * 1024**2:
                raise ValueError(error)
            files.add(name)
        if "index.html" not in files or not any(f.startswith("assets/") for f in files):
            raise ValueError(error)
        self.root = root
        self.files = frozenset(files)
        super().__init__(directory=root, html=False, follow_symlink=False)

    async def get_response(self, path, scope):
        name = "index.html" if path in {".", ""} else path
        if name not in self.files:
            raise HTTPException(404)
        # dist должен быть read-only. Дополнительно запрещаем подмену symlink после старта.
        target = self.root / name
        if target.resolve() != target or not target.is_file():
            raise HTTPException(404)
        response = await super().get_response(name, scope)
        response.headers.update(
            {
                "Content-Security-Policy": CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-cache",
            }
        )
        if name.startswith("assets/") and re.search(r"-[A-Za-z0-9_-]{8,}\.", name):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
