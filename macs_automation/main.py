"""MACS+ Batch Automation Tool — CLI entry point."""

import argparse
from pathlib import Path

from tqdm import tqdm

from macs_automation.data_loader import load_data
from macs_automation.db import ResultsDB
from macs_automation.runner import run_batch_with_callback
from macs_automation.sweep import generate_combinations, load_config, resolve_deck, resolve_mesh, resolve_slab_weight


def list_sections(data: dict):
    """Print all available steel sections."""
    sections = data["sections"]
    families = {}
    for sec_id, sec in sections.items():
        fam = sec["family"]
        if fam not in families:
            families[fam] = []
        families[fam].append((sec_id, sec["name"], sec["h"], sec["b"]))

    for fam in sorted(families.keys()):
        print(f"\n{'='*60}")
        print(f"  {fam} Sections ({len(families[fam])} total)")
        print(f"{'='*60}")
        print(f"  {'ID':<25} {'Name':<25} {'h(mm)':<8} {'b(mm)':<8}")
        print(f"  {'-'*25} {'-'*25} {'-'*8} {'-'*8}")
        for sec_id, name, h, b in families[fam]:
            print(f"  {sec_id:<25} {name:<25} {h:<8.1f} {b:<8.1f}")


def list_decks(data: dict):
    """Print all available deck types."""
    decks = data["decks"]
    print(f"\n{'='*80}")
    print(f"  Available Deck Types ({len(decks)} total)")
    print(f"{'='*80}")
    print(f"  {'ID':<8} {'Name':<25} {'Type':<6} {'Depth':<8} {'Pitch':<8} {'Top':<8} {'Bot':<8}")
    print(f"  {'-'*8} {'-'*25} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for deck_id, deck in sorted(decks.items()):
        print(f"  {deck_id:<8} {deck['name']:<25} {deck['deck_type']:<6} "
              f"{deck['deck_depth']:<8.1f} {deck['deck_trug']:<8.1f} "
              f"{deck['deck_top']:<8.1f} {deck['deck_bot']:<8.1f}")


def list_meshes(data: dict):
    """Print all available mesh types."""
    meshes = data["meshes"]
    print(f"\n{'='*70}")
    print(f"  Available Mesh Types ({len(meshes)} total)")
    print(f"{'='*70}")
    print(f"  {'ID':<10} {'Name':<15} {'Main(mm²/m)':<14} {'Trans(mm²/m)':<14} {'Dia(mm)':<10}")
    print(f"  {'-'*10} {'-'*15} {'-'*14} {'-'*14} {'-'*10}")
    for mesh_id, mesh in sorted(meshes.items()):
        dia = f"{mesh['min_mesh_dia']}-{mesh['max_mesh_dia']}"
        print(f"  {mesh_id:<10} {mesh['name']:<15} {mesh['mainArea']:<14.0f} "
              f"{mesh['transArea']:<14.0f} {dia:<10}")


def run_batch(config_path: str, db_path: str, resume: bool = True):
    """Run a batch of MACS+ calculations from a sweep config."""
    print("Loading reference data...")
    data = load_data()

    print(f"Loading config: {config_path}")
    config = load_config(config_path)

    print("Generating parameter combinations...")
    sampling_mode = config.get("sampling", "grid")
    if sampling_mode == "lhs":
        n_samples = config.get("n_samples", "?")
        seed = config.get("seed", "none")
        print(f"Sampling mode: LHS (n_samples={n_samples}, seed={seed})")
    else:
        print("Sampling mode: grid")

    combinations = generate_combinations(config)

    # Resolve deck and mesh lookups for each combination, then recompute the
    # slab weight from the resolved geometry (mirrors MACS+'s auto-calc)
    for params in combinations:
        resolve_deck(params, data["decks"])
        resolve_mesh(params, data["meshes"])
        resolve_slab_weight(params)

    print(f"Total combinations: {len(combinations)}")

    db = ResultsDB(db_path)

    # Use tqdm as the callback for the batch runner
    remaining = len(combinations)
    if resume:
        skipped = sum(1 for p in combinations if db.run_exists(p))
        remaining -= skipped
        if skipped:
            print(f"Resuming: skipping {skipped} already-completed runs")

    print(f"Runs to execute: {remaining}")

    if remaining == 0:
        print("All runs already completed.")
        db.close()
        return

    pbar = tqdm(total=remaining, desc="Running MACS+", unit="run")

    def _on_run_complete(run_id, params, outputs, error, progress):
        pbar.update(1)
        if error:
            tqdm.write(f"  ERROR: {error}")

    result = run_batch_with_callback(
        combinations, db, data["sections"],
        resume=resume,
        on_run_complete=_on_run_complete,
    )

    pbar.close()
    db.close()

    success = result.completed - result.errors
    print(f"\nComplete: {success} succeeded, {result.errors} failed")
    print(f"Results stored in: {db_path}")


def main():
    parser = argparse.ArgumentParser(
        description="MACS+ Batch Automation Tool — Run parameter sweeps using the FRACOF COM engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", type=str, help="Path to sweep configuration YAML file")
    parser.add_argument("--db", type=str, default="results.db", help="Path to SQLite results database")
    parser.add_argument("--no-resume", action="store_true", help="Don't skip already-completed runs")
    parser.add_argument("--list-sections", action="store_true", help="List all available steel sections")
    parser.add_argument("--list-decks", action="store_true", help="List all available deck types")
    parser.add_argument("--list-meshes", action="store_true", help="List all available mesh types")
    parser.add_argument("--data-path", type=str, help="Override path to Data.xml")

    args = parser.parse_args()

    # List commands don't need a config
    if args.list_sections or args.list_decks or args.list_meshes:
        data_path = Path(args.data_path) if args.data_path else None
        data = load_data(data_path)
        if args.list_sections:
            list_sections(data)
        if args.list_decks:
            list_decks(data)
        if args.list_meshes:
            list_meshes(data)
        return

    # Batch run requires config
    if not args.config:
        parser.error("--config is required for batch runs")

    run_batch(args.config, args.db, resume=not args.no_resume)


if __name__ == "__main__":
    main()
