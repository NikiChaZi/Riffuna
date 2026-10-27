"""Numerical user-tower inference shared by the local engine and evaluation."""
import numpy as np


def query(profile, weights):
    hidden = profile @ weights["layers.0.weight"].T + weights["layers.0.bias"]
    hidden = (hidden - hidden.mean()) / np.sqrt(hidden.var() + 1e-5)
    hidden = hidden * weights["layers.1.weight"] + weights["layers.1.bias"]
    embedding = np.maximum(hidden, 0) @ weights["layers.3.weight"].T + weights["layers.3.bias"]
    return embedding / max(float(np.linalg.norm(embedding)), 1e-8)
