"""
Run this script once after first creating your project from this template repo
to personalize it for own project.

This script is interactive and will prompt you for various inputs.

Usage:
    # Initial personalization (package name, git URL, etc.)
    python personalize.py

    # Clean up sample code (remove sample implementations)
    python personalize.py --cleanup-sample-code
"""

import re
import shutil
from pathlib import Path
from typing import Generator, List, Optional, Set, Tuple

import click
from click_help_colors import HelpColorsCommand
from rich import print
from rich.markdown import Markdown
from rich.prompt import Confirm
from rich.syntax import Syntax
from rich.traceback import install

install(show_locals=True, suppress=[click])

# Component definitions for sample code cleanup
COMPONENT_CLI = "cli"
COMPONENT_API = "api"
COMPONENT_DL = "dl"
ALL_COMPONENTS = [COMPONENT_CLI, COMPONENT_API, COMPONENT_DL]

LAYOUT_SRC = "src"
LAYOUT_FLAT = "flat"

GIT_REPO_URL = "GITREPOURL"
REPO_BASE = Path(__file__).parent.resolve()

FILES_TO_REMOVE = {
    REPO_BASE / "setup-requirements.txt",
    REPO_BASE / "personalize.py",
}

PATHS_TO_IGNORE = {
    REPO_BASE / ".git",
    REPO_BASE / "docs" / "logo.png",
    REPO_BASE / "data",
}

GITIGNORE_LIST = [
    line.strip()
    for line in (REPO_BASE / ".gitignore").open().readlines()
    if line.strip() and not line.startswith("#")
]


@click.command(
    cls=HelpColorsCommand,
    help_options_color="green",
    help_headers_color="yellow",
    context_settings={"max_content_width": 115},
)
@click.option(
    "--package-name",
    prompt=(
        "Python package name"
        " (e.g. 'my-package'. import name is made with replace('_', '-') )"
    ),
    help="The name of your Python package.",
)
@click.option(
    "--git-repo-url",
    prompt=(
        "Git repository URL (e.g." " https://github.com/synforger/personal-template)"
    ),
    help="Git repository URL username/repository_name",
)
@click.option(
    "--python-version",
    prompt="Python version (used for unittest.yml. e.g. 3.10)",
    help="The version of Python.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Run the script without prompting for a confirmation.",
    default=False,
)
@click.option(
    "--dry-run",
    is_flag=True,
    hidden=True,
    default=False,
)
@click.option("--venv-dir", help="The directory name for venv", default=None)
@click.option(
    "--layout",
    type=click.Choice([LAYOUT_SRC, LAYOUT_FLAT], case_sensitive=False),
    prompt=(
        f"Package layout ({LAYOUT_SRC}: src/package_name/, {LAYOUT_FLAT}: package_name/)"
    ),
    help="Package directory layout (src or flat).",
    default=LAYOUT_SRC,
)
def main(
    package_name: str,
    git_repo_url: str,
    venv_dir: str,
    python_version: str,
    layout: str,
    yes: bool = False,
    dry_run: bool = False,
):
    package_actual_name = package_name.replace("_", "-")
    package_dir_name = package_name.replace("-", "_")

    # Confirm before continuing.
    print(f"Package name set to: [cyan]{package_actual_name}[/]")
    print(f"Git repository URL set to: [cyan]{git_repo_url}[/]")
    print(f"Python version set to: [cyan]{python_version}[/]")
    print(f"Package layout set to: [cyan]{layout}[/]")
    if not yes:
        yes = Confirm.ask("Is this correct?")
    if not yes:
        raise click.ClickException("Aborted, please run script again")

    # Personalize remaining files.
    replacements = [
        (GIT_REPO_URL, git_repo_url),
        ("my-package", package_actual_name),
        ("my_package", package_dir_name),
        ("PYTHONVERSION", python_version),
    ]
    if dry_run:
        for old, new in replacements:
            print(f"Replacing '{old}' with '{new}'")

    if venv_dir is not None:
        PATHS_TO_IGNORE.add(REPO_BASE / venv_dir)

    for path in iterfiles(REPO_BASE, PATHS_TO_IGNORE):
        personalize_file(path, dry_run, replacements)

    # Rename 'my_package' directory to `package_dir_name`.
    if not dry_run:
        (REPO_BASE / "src/my_package").replace(REPO_BASE / "src" / package_dir_name)
    else:
        print(f"Renaming 'my_package' directory to '{package_dir_name}'")

    # Reset project version to 0.0.0 (TEMPLATE_VERSION is preserved).
    reset_version(REPO_BASE, package_dir_name, dry_run)

    # Convert to flat layout if selected, otherwise update CI for src layout only.
    if layout == LAYOUT_FLAT:
        convert_to_flat_layout(REPO_BASE, package_dir_name, dry_run)
    else:
        # Update unittest.yml to only test src layout
        update_unittest_yml_layout(REPO_BASE, LAYOUT_SRC, dry_run)

    # Delete files that we don't need.
    for path in FILES_TO_REMOVE:
        assert path.is_file(), path
        if not dry_run:
            path.unlink()
        else:
            print(f"Removing {path}")

    install_example = Syntax("pip install -e '.[dev,sample]'", "bash")
    print(
        "[green]\N{CHECK MARK} Success![/] You can now install"
        " your package locally in development mode with:\n",
        install_example,
    )

    # Ask if user wants to clean up sample code
    if not dry_run:
        print("")
        if Confirm.ask(
            "Do you want to clean up sample code? (remove cli/api/dl components)",
            default=False,
        ):
            _run_interactive_cleanup(package_dir_name)


