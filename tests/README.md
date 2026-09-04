# Tests

These live inside the source tree on purpose. They used to sit beside it in a
scratch directory and were lost when that machine was recycled — 54 Python and
15 browser tests, none of them in any zip that had been handed over. Anything
worth keeping ships with the thing it tests.

## Running

Python — each file is a standalone script, not a pytest suite:

    python3.12 tests/<name>_test.py

Browser tests need a page to load. Serve the template with the Jinja tags
stripped, then run the file:

    python3.12 tests/serve.py &          # port 5199
    node tests/<name>_test.js

Restart the server after every template edit — it reads index.html once at
import. If a restart seems to do nothing, an old process is still holding the
port: `allow_reuse_address` lets the new one bind silently and serve nothing,
so kill the old PID explicitly.
