import os
import json
from pathlib import Path

import typer

try:
    import questionary  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    questionary = None

app = typer.Typer()

# ---------- CONFIG ---------
DEFAULT_PRESET = "python"
DEFAULT_VARIANT = "basic"
# Resolve presets relative to the project root:
#   <project_root>/presets/<language>/<variant>
PRESETS_ROOT = Path(__file__).resolve().parent.parent.parent / "presets"


# ---------- HELPER FUNCTIONS ----------
def list_presets() -> list[str]:
    """
    Return available presets in the form "<language>/<variant>".

    Example: "python/basic", "go/basic"
    """
    if not PRESETS_ROOT.exists():
        return []

    results: list[str] = []
    for language_dir in PRESETS_ROOT.iterdir():
        if not language_dir.is_dir():
            continue
        for variant_dir in language_dir.iterdir():
            if variant_dir.is_dir():
                results.append(f"{language_dir.name}/{variant_dir.name}")
    return sorted(results)


def _preset_index() -> dict[str, list[str]]:
    """
    Group presets by language: {language: [variant, ...]}.
    """
    index: dict[str, list[str]] = {}
    for entry in list_presets():
        lang, variant = entry.split("/", 1)
        index.setdefault(lang, []).append(variant)
    for lang in index:
        index[lang].sort()
    return index


def _lang_color(language: str):
    """
    Accent color per language, loosely matching typical logos/themes.
    """
    lang = language.lower()
    if lang == "python":
        return typer.colors.BLUE
    if lang == "go":
        return typer.colors.CYAN
    if lang in ("javascript", "node", "nodejs"):
        return typer.colors.YELLOW
    if lang in ("typescript", "ts"):
        return typer.colors.BRIGHT_BLUE if hasattr(typer.colors, "BRIGHT_BLUE") else typer.colors.BLUE
    if lang == "ruby":
        return typer.colors.RED
    return None


def _preset_meta_path(language: str, variant: str) -> Path:
    return PRESETS_ROOT / language / variant / "preset.json"


def _load_preset_meta(language: str, variant: str) -> dict:
    """
    Load optional metadata for a preset from preset.json.

    Supports keys:
      - name: human-friendly name
      - description: short description
      - tags: list of strings
      - next_steps: list of commands/messages shown after generation
    """
    path = _preset_meta_path(language, variant)
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(raw, dict):
        return {}
    # Ensure basic shapes
    if not isinstance(raw.get("tags", []), list):
        raw["tags"] = []
    if not isinstance(raw.get("next_steps", []), list):
        raw["next_steps"] = []
    return raw