def convert_to_flat_layout(repo_base: Path, package_dir_name: str, dry_run: bool):
    """Convert from src layout to flat layout.

    This moves the package from src/<package_dir_name>/ to <package_dir_name>/
    and updates pyproject.toml accordingly.
    """
    src_dir = repo_base / "src"
    src_package_dir = src_dir / package_dir_name
    flat_package_dir = repo_base / package_dir_name

    # Move package directory from src/ to root
    if not dry_run:
        shutil.move(str(src_package_dir), str(flat_package_dir))
        # Remove empty src directory
        if src_dir.exists() and not any(src_dir.iterdir()):
            src_dir.rmdir()
        print(f"[yellow]Converted to flat layout:[/] {package_dir_name}/")
    else:
        print(f"Moving '{src_package_dir}' to '{flat_package_dir}'")
        print(f"Removing empty '{src_dir}' directory")

    # Update pyproject.toml for flat layout
    pyproject_path = repo_base / "pyproject.toml"
    if not dry_run:
        with open(pyproject_path, "r") as file:
            content = file.read()

        replacements = [
            ('package-dir = { "" = "src" }', ""),
            ('where = ["src"]', 'where = ["."]'),
        ]
        for old, new in replacements:
            content = content.replace(old, new)

        with open(pyproject_path, "w") as f:
            f.write(content)
    else:
        print("Updating pyproject.toml for flat layout")

    # Update Makefile for flat layout (docs commands still have hardcoded paths)
    makefile_path = repo_base / "Makefile"
    if makefile_path.exists():
        if not dry_run:
            with open(makefile_path, "r") as file:
                content = file.read()

            # Update docs commands that have hardcoded src/ paths
            makefile_replacements = [
                (f"./src/{package_dir_name}", f"./{package_dir_name}"),
                (f"src/{package_dir_name}/", f"{package_dir_name}/"),
            ]
            for old, new in makefile_replacements:
                content = content.replace(old, new)

            with open(makefile_path, "w") as f:
                f.write(content)
        else:
            print("Updating Makefile for flat layout")

    # Update unittest.yml to only test flat layout
    update_unittest_yml_layout(repo_base, LAYOUT_FLAT, dry_run)


def reset_version(repo_base: Path, package_dir_name: str, dry_run: bool):
    """Reset the project version to 0.0.0.

    This resets _MAJOR, _MINOR, _PATCH to "0" while preserving TEMPLATE_VERSION.
    Also resets the current_version in pyproject.toml bumpversion config.
    """
    version_path = repo_base / "src" / package_dir_name / "version.py"
    if not version_path.exists():
        return

    if not dry_run:
        with open(version_path, "r") as file:
            content = file.read()

        # Reset version components to 0.0.0
        content = re.sub(r'_MAJOR = "\d+"', '_MAJOR = "0"', content)
        content = re.sub(r'_MINOR = "\d+"', '_MINOR = "0"', content)
        content = re.sub(r'_PATCH = "\d+"', '_PATCH = "0"', content)

        with open(version_path, "w") as f:
            f.write(content)
        print("[yellow]Reset project version to 0.0.0[/]")
    else:
        print("Resetting project version to 0.0.0")

    # Also reset current_version in pyproject.toml
    pyproject_path = repo_base / "pyproject.toml"
    if pyproject_path.exists():
        if not dry_run:
            with open(pyproject_path, "r") as file:
                content = file.read()

            content = re.sub(
                r'current_version = "\d+\.\d+\.\d+"',
                'current_version = "0.0.0"',
                content
            )

            with open(pyproject_path, "w") as f:
                f.write(content)
        else:
            print("Resetting current_version in pyproject.toml to 0.0.0")


