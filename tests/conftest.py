import os

# Existing Qt fallback regression tests; native tests explicitly opt in.
os.environ.setdefault("RIFFUNA_AUDIO_BACKEND", "qt")
