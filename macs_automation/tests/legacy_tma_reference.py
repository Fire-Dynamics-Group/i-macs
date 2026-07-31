"""Frozen reference copy of the Fire Dynamics Group legacy TMA sampler.

Vendored from the Fire Dynamics Group Dropbox (retrieved 2026-07-28):

- ``05 R&D/06 KK/19. MACS automation Python code/macs_automation/exe_script.py``
  (modified 2025-11-17)
- ``05 R&D/06 KK/08. Monte Carlo TMA/Ian's MACS+ MC simulation/create_mc_variables.py``
  (modified 2024-12-19)
- ``05 R&D/06 KK/08. Monte Carlo TMA/Ian's MACS+ MC simulation/fire_load_density.csv``
  (modified 2024-10-24)

The sampling maths is identical in both scripts and is copied here line-for-line.
The only adaptation is ``read_fld_data``: the pandas CSV load is replaced with an
embedded verbatim copy of fire_load_density.csv, preserving the exact parsing
semantics — including the ``str.split(...)[0]`` truncation that makes the
``== "Gumbel type 1"`` comparison always False. Because of that, the legacy
scripts sampled EVERY occupancy from the lognormal branch; the Gumbel branch is
dead code. This is confirmed empirically: the team's 10,000-line
``fire_load_distr.txt`` (Office, labelled Gumbel 420/0.3) has skewness +0.918
and range 129–1209, matching lognormal(420, cov 0.3) with KS D=0.0001 —
gumbel_l would be skewed −1.14 with range −428–695.

DO NOT fix, tidy, or modernise anything in this file. Its purpose is to preserve
what the team's script actually did, bugs included, as a differential-test oracle.
"""

import csv
import io
import math

import numpy as np

FIRE_LOAD_DENSITY_CSV = """Occupancy,Distribution,Mean Fire Density,Coefficient of Variation
Dwelling,Gumbel type 1,780,0.3
Hospital,Gumbel type 1,230,0.3
Hotel room,Gumbel type 1,310,0.3
Library,Gumbel type 1,1500,0.3
Office,Gumbel type 1,420,0.3
School,Gumbel type 1,285,0.3
Fast food outlet,Log-normal,526,0.61
Clothing store,Log-normal,393,0.42
Restaurant,Log-normal,298,0.64
Kitchen,Log-normal,314,0.51
Retail unit storage area,Log-normal,1196,1.01
Manufacturing and storage of combustible goods (<150 kg/m2),Log-normal,1180,0.73
Manufacturing and storage of combustible goods (>150 kg/m2),Log-normal,9920,0.86
Opening Factor, Log-normal, 0.2, 1
"""


def read_fld_data(occupancy):
    """Legacy CSV lookup. ``str.split`` (whitespace split) truncates the
    distribution label: "Gumbel type 1" -> "Gumbel", " Log-normal" -> "Log-normal".
    """
    rows = list(csv.DictReader(io.StringIO(FIRE_LOAD_DENSITY_CSV)))
    row = next(r for r in rows if r["Occupancy"] == occupancy)
    distr_type = str.split(row["Distribution"])[0]
    mean = float(row["Mean Fire Density"])
    cov = float(row["Coefficient of Variation"])
    std_dev = mean * cov
    return distr_type, mean, std_dev


def factorise_opening_percentage(distr):
    # replace the value above 1 to a value between 0 to 1
    count_above_1 = len(distr[distr > 1])
    distr[distr > 1] = np.random.uniform(0, 1, size=count_above_1)
    # below is to get an array with 1 - distribution
    one_minus_dist = 1 - distr
    return one_minus_dist


def get_distribution(dist, occupancy):
    """Verbatim legacy dispatch. The Gumbel comparison can never be True
    because read_fld_data returns the truncated label "Gumbel".
    """
    distr_type, mean, std_dev = read_fld_data(occupancy)
    if distr_type == "Gumbel type 1":
        dist_scale = std_dev * math.sqrt(6) / math.pi
        dist_loc = mean + np.euler_gamma * dist_scale
        from scipy.stats import gumbel_l
        return gumbel_l.ppf(dist, dist_loc, dist_scale)
    else:  # log-normal distribution
        cov = std_dev / mean   # coefficient of variation
        sln = np.sqrt(np.log(1 + cov ** 2))  # std deviation value in log normal
        mln = np.log(mean) - 1 / 2 * sln ** 2  # mean value in log normal
        from scipy.stats import lognorm
        return lognorm.ppf(dist, sln, 0, np.exp(mln))


# Standalone copies of the two get_distribution branches, so tests can compare
# formulas independently of the (buggy) dispatch above.

def legacy_gumbel_formula(dist, mean, std_dev):
    dist_scale = std_dev * math.sqrt(6) / math.pi
    dist_loc = mean + np.euler_gamma * dist_scale
    from scipy.stats import gumbel_l
    return gumbel_l.ppf(dist, dist_loc, dist_scale)


def legacy_lognormal_formula(dist, mean, std_dev):
    cov = std_dev / mean
    sln = np.sqrt(np.log(1 + cov ** 2))
    mln = np.log(mean) - 1 / 2 * sln ** 2
    from scipy.stats import lognorm
    return lognorm.ppf(dist, sln, 0, np.exp(mln))