def update_unittest_yml_layout(repo_base: Path, layout: str, dry_run: bool):
    """Update unittest.yml to only test the selected layout.

    This changes the matrix from layout: ["src", "flat"] to layout: ["<selected>"].
    """
    unittest_yml_path = repo_base / ".github" / "workflows" / "unittest.yml"
    if not unittest_yml_path.exists():
        return

    if not dry_run:
        with open(unittest_yml_path, "r") as file:
            content = file.read()

        # Replace the layout matrix to only include the selected layout
        content = content.replace('layout: ["src", "flat"]', f'layout: ["{layout}"]')

        # Remove the flat layout conversion step if src is selected
        if layout == LAYOUT_SRC:
            # Remove the entire "Convert to flat layout" step
            pattern = (
                r"\s*- name: Convert to flat layout \(if needed\).*?(?=\s*- name:)"
            )
            content = re.sub(pattern, "\n      ", content, flags=re.DOTALL)

        with open(unittest_yml_path, "w") as f:
            f.write(content)
    else:
        print(f"Updating unittest.yml to only test {layout} layout")


def iterfiles(dir: Path, path_to_ignore: str) -> Generator[Path, None, None]:
    assert dir.is_dir()
    for path in dir.iterdir():
        if path in path_to_ignore:
            continue

        is_ignored_file = False
        for gitignore_entry in GITIGNORE_LIST:
            if path.relative_to(REPO_BASE).match(gitignore_entry):
                is_ignored_file = True
                break
        if is_ignored_file:
            continue

        if path.is_dir():
            yield from iterfiles(path, path_to_ignore)
        else:
            yield path


def personalize_file(path: Path, dry_run: bool, replacements: List[Tuple[str, str]]):
    try:
        with path.open("r+t") as file:
            filedata = file.read()
    except UnicodeDecodeError:
        return

    should_update: bool = False
    for old, new in replacements:
        if filedata.count(old):
            should_update = True
            filedata = filedata.replace(old, new)

    if should_update:
        if not dry_run:
            with path.open("w+t") as file:
                file.write(filedata)
        else:
            print(f"Updating {path}")


def cleanup_sample_code(
    repo_base: Path,
    components_to_remove: Set[str],
    package_dir_name: str,
    dry_run: bool = False,
):
    """Remove sample code from the project based on selected components.

    Args:
        repo_base: Path to the repository root
        components_to_remove: Set of components to remove (cli, api, dl)
        package_dir_name: Name of the package directory (e.g., 'my_package')
        dry_run: If True, only print what would be done without making changes
    """
    # Detect layout (src or flat)
    src_package_dir = repo_base / "src" / package_dir_name
    flat_package_dir = repo_base / package_dir_name
    if src_package_dir.exists():
        package_base = src_package_dir
        layout = LAYOUT_SRC
    elif flat_package_dir.exists():
        package_base = flat_package_dir
        layout = LAYOUT_FLAT
    else:
        raise click.ClickException(
            f"Package directory not found: {src_package_dir} or {flat_package_dir}"
        )

    print(f"[cyan]Detected layout:[/] {layout}")
    print(f"[cyan]Package directory:[/] {package_base}")
    print(f"[cyan]Components to remove:[/] {', '.join(components_to_remove)}")

    # Define paths to remove for each component
    paths_to_remove: List[Path] = []
    files_to_empty: List[Path] = []

    # CLI component
    if COMPONENT_CLI in components_to_remove:
        paths_to_remove.extend(
            [
                package_base / "cli",
                repo_base / "tests" / "cli",
                repo_base / "configs" / "cli",
            ]
        )

    # API component
    if COMPONENT_API in components_to_remove:
        paths_to_remove.extend(
            [
                package_base / "api",
                repo_base / "tests" / "api",
                repo_base / "configs" / "api",
            ]
        )

    # DL component (deep learning / Lightning)
    if COMPONENT_DL in components_to_remove:
        paths_to_remove.extend(
            [
                package_base / "dl",
                repo_base / "tests" / "dl",
                repo_base / "configs" / "dl",
                repo_base / "examples" / "example_train_lightning.py",
                repo_base / "examples" / "example_gradio.py",
            ]
        )
        # Also remove legacy directories if they exist
        for legacy_dir in ["litmodules", "datamodules", "models"]:
            legacy_path = package_base / legacy_dir
            if legacy_path.exists():
                paths_to_remove.append(legacy_path)

    # Always remove experimental and doctest_sample
    paths_to_remove.extend(
        [
            package_base / "experimental",
            package_base / "doctest_sample.py",
            repo_base / "tests" / "experimental",
        ]
    )

    # Remove paths
    for path in paths_to_remove:
        if path.exists():
            if not dry_run:
                if path.is_dir():
                    shutil.rmtree(path)
                    print(f"[red]Removed directory:[/] {path.relative_to(repo_base)}")
                else:
                    path.unlink()
                    print(f"[red]Removed file:[/] {path.relative_to(repo_base)}")
            else:
                print(f"[yellow]Would remove:[/] {path.relative_to(repo_base)}")

    # Update pyproject.toml to remove optional dependencies for removed components
    update_pyproject_toml_dependencies(repo_base, components_to_remove, dry_run)

    # Clean up __init__.py files
    cleanup_init_files(package_base, components_to_remove, dry_run)

    print("")
    print("[green]\N{CHECK MARK} Sample code cleanup completed![/]")
    if COMPONENT_DL in components_to_remove:
        print(
            "[yellow]Note:[/] Lightning optional dependencies have been removed from pyproject.toml"
        )
        # Warn about api/cli dependencies on dl
        if COMPONENT_API not in components_to_remove:
            print(
                "[yellow]Warning:[/] api/mnist_app.py has dependencies on dl. "
                "You may need to remove or modify this file manually."
            )
        if COMPONENT_CLI not in components_to_remove:
            print(
                "[yellow]Warning:[/] cli/mnist_cli.py has dependencies on dl. "
                "You may need to remove or modify this file manually."
            )


