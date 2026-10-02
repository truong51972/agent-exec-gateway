# Python Test

Run the narrowest relevant test target first, then broaden only when needed.

Typical command:

`uv run pytest <path-or-test>`

Do not modify dependencies merely to make a test pass unless the task explicitly calls for it.
