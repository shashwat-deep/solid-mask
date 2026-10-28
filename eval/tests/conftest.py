import functools, http.server, sys, threading
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the scripts in eval/ import each other by name


@pytest.fixture(scope='session')
def chromium():
    """Skips the test when Playwright has no Chromium to launch."""
    playwright = pytest.importorskip('playwright.sync_api')
    try:
        with playwright.sync_playwright() as pw:
            pw.chromium.launch().close()
    except playwright.Error as e:
        pytest.skip(f'no Chromium for Playwright (python -m playwright install --only-shell chromium): {e}')


@pytest.fixture
def site(tmp_path):
    """A local HTTP server for the folder tmp_path/site. Yields (base URL, folder, list of requested paths)."""
    folder, requested = tmp_path / 'site', []
    folder.mkdir()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            super().do_GET()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=folder))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}', folder, requested
    server.shutdown()
    server.server_close()
