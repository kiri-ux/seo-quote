# Tests

These live inside the source tree on purpose. They used to sit beside it in a
scratch directory and were lost when that machine was recycled — 54 Python and
15 browser tests, none of them in any zip that had been handed over. Anything
worth keeping ships with the thing it tests.

## Running

The one command:

    tests/run.sh            # everything, ~80 tests
    tests/run.sh py         # Python only, no servers, ~20s
    tests/run.sh js         # browser only
    tests/run.sh tests/runs_test.js   # one file

It starts both servers fresh, runs, and tears them down, so a stale server
cannot fail a test against code that is fine.

## By hand

Python -- each file is a standalone script, not a pytest suite. Use
`python3.12` explicitly: on the web container the bare `pip` and `python3`
are 3.11, so a plain `pip install` succeeds and the tests still see nothing.

    python3.12 tests/<name>_test.py

Browser tests need TWO servers, on different ports, and which one a test
wants is hardcoded in the file:

    python3.12 tests/serve.py &          # port 5199: the template, Jinja stripped
    PORT=5203 python3.12 app.py &        # port 5203: the real app
    node tests/<name>_test.js

Restart serve.py after every template edit -- it reads the template once at
import. If a restart seems to do nothing, an old process is still holding the
port: `allow_reuse_address` lets the new one bind silently and serve nothing,
so kill the old PID explicitly (`tests/run.sh` does this for you).

The browser tests require playwright-core by absolute path,
`/root/work/node_modules/playwright-core`, and launch the Chromium at
`/opt/pw-browsers/chromium`. On the web container the session-start hook in
`.claude/hooks/` installs both the Python deps and playwright-core.
