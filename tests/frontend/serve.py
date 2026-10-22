"""Serve only synthetic UI fixtures and frontend assets on loopback."""

from pathlib import Path

from aiohttp import web

FIXTURES = Path(__file__).parent
ASSETS = FIXTURES.parents[1] / "custom_components" / "casambi_bt" / "frontend"


async def fixture(request: web.Request) -> web.Response:
    """Serve the two explicit fixture files, never the repository directory."""
    filename = "harness.js" if request.path == "/harness.js" else "harness.html"
    return web.Response(body=(FIXTURES / filename).read_bytes(), content_type="text/javascript" if filename.endswith(".js") else "text/html")


if __name__ == "__main__":
    app = web.Application()
    app.router.add_get("/", fixture)
    app.router.add_get("/harness.js", fixture)
    app.router.add_static("/assets", ASSETS)
    web.run_app(app, host="127.0.0.1", port=8887, access_log=None)
