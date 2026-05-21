# Archived: cartesian "grid" sweep mode

The cartesian-product sweep arm (`itertools.product`) was removed in #36 in
favour of paired (row-aligned) iteration as the default. LHS sampling stays
untouched. This doc preserves the removed code for reference — restore from
here if you ever need to resurrect grid mode.

## Original `generate_combinations` grid arm (`macs_automation/sweep.py`)

```python
# Generate sweep combinations
sweep = config.get("sweep", {})
if not sweep:
    return [base]

# Normalize keys and ensure all values are lists
sweep_keys = []
sweep_values = []
for key, values in sweep.items():
    internal_key = PARAM_ALIASES.get(key, key)
    sweep_keys.append(internal_key)
    if not isinstance(values, list):
        values = [values]
    sweep_values.append(values)

combinations = []
for combo in itertools.product(*sweep_values):
    params = dict(base)
    for key, val in zip(sweep_keys, combo):
        params[key] = val
    combinations.append(params)

return combinations
```

## Original cartesian total-combinations math (`src/sweep/buildSweepPayload.ts`)

```typescript
const totalCombinations = Object.values(sweep).reduce(
  (acc, vals) => acc * vals.length,
  Object.keys(sweep).length === 0 ? 0 : 1,
);
```

## Removed grid-only tests (`macs_automation/tests/test_sweep.py`)

```python
def test_two_param_sweep(self):
    config = {
        "analysis_method": "iso",
        "sweep": {"span1": [6, 9], "span2": [6, 9]},
    }
    combos = generate_combinations(config)
    assert len(combos) == 4  # 2 x 2

def test_three_param_sweep(self):
    config = {
        "analysis_method": "iso",
        "sweep": {
            "span1": [6, 9, 12],
            "slab_depth": [130, 150],
            "fck": [25, 30],
        },
    }
    combos = generate_combinations(config)
    assert len(combos) == 12  # 3 x 2 x 2

def test_large_sweep(self):
    config = {
        "analysis_method": "iso",
        "sweep": {
            "span1": [6, 9, 12],
            "span2": [6, 9, 12],
            "slab_depth": [130, 150, 180],
            "fck": [25, 30, 40],
            "u_sec_size": ["IPE_300", "IPE_400", "IPE_500"],
            "time_limit": [60, 90, 120],
        },
    }
    combos = generate_combinations(config)
    assert len(combos) == 3 * 3 * 3 * 3 * 3 * 3  # 729

def test_grid_mode_default(self):
    config = {
        "analysis_method": "iso",
        "sweep": {"span1": [6, 9]},
    }
    combos = generate_combinations(config)
    assert len(combos) == 2
    assert "_sample_index" not in combos[0]

def test_grid_mode_explicit(self):
    config = {
        "analysis_method": "iso",
        "sampling": "grid",
        "sweep": {"span1": [6, 9]},
    }
    combos = generate_combinations(config)
    assert len(combos) == 2
    assert "_sample_index" not in combos[0]

def test_sweep_qf_and_window_percent(self):
    config = {
        "analysis_method": "parametric",
        "sweep": {
            "qf": [300, 500, 700],
            "window_percent": [50, 80],
        },
        "fixed": {"span1": 9, "span2": 9},
    }
    combos = generate_combinations(config)
    assert len(combos) == 6  # 3 x 2
    ...

def test_sweep_loading_params(self):
    config = {
        "analysis_method": "iso",
        "sweep": {
            "lead_var_act": [3.0, 5.0, 7.5],
            "cold_perm": [0.5, 1.2],
        },
    }
    combos = generate_combinations(config)
    assert len(combos) == 6  # 3 x 2
    ...
```

## Rationale for removal

A 10000×10000 cartesian product silently projected to 100,000,000 runs and
OOM-crashed the sidecar. Paired (zip) iteration is the right primitive for
pre-sampled distributions (Monte Carlo with externally generated samples),
which is the dominant use case for this form. See #36 for the full decision
table and acceptance criteria.
