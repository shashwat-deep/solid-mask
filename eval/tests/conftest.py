import functools, http.server, sys, threading
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the scripts in eval/ import each other by name


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