def _render_template_file(src: Path, dst: Path, project_name: str) -> None:
    """
    Copy a file from preset to destination, performing simple {project_name} substitution.
    """
    text = src.read_text(encoding="utf-8")
    text = text.replace("{project_name}", project_name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")


def _planned_files(preset_path: Path, project_name: str, project_path: Path) -> list[Path]:
    """
    Return the list of files that would be created for this preset.
    """
    files: list[Path] = []
    for root, dirs, filenames in os.walk(preset_path):
        rel_root = Path(root).relative_to(preset_path)
        rendered_rel_root = Path(
            str(rel_root).replace("{project_name}", project_name)
        ) if rel_root != Path(".") else Path("")
        target_root = project_path / rendered_rel_root

        for f in filenames:
            rendered_name = f.replace("{project_name}", project_name)
            files.append(target_root / rendered_name)
    return sorted(files)


def _copy_preset_tree(preset_path: Path, project_path: Path, project_name: str) -> None:
    """
    Recursively copy the preset directory tree, rendering template placeholders.
    """
    for root, dirs, filenames in os.walk(preset_path):
        rel_root = Path(root).relative_to(preset_path)

        # Render {project_name} in directory names
        rendered_rel_root = Path(
            str(rel_root).replace("{project_name}", project_name)
        ) if rel_root != Path(".") else Path("")

        target_root = project_path / rendered_rel_root
        target_root.mkdir(parents=True, exist_ok=True)

        # Process files
        for f in filenames:
            src_file = Path(root) / f
            rendered_name = f.replace("{project_name}", project_name)
            dst_file = target_root / rendered_name
            _render_template_file(src_file, dst_file, project_name)


def generate_project(preset: str, name: str, git: bool = False, dry_run: bool = False):
    """
    Core generator logic.

    `preset` can be either:
    - a language (e.g. "python", "go") → uses the default variant
    - "language/variant" (e.g. "python/basic")
    """
    project_path = Path.cwd() / name
    if project_path.exists():
        typer.echo(f"Error: {name} already exists!")
        raise typer.Exit(1)

    # Resolve preset -> language + variant
    if "/" in preset:
        language, variant = preset.split("/", 1)
    else:
        language, variant = preset, DEFAULT_VARIANT

    preset_dir = PRESETS_ROOT / language / variant
    if not preset_dir.exists():
        available = ", ".join(list_presets())
        typer.echo(
            f"Error: preset '{preset}' not found.\n"
            f"Available presets: {available or 'none'}"
        )
        raise typer.Exit(1)

    if dry_run:
        files = _planned_files(preset_dir, name, project_path)
        lang_color = _lang_color(language) or typer.colors.CYAN
        typer.secho(
            f"\n[dry-run] Would create project '{name}' with preset '{language}/{variant}':",
            fg=lang_color,
        )
        if not files:
            typer.echo("  (no files)")
        else:
            for path in files:
                typer.echo(f"  - {path}")
        typer.secho(
            "\nDry run only; no files were written.",
            fg=typer.colors.BRIGHT_BLACK,
        )
        return

    # Copy the preset tree into the new project
    _copy_preset_tree(preset_dir, project_path, name)

    # Optional: git init
    if git:
        os.system(f"cd {project_path} && git init >/dev/null 2>&1")

    typer.secho(
        f"\nProject '{name}' created with preset '{language}/{variant}'.",
        fg=typer.colors.GREEN,
    )

    meta = _load_preset_meta(language, variant)
    next_steps = meta.get("next_steps") or []
    if next_steps:
        typer.secho("\nNext steps:", fg=typer.colors.CYAN, bold=True)
        for step in next_steps:
            # Apply {project_name} placeholder in commands too
            rendered = str(step).replace("{project_name}", name)
            typer.echo(f"  - {rendered}")


def _interactive_flow(git: bool, dry_run: bool) -> None:
    """
    Rich, menu-based interactive flow when no arguments are provided.
    """
    presets_by_lang = _preset_index()
    if not presets_by_lang:
        typer.secho(
            "No presets found. Create some under 'presets/<language>/<variant>/'.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    typer.secho("\n ProKit ", fg=typer.colors.CYAN, bold=True, nl=False)
    typer.secho("• project starter\n", fg=typer.colors.WHITE)
    typer.secho("Arrow keys to move, Enter to select.\n", fg=typer.colors.BRIGHT_BLACK)

    if questionary is None:
        # Fallback to simple prompts if questionary is not installed
        typer.secho(
            "Tip: install 'questionary' for a nicer arrow-key menu "
            "(pip install questionary).",
            fg=typer.colors.YELLOW,
        )

        languages = sorted(presets_by_lang.keys())
        default_lang = DEFAULT_PRESET if DEFAULT_PRESET in languages else languages[0]
        lang = typer.prompt("Language", default=default_lang)

        variants = presets_by_lang.get(lang)
        if not variants:
            typer.secho(f"Unknown language '{lang}'.", fg=typer.colors.RED)
            raise typer.Exit(1)

        default_variant = DEFAULT_VARIANT if DEFAULT_VARIANT in variants else variants[0]
        variant = typer.prompt("Variant", default=default_variant)

        project_name = typer.prompt("Project name")
    else:
        languages = sorted(presets_by_lang.keys())
        lang = questionary.select(
            "Choose a language preset",
            choices=languages,
            default=DEFAULT_PRESET if DEFAULT_PRESET in languages else languages[0],
        ).ask()

        if not lang:
            raise typer.Exit(1)

        variants = presets_by_lang[lang]
        if len(variants) == 1:
            variant = variants[0]
        else:
            variant = questionary.select(
                f"{lang} preset",
                choices=variants,
                default=DEFAULT_VARIANT if DEFAULT_VARIANT in variants else variants[0],
            ).ask()

        if not variant:
            raise typer.Exit(1)

        meta = _load_preset_meta(lang, variant)
        desc = meta.get("description")
        if desc:
            color = _lang_color(lang) or typer.colors.CYAN
            typer.secho(f"\n{lang}/{variant}: ", fg=color, nl=False)
            typer.echo(desc)

        project_name = questionary.text("Project name").ask()

    if not project_name:
        typer.secho("Project name is required.", fg=typer.colors.RED)
        raise typer.Exit(1)

    # Confirmation summary
    preset_key = f"{lang}/{variant}"
    typer.secho("\nSummary:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Preset : {preset_key}")
    typer.echo(f"  Name   : {project_name}")

    if questionary is not None:
        confirm = questionary.confirm("Create project?", default=True).ask()
    else:
        confirm = typer.confirm("Create project?", default=True)

    if not confirm:
        typer.secho("Aborted.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    generate_project(preset_key, project_name, git=git, dry_run=dry_run)


@app.command("list")
def list_command() -> None:
    """
    List available presets grouped by language.
    """
    index = _preset_index()
    if not index:
        typer.secho("No presets found.", fg=typer.colors.RED)
        return

    typer.secho("Available presets:\n", fg=typer.colors.CYAN, bold=True)

    for language in sorted(index.keys()):
        lang_color = _lang_color(language) or typer.colors.WHITE
        typer.secho(f"{language}:", fg=lang_color, bold=True)
        for variant in index[language]:
            meta = _load_preset_meta(language, variant)
            label = meta.get("name") or f"{language}/{variant}"
            desc = meta.get("description") or ""
            line = f"  - {language}/{variant}"
            if label and label != f"{language}/{variant}":
                line += f" ({label})"
            typer.secho(line, fg=lang_color)
            if desc:
                typer.secho(f"      {desc}", fg=typer.colors.BRIGHT_BLACK)
        typer.echo()

# ---------- CLI ----------
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    preset: str | None = typer.Argument(
        None,
        help=(
            "Preset name. Either a language "
            "(e.g. 'python', 'go') or 'language/variant' "
            "(e.g. 'python/basic')."
        ),
    ),
    name: str | None = typer.Argument(
        None,
        help="Project name (or second argument when preset is provided).",
    ),
    git: bool = typer.Option(
        False,
        "--git",
        "-g",
        help="Initialize a Git repository in the generated project.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview files that would be created without writing anything.",
    ),
):
    """
    ProKit - Project Kit

    Usage:
      prokit                         # interactive mode
      prokit <name>                  # default preset (python/basic)
      prokit <preset> <name>         # specific preset

    Presets:
      - Use a language name to get its default variant, e.g. "python" or "go".
      - Or use "language/variant", e.g. "python/basic", "go/basic".
    """
    # 1. No arguments → interactive
    if preset is None and name is None:
        _interactive_flow(git=git, dry_run=dry_run)
        raise typer.Exit()

    # 2. One argument → project name, default preset
    if name is None:
        name = preset
        preset = DEFAULT_PRESET

    # 3. Two arguments → preset + project name
    generate_project(preset, name, git=git, dry_run=dry_run)

if __name__ == "__main__":
    app()