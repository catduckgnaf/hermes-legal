# Getting started

1. Install Python 3.12 and uv.
2. Clone this repository and run `uv sync`.
3. Run `uv run legal doctor` — it works offline and names anything missing.
4. Run `uv run legal demo`, then `uv run legal matter list`.
5. Open a real folder as a matter only when you are ready; the demo matter is fictional.

Access is **this computer only** by default: the app binds loopback and refuses to start on a non-loopback address until you choose a protected access mode in Settings. That fail-closed start is deliberate.