def update_pyproject_toml_dependencies(
    repo_base: Path,
    components_to_remove: Set[str],
    dry_run: bool,
):
    """Update pyproject.toml to remove optional dependencies for removed components."""
    pyproject_path = repo_base / "pyproject.toml"
    if not pyproject_path.exists():
        return

    if not dry_run:
        with open(pyproject_path, "r") as f:
            content = f.read()

        # Remove lightning optional dependency if dl is removed
        if COMPONENT_DL in components_to_remove:
            # Remove the lightning section from optional-dependencies
            pattern = r"\nlightning\s*=\s*\[[\s\S]*?\](?=\n\w|\n\[|\Z)"
            content = re.sub(pattern, "", content)

        # Remove api optional dependency if api is removed
        if COMPONENT_API in components_to_remove:
            pattern = r"\napi\s*=\s*\[[\s\S]*?\](?=\n\w|\n\[|\Z)"
            content = re.sub(pattern, "", content)

        # Remove cli optional dependency if cli is removed
        if COMPONENT_CLI in components_to_remove:
            pattern = r"\ncli\s*=\s*\[[\s\S]*?\](?=\n\w|\n\[|\Z)"
            content = re.sub(pattern, "", content)

        # Remove sample optional dependency (always)
        pattern = r"\nsample\s*=\s*\[[\s\S]*?\](?=\n\w|\n\[|\Z)"
        content = re.sub(pattern, "", content)

        with open(pyproject_path, "w") as f:
            f.write(content)

        print("[yellow]Updated:[/] pyproject.toml (removed optional dependencies)")
    else:
        print("[yellow]Would update:[/] pyproject.toml (remove optional dependencies)")


def cleanup_init_files(
    package_base: Path,
    components_to_remove: Set[str],
    dry_run: bool,
):
    """Clean up __init__.py files to remove imports of deleted modules."""
    # Main package __init__.py
    main_init = package_base / "__init__.py"
    if main_init.exists():
        if not dry_run:
            with open(main_init, "r") as f:
                content = f.read()

            # Remove imports for removed components
            for component in components_to_remove:
                # Remove import lines
                content = re.sub(
                    rf"^from\s+\S*\.{component}\b.*$\n?",
                    "",
                    content,
                    flags=re.MULTILINE,
                )
                content = re.sub(
                    rf"^import\s+\S*\.{component}\b.*$\n?",
                    "",
                    content,
                    flags=re.MULTILINE,
                )

            with open(main_init, "w") as f:
                f.write(content)
        else:
            print(
                f"[yellow]Would update:[/] {main_init.relative_to(package_base.parent.parent)}"
            )


