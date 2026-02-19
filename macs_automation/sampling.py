"""LHS (Latin Hypercube Sampling) module for probabilistic fire analysis.

Generates parameter samples using LHS with Gumbel and Lognormal inverse CDFs,
matching the approach used by the Fire Dynamics Group TMA script.
"""

import math
from typing import Optional

import numpy as np
from scipy.stats import gumbel_l, lognorm, qmc

from macs_automation.sweep import BEAM_SIDE_MAP, DEFAULTS, PARAM_ALIASES

# Occupancy fire load presets from EN 1991-1-2 Table E.4
# Format: {name: {"type": distribution_type, "mean": value, "cov": value}}
FIRE_LOAD_PRESETS = {
    # Gumbel distributions
    "Dwelling":       {"type": "gumbel",    "mean": 780,  "cov": 0.3},
    "Hospital":       {"type": "gumbel",    "mean": 230,  "cov": 0.3},
    "Hotel room":     {"type": "gumbel",    "mean": 310,  "cov": 0.3},
    "Library":        {"type": "gumbel",    "mean": 1500, "cov": 0.3},
    "Office":         {"type": "gumbel",    "mean": 420,  "cov": 0.3},
    "School":         {"type": "gumbel",    "mean": 285,  "cov": 0.3},
    # Lognormal distributions
    "Fast food outlet":     {"type": "lognormal", "mean": 526,  "cov": 0.61},
    "Clothing store":       {"type": "lognormal", "mean": 393,  "cov": 0.42},
    "Restaurant":           {"type": "lognormal", "mean": 298,  "cov": 0.64},
    "Kitchen":              {"type": "lognormal", "mean": 314,  "cov": 0.51},
    "Retail unit storage area": {"type": "lognormal", "mean": 1196, "cov": 1.01},
    "Manufacturing and storage of combustible goods (<150 kg/m2)":
                            {"type": "lognormal", "mean": 1180, "cov": 0.73},
    "Manufacturing and storage of combustible goods (>150 kg/m2)":
                            {"type": "lognormal", "mean": 9920, "cov": 0.86},
    # Opening Factor
    "Opening Factor":       {"type": "lognormal", "mean": 0.2,  "cov": 1.0},
}


def gumbel_ppf(u: np.ndarray, mean: float, cov: float) -> np.ndarray:
    """Inverse CDF for Gumbel (type I minimum) distribution.

    Matches TMA script: scale = std*sqrt(6)/pi, loc = mean + euler_gamma*scale.
    """
    std = mean * cov
    scale = std * math.sqrt(6) / math.pi
    loc = mean + np.euler_gamma * scale
    return gumbel_l.ppf(u, loc, scale)


def lognormal_ppf(u: np.ndarray, mean: float, cov: float) -> np.ndarray:
    """Inverse CDF for Lognormal distribution.

    Matches TMA script: sln = sqrt(log(1+cov^2)), mln = log(mean) - 0.5*sln^2.
    """
    sln = np.sqrt(np.log(1 + cov**2))
    mln = np.log(mean) - 0.5 * sln**2
    return lognorm.ppf(u, sln, 0, np.exp(mln))


def opening_factor_transform(values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Transform raw opening factor samples to MACS+ window percentage.

    Values > 1 are replaced with uniform(0, 1), then inverted (1 - x),
    then scaled to percentage (* 100).
    """
    result = values.copy()
    above_one = result > 1
    result[above_one] = rng.uniform(0, 1, size=above_one.sum())
    result = (1 - result) * 100
    return result


def resolve_distribution(spec: dict) -> dict:
    """Resolve a distribution spec — either explicit {type, mean, cov} or a preset reference."""
    if "preset" in spec:
        name = spec["preset"]
        if name not in FIRE_LOAD_PRESETS:
            raise ValueError(f"Unknown preset: '{name}'. Available: {list(FIRE_LOAD_PRESETS.keys())}")
        return dict(FIRE_LOAD_PRESETS[name])
    # Explicit spec — validate required keys
    return {"type": spec["type"], "mean": spec["mean"], "cov": spec["cov"]}


def generate_lhs_samples(config: dict) -> list[dict]:
    """Generate LHS parameter samples from config.

    Reads n_samples, seed, distributions from config. Builds base params
    from DEFAULTS + fixed + beams, then overlays sampled distribution values.
    """
    n_samples = config["n_samples"]
    seed = config.get("seed")

    distributions = config.get("distributions", {})
    dist_specs = {}
    for param_name, spec in distributions.items():
        dist_specs[param_name] = {
            "resolved": resolve_distribution(spec),
            "transform": spec.get("transform"),
        }

    n_dims = len(dist_specs)
    if n_dims == 0:
        n_dims = 1  # qmc requires at least 1 dimension

    # Generate LHS samples in [0, 1]^d
    sampler = qmc.LatinHypercube(d=n_dims, seed=seed)
    lhs_raw = sampler.random(n=n_samples)

    # RNG for opening factor transform
    rng = np.random.default_rng(seed)

    # Transform each column through the appropriate inverse CDF
    transformed = {}
    for i, (param_name, spec_info) in enumerate(dist_specs.items()):
        resolved = spec_info["resolved"]
        col = lhs_raw[:, i]

        if resolved["type"] == "gumbel":
            values = gumbel_ppf(col, resolved["mean"], resolved["cov"])
        elif resolved["type"] == "lognormal":
            values = lognormal_ppf(col, resolved["mean"], resolved["cov"])
        else:
            raise ValueError(f"Unknown distribution type: {resolved['type']}")

        if spec_info["transform"] == "opening_factor":
            values = opening_factor_transform(values, rng)

        transformed[param_name] = values

    # Build base params from DEFAULTS + fixed + beams (same logic as sweep.py)
    base = dict(DEFAULTS)

    method = config.get("analysis_method", "iso")
    method_map = {"parametric": "parametric", "iso": "iso", "udf": "udf"}
    base["method"] = method_map.get(method, method)

    fixed = config.get("fixed", {})
    for key, value in fixed.items():
        internal_key = PARAM_ALIASES.get(key, key)
        base[internal_key] = value

    beams = config.get("beams", {})
    for side, cfg in beams.items():
        if side in BEAM_SIDE_MAP:
            mapping = BEAM_SIDE_MAP[side]
            if "sec_size" in cfg:
                base[mapping["sec_size"]] = cfg["sec_size"]
            if "fy" in cfg:
                base[mapping["fy"]] = str(cfg["fy"])
            if "edge" in cfg:
                base[mapping["edge"]] = int(cfg["edge"])
            if "composite" in cfg:
                base[mapping["composite"]] = int(cfg["composite"])
            if "sh_con" in cfg:
                base[mapping["sh_con"]] = cfg["sh_con"]

    if "deck_id" in fixed:
        base["DeckId"] = fixed["deck_id"]

    # Build sample dicts
    samples = []
    for i in range(n_samples):
        params = dict(base)
        for param_name, values in transformed.items():
            params[param_name] = float(values[i])
        params["_sample_index"] = i
        params["_seed"] = seed
        samples.append(params)

    return samples
