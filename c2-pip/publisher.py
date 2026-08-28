from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


class PublishError(Exception):
    """Raised when a c2pip package cannot be published."""


class PackagePublisher:
    """Validate and upload c2pip distributions with Twine."""

    TWINE_MODULE = "twine"

    def __init__(
        self,
        project_dir: str | Path = ".",
        *,
        repository: str = "pypi",
        verbose: bool = False,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.repository = repository
        self.verbose = verbose

        if repository not in {
            "pypi",
            "testpypi",
        }:
            raise PublishError(
                "Repository must be 'pypi' or 'testpypi'."
            )

    def publish(
        self,
        *,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> list[Path]:
        """Validate distributions and upload them to PyPI."""

        self._validate_project()

        self._ensure_twine_available()

        distributions = self._find_distributions()

        if not distributions:
            raise PublishError(
                "No distributions found in dist/. "
                "Run 'c2pip build' first."
            )

        self._check_distributions(
            distributions
        )

        environment = os.environ.copy()

        self._configure_credentials(
            environment,
            token=token,
            username=username,
            password=password,
        )

        command = [
            sys.executable,
            "-m",
            self.TWINE_MODULE,
            "upload",
        ]

        if self.repository == "testpypi":
            command.extend(
                [
                    "--repository",
                    "testpypi",
                ]
            )

        command.extend(
            str(path)
            for path in distributions
        )

        self._run(
            command,
            environment=environment,
            description=(
                "Uploading to "
                + (
                    "TestPyPI"
                    if self.repository == "testpypi"
                    else "PyPI"
                )
            ),
        )

        self._print("")
        self._print(
            "✓ Publication successful."
        )

        for distribution in distributions:
            self._print(
                f"  → {distribution.name}"
            )

        return distributions

    def check(
        self,
    ) -> list[Path]:
        """Run twine check against all generated distributions."""

        self._validate_project()
        self._ensure_twine_available()

        distributions = self._find_distributions()

        if not distributions:
            raise PublishError(
                "No distributions found in dist/. "
                "Run 'c2pip build' first."
            )

        self._check_distributions(
            distributions
        )

        return distributions

    def _validate_project(self) -> None:
        """Validate the project directory."""

        if not self.project_dir.exists():
            raise PublishError(
                f"Project directory does not exist: "
                f"{self.project_dir}"
            )

        if not self.project_dir.is_dir():
            raise PublishError(
                f"Project path is not a directory: "
                f"{self.project_dir}"
            )

    def _ensure_twine_available(self) -> None:
        """Install Twine if it is not already available."""

        if importlib.util.find_spec(
            self.TWINE_MODULE
        ) is not None:
            return

        self._print(
            "Twine not found; installing 'twine'..."
        )

        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "twine",
        ]

        self._run(
            command,
            environment=os.environ.copy(),
            description="Installing Twine",
        )

    def _find_distributions(self) -> list[Path]:
        """Find uploadable distribution files."""

        dist = self.project_dir / "dist"

        if not dist.is_dir():
            return []

        distributions = []

        for path in dist.iterdir():
            if not path.is_file():
                continue

            if path.suffix in {
                ".whl",
                ".gz",
                ".zip",
            }:
                distributions.append(
                    path.resolve()
                )

        return sorted(
            distributions,
            key=lambda path: path.name,
        )

    def _check_distributions(
        self,
        distributions: Sequence[Path],
    ) -> None:
        """Run twine check and fail with actionable diagnostics."""

        command = [
            sys.executable,
            "-m",
            self.TWINE_MODULE,
            "check",
        ]

        command.extend(
            str(path)
            for path in distributions
        )

        self._run(
            command,
            environment=os.environ.copy(),
            description="Checking distributions",
        )

        self._print(
            "✓ Distribution metadata is valid."
        )

    @staticmethod
    def _configure_credentials(
        environment: dict[str, str],
        *,
        token: str | None,
        username: str | None,
        password: str | None,
    ) -> None:
        """
        Configure credentials without putting secrets into
        the subprocess command line.

        Twine understands TWINE_USERNAME and TWINE_PASSWORD.
        """

        if token:
            environment["TWINE_USERNAME"] = "__token__"
            environment["TWINE_PASSWORD"] = token
            return

        if username:
            environment["TWINE_USERNAME"] = username

        if password:
            environment["TWINE_PASSWORD"] = password

    def _run(
        self,
        command: Sequence[str],
        *,
        environment: dict[str, str],
        description: str,
    ) -> None:
        """Execute a Twine command and provide useful errors."""

        self._print(
            f"→ {description}..."
        )

        if self.verbose:
            self._print(
                "$ "
                + " ".join(
                    self._quote_argument(
                        argument
                    )
                    for argument in command
                )
            )

        try:
            process = subprocess.run(
                list(command),
                cwd=self.project_dir,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except OSError as exc:
            raise PublishError(
                f"Unable to execute publishing command: "
                f"{exc}"
            ) from exc

        output = process.stdout or ""

        if output:
            self._print(
                output.rstrip()
            )

        if process.returncode != 0:
            raise PublishError(
                self._format_failure(
                    process.returncode,
                    output,
                )
            )

    @staticmethod
    def _format_failure(
        return_code: int,
        output: str,
    ) -> str:
        """Turn a Twine failure into a useful error message."""

        lowered = output.lower()

        lines = [
            "Package publication failed.",
            f"Exit code: {return_code}.",
        ]

        if (
            "403" in lowered
            or "forbidden" in lowered
            or "authentication" in lowered
            or "unauthorized" in lowered
        ):
            lines.append(
                "Hint: check your PyPI credentials or API token."
            )

        if (
            "already exists" in lowered
            or "file already exists" in lowered
        ):
            lines.append(
                "Hint: that package version may already exist "
                "on the selected repository. Increment the "
                "project version before publishing again."
            )

        if (
            "invalid distribution" in lowered
            or "twine check" in lowered
        ):
            lines.append(
                "Hint: run 'c2pip publish --check' and fix "
                "the reported distribution metadata errors."
            )

        if output.strip():
            lines.append(
                "\nTwine output:\n"
                + output.strip()
            )

        return "\n".join(
            lines
        )

    @staticmethod
    def _quote_argument(
        argument: str,
    ) -> str:
        """Quote an argument for human-readable verbose output."""

        if not argument:
            return '""'

        if any(
            character.isspace()
            for character in argument
        ):
            return f'"{argument}"'

        return argument

    @staticmethod
    def _print(
        message: str,
    ) -> None:
        """Print immediately."""

        print(
            message,
            flush=True,
        )


def publish_project(
    project_dir: str | Path = ".",
    *,
    repository: str = "pypi",
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    verbose: bool = False,
) -> list[Path]:
    """Convenience API used by c2pip.cli."""

    publisher = PackagePublisher(
        project_dir,
        repository=repository,
        verbose=verbose,
    )

    return publisher.publish(
        token=token,
        username=username,
        password=password,
    )


def check_project(
    project_dir: str | Path = ".",
) -> list[Path]:
    """Convenience API for validating distributions."""

    publisher = PackagePublisher(
        project_dir
    )

    return publisher.check()


__all__ = [
    "PublishError",
    "PackagePublisher",
    "publish_project",
    "check_project",
      ]