def _run_interactive_cleanup(package_dir_name: str):
    """Run interactive cleanup flow to select which components to keep."""
    print("")
    print("[cyan]Select components to keep:[/]")
    print("  - cli: Command-line interface (Typer)")
    print("  - api: REST API (FastAPI)")
    print("  - dl: Deep learning / Lightning")
    print("")

    keep_set: Set[str] = set()
    for component in ALL_COMPONENTS:
        if Confirm.ask(f"Keep {component}?", default=False):
            keep_set.add(component)

    components_to_remove = set(ALL_COMPONENTS) - keep_set

    if not components_to_remove:
        print("[yellow]No components selected for removal. Skipping cleanup.[/]")
        return

    # Confirm before proceeding
    print("")
    print(f"[cyan]Components to remove:[/] {', '.join(sorted(components_to_remove))}")
    print(f"[cyan]Components to keep:[/] {', '.join(sorted(keep_set)) or 'none'}")

    if not Confirm.ask("Proceed with cleanup?", default=True):
        print("[yellow]Cleanup skipped.[/]")
        return

    cleanup_sample_code(
        REPO_BASE,
        components_to_remove,
        package_dir_name,
        dry_run=False,
    )


@click.command(
    cls=HelpColorsCommand,
    help_options_color="green",
    help_headers_color="yellow",
    context_settings={"max_content_width": 115},
)
@click.option(
    "--cleanup-sample-code",
    "cleanup_mode",
    is_flag=True,
    help="Remove sample code from the project (run after initial personalization).",
    default=False,
)
@click.option(
    "--keep-components",
    type=click.Choice(ALL_COMPONENTS, case_sensitive=False),
    multiple=True,
    help="Components to keep when cleaning up sample code (can specify multiple).",
    default=None,
)
@click.option(
    "--package-dir",
    help="Package directory name (default: auto-detect from src/ or root).",
    default=None,
)
def cleanup_command(
    cleanup_mode: bool,
    keep_components: Optional[Tuple[str, ...]],
    package_dir: Optional[str],
):
    """Clean up sample code from the project.

    This command removes sample implementations while keeping the project structure.
    Use --keep-components to specify which components to keep (cli, api, dl).

    Example:
        python personalize.py --cleanup-sample-code --keep-components cli --keep-components api
    """
    if not cleanup_mode:
        # If not in cleanup mode, run the main personalization
        ctx = click.get_current_context()
        ctx.invoke(main)
        return

    # Auto-detect package directory if not specified
    if package_dir is None:
        # Try to find package directory
        src_dir = REPO_BASE / "src"
        if src_dir.exists():
            for item in src_dir.iterdir():
                if item.is_dir() and not item.name.startswith("_"):
                    package_dir = item.name
                    break
        if package_dir is None:
            # Try flat layout
            for item in REPO_BASE.iterdir():
                if item.is_dir() and (item / "__init__.py").exists():
                    if item.name not in [
                        "tests",
                        "docs",
                        "examples",
                        "configs",
                        "data",
                    ]:
                        package_dir = item.name
                        break
        if package_dir is None:
            package_dir = "my_package"

    # Determine components to remove
    if keep_components:
        components_to_remove = set(ALL_COMPONENTS) - set(keep_components)
    else:
        # Interactive mode: ask user which components to keep
        print("[cyan]Select components to keep:[/]")
        print("  - cli: Command-line interface (Typer)")
        print("  - api: REST API (FastAPI)")
        print("  - dl: Deep learning / Lightning")
        print("")

        keep_set: Set[str] = set()
        for component in ALL_COMPONENTS:
            if Confirm.ask(f"Keep {component}?", default=False):
                keep_set.add(component)

        components_to_remove = set(ALL_COMPONENTS) - keep_set

    if not components_to_remove:
        print("[yellow]No components selected for removal. Exiting.[/]")
        return

    # Confirm before proceeding
    print("")
    print(f"[cyan]Package directory:[/] {package_dir}")
    print(f"[cyan]Components to remove:[/] {', '.join(sorted(components_to_remove))}")
    print(
        f"[cyan]Components to keep:[/] {', '.join(sorted(set(ALL_COMPONENTS) - components_to_remove)) or 'none'}"
    )

    if not Confirm.ask("Proceed with cleanup?", default=True):
        raise click.ClickException("Aborted")

    cleanup_sample_code(
        REPO_BASE,
        components_to_remove,
        package_dir,
        dry_run=False,
    )


if __name__ == "__main__":
    import sys

    # Check if cleanup mode is requested
    if "--cleanup-sample-code" in sys.argv:
        cleanup_command()
    else:
        main()
