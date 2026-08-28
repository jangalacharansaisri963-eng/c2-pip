# c2pip/scanner.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser
import tree_sitter_c


class ScanError(Exception):
    """Raised when a C file cannot be parsed or scanned."""


class UnsupportedTypeError(ScanError):
    """Raised when a C declaration cannot be represented safely."""


@dataclass(slots=True)
class CArgument:
    """A parsed C function argument."""

    type: str
    name: str
    is_pointer: bool = False
    is_const: bool = False
    pointer_depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "is_pointer": self.is_pointer,
            "is_const": self.is_const,
            "pointer_depth": self.pointer_depth,
        }


@dataclass(slots=True)
class CFunction:
    """A parsed C function declaration."""

    return_type: str
    name: str
    args: list[CArgument] = field(default_factory=list)
    is_definition: bool = False
    is_static: bool = False
    line: int = 0
    column: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "return_type": self.return_type,
            "name": self.name,
            "args": [arg.to_dict() for arg in self.args],
            "is_definition": self.is_definition,
            "is_static": self.is_static,
            "line": self.line,
            "column": self.column,
        }


class CScanner:
    """
    Full AST-based C scanner powered by Tree-sitter.

    The scanner discovers function declarations and definitions without
    relying on regular expressions.

    Example:

        scanner = CScanner()
        functions = scanner.scan("math.h")

    Returns a list of dictionaries compatible with c2pip's generator:

        [
            {
                "return_type": "int",
                "name": "add",
                "args": [
                    {
                        "type": "int",
                        "name": "a",
                        "is_pointer": False,
                        "is_const": False,
                        "pointer_depth": 0,
                    }
                ],
            }
        ]
    """

    def __init__(
        self,
        *,
        include_static: bool = False,
        include_definitions: bool = True,
        strict: bool = False,
    ) -> None:
        self.include_static = include_static
        self.include_definitions = include_definitions
        self.strict = strict

        self._language = Language(
            tree_sitter_c.language()
        )

        self._parser = Parser(self._language)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(
        self,
        path: str | Path,
    ) -> list[dict[str, Any]]:
        """
        Parse a C source/header file and return discovered functions.
        """

        path = Path(path)

        self._validate_path(path)

        try:
            source = path.read_bytes()
        except OSError as exc:
            raise ScanError(
                f"Unable to read '{path}': {exc}"
            ) from exc

        return self.scan_source(
            source,
            filename=str(path),
        )

    def scan_source(
        self,
        source: str | bytes,
        *,
        filename: str = "<memory>",
    ) -> list[dict[str, Any]]:
        """
        Parse C source supplied as a string or bytes object.
        """

        if isinstance(source, str):
            source_bytes = source.encode("utf-8")
        elif isinstance(source, bytes):
            source_bytes = source
        else:
            raise TypeError(
                "source must be str or bytes"
            )

        tree = self._parser.parse(source_bytes)

        if tree.root_node.has_error:
            errors = self._collect_syntax_errors(
                tree.root_node
            )

            message = (
                f"C parser found {len(errors)} syntax error(s) "
                f"in {filename}."
            )

            if errors:
                message += "\n" + "\n".join(
                    f"  - {error}"
                    for error in errors[:10]
                )

            if self.strict:
                raise ScanError(message)

        functions: list[CFunction] = []

        self._walk(
            tree.root_node,
            source_bytes,
            functions,
        )

        return self._deduplicate(
            functions
        )

    # ------------------------------------------------------------------
    # AST traversal
    # ------------------------------------------------------------------

    def _walk(
        self,
        node: Any,
        source: bytes,
        functions: list[CFunction],
    ) -> None:
        if node.type == "function_definition":
            function = self._parse_function(
                node,
                source,
                is_definition=True,
            )

            if function is not None:
                if (
                    self.include_definitions
                    and (
                        self.include_static
                        or not function.is_static
                    )
                ):
                    functions.append(function)

            return

        if node.type == "declaration":
            self._parse_declaration(
                node,
                source,
                functions,
            )

        for child in node.named_children:
            self._walk(
                child,
                source,
                functions,
            )

    def _parse_declaration(
        self,
        node: Any,
        source: bytes,
        functions: list[CFunction],
    ) -> None:
        """
        Parse declarations such as:

            int add(int a, int b);

            double calculate(
                double x,
                double y
            );
        """

        declarators = [
            child
            for child in node.named_children
            if self._is_function_declarator(child)
        ]

        if not declarators:
            return

        base_type = self._extract_base_type(
            node,
            source,
        )

        is_static = self._has_storage_class(
            node,
            source,
            "static",
        )

        if is_static and not self.include_static:
            return

        for declarator in declarators:
            function = self._build_function(
                node=node,
                declarator=declarator,
                base_type=base_type,
                source=source,
                is_definition=False,
                is_static=is_static,
            )

            if function is not None:
                functions.append(function)

    def _parse_function(
        self,
        node: Any,
        source: bytes,
        *,
        is_definition: bool,
    ) -> CFunction | None:
        """
        Parse a function_definition node.
        """

        declarator = node.child_by_field_name(
            "declarator"
        )

        if declarator is None:
            return None

        base_type = self._extract_base_type(
            node,
            source,
        )

        is_static = self._has_storage_class(
            node,
            source,
            "static",
        )

        return self._build_function(
            node=node,
            declarator=declarator,
            base_type=base_type,
            source=source,
            is_definition=is_definition,
            is_static=is_static,
        )

    def _build_function(
        self,
        *,
        node: Any,
        declarator: Any,
        base_type: str,
        source: bytes,
        is_definition: bool,
        is_static: bool,
    ) -> CFunction | None:
        function_declarator = self._find_function_declarator(
            declarator
        )

        if function_declarator is None:
            return None

        name = self._extract_function_name(
            function_declarator,
            source,
        )

        if not name:
            return None

        return_type = self._build_return_type(
            base_type,
            declarator,
            source,
        )

        parameters = function_declarator.child_by_field_name(
            "parameters"
        )

        args: list[CArgument] = []

        if parameters is not None:
            for parameter in parameters.named_children:
                argument = self._parse_parameter(
                    parameter,
                    source,
                )

                if argument is not None:
                    args.append(argument)

        return CFunction(
            return_type=return_type,
            name=name,
            args=args,
            is_definition=is_definition,
            is_static=is_static,
            line=node.start_point[0] + 1,
            column=node.start_point[1] + 1,
        )

    # ------------------------------------------------------------------
    # Parameter parsing
    # ------------------------------------------------------------------

    def _parse_parameter(
        self,
        node: Any,
        source: bytes,
    ) -> CArgument | None:
        if node.type == "variadic_parameter":
            raise UnsupportedTypeError(
                "Variadic C functions (...) are not currently "
                "supported by c2pip."
            )

        if node.type not in {
            "parameter_declaration",
            "optional_parameter_declaration",
        }:
            return None

        type_node = node.child_by_field_name(
            "type"
        )

        declarator = node.child_by_field_name(
            "declarator"
        )

        base_type = self._node_text(
            type_node,
            source,
        )

        if not base_type:
            return None

        name = self._extract_parameter_name(
            declarator,
            source,
        )

        if not name:
            # Valid C permits unnamed parameters.
            # Give the wrapper a deterministic internal name.
            name = f"arg_{node.start_point[0]}"

        pointer_depth = self._pointer_depth(
            declarator
        )

        is_const = self._contains_const(
            node,
            source,
        )

        normalized_base = self._normalize_type(
            base_type
        )

        full_type = self._compose_type(
            normalized_base,
            pointer_depth,
            is_const,
        )

        return CArgument(
            type=full_type,
            name=name,
            is_pointer=pointer_depth > 0,
            is_const=is_const,
            pointer_depth=pointer_depth,
        )

    # ------------------------------------------------------------------
    # Type handling
    # ------------------------------------------------------------------

    def _extract_base_type(
        self,
        node: Any,
        source: bytes,
    ) -> str:
        type_parts: list[str] = []

        for child in node.named_children:
            if child.type in {
                "primitive_type",
                "type_identifier",
                "struct_specifier",
                "enum_specifier",
                "union_specifier",
            }:
                text = self._node_text(
                    child,
                    source,
                )

                if text:
                    type_parts.append(text)

        if not type_parts:
            type_node = node.child_by_field_name(
                "type"
            )

            if type_node is not None:
                return self._normalize_type(
                    self._node_text(
                        type_node,
                        source,
                    )
                )

        return self._normalize_type(
            " ".join(type_parts)
        )

    def _build_return_type(
        self,
        base_type: str,
        declarator: Any,
        source: bytes,
    ) -> str:
        pointer_depth = self._pointer_depth(
            declarator
        )

        is_const = self._contains_const(
            declarator,
            source,
        )

        return self._compose_type(
            base_type,
            pointer_depth,
            is_const,
        )

    @staticmethod
    def _compose_type(
        base_type: str,
        pointer_depth: int,
        is_const: bool,
    ) -> str:
        base_type = " ".join(
            base_type.split()
        )

        if pointer_depth == 0:
            return base_type

        if (
            is_const
            and base_type == "char"
            and pointer_depth == 1
        ):
            return "const char *"

        return (
            f"{base_type} "
            + "*" * pointer_depth
        ).strip()

    @staticmethod
    def _normalize_type(type_name: str) -> str:
        type_name = " ".join(
            type_name.strip().split()
        )

        replacements = {
            "signed": "signed int",
            "unsigned": "unsigned int",
            "short int": "short",
            "unsigned short int": "unsigned short",
            "long int": "long",
            "unsigned long int": "unsigned long",
            "long long int": "long long",
            "unsigned long long int":
                "unsigned long long",
        }

        return replacements.get(
            type_name,
            type_name,
        )

    # ------------------------------------------------------------------
    # Declarator helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_function_declarator(
        node: Any,
    ) -> bool:
        return node.type in {
            "function_declarator",
        } or (
            node.type == "pointer_declarator"
            and any(
                child.type == "function_declarator"
                for child in node.named_children
            )
        )

    def _find_function_declarator(
        self,
        node: Any,
    ) -> Any | None:
        if node.type == "function_declarator":
            return node

        for child in node.named_children:
            result = self._find_function_declarator(
                child
            )

            if result is not None:
                return result

        return None

    def _extract_function_name(
        self,
        node: Any,
        source: bytes,
    ) -> str | None:
        declarator = node.child_by_field_name(
            "declarator"
        )

        if declarator is None:
            return None

        return self._extract_identifier(
            declarator,
            source,
        )

    def _extract_parameter_name(
        self,
        node: Any,
        source: bytes,
    ) -> str | None:
        if node is None:
            return None

        return self._extract_identifier(
            node,
            source,
        )

    def _extract_identifier(
        self,
        node: Any,
        source: bytes,
    ) -> str | None:
        if node.type == "identifier":
            return self._node_text(
                node,
                source,
            )

        for child in node.named_children:
            result = self._extract_identifier(
                child,
                source,
            )

            if result:
                return result

        return None

    def _pointer_depth(
        self,
        node: Any,
    ) -> int:
        if node is None:
            return 0

        depth = 0

        if node.type == "pointer_declarator":
            depth += 1

        for child in node.named_children:
            depth += self._pointer_depth(
                child
            )

        return depth

    def _contains_const(
        self,
        node: Any,
        source: bytes,
    ) -> bool:
        if node is None:
            return False

        text = self._node_text(
            node,
            source,
        )

        return bool(
            text
            and "const" in text.split()
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _node_text(
        node: Any | None,
        source: bytes,
    ) -> str:
        if node is None:
            return ""

        return source[
            node.start_byte:node.end_byte
        ].decode(
            "utf-8",
            errors="replace",
        ).strip()

    @staticmethod
    def _has_storage_class(
        node: Any,
        source: bytes,
        storage_class: str,
    ) -> bool:
        text = source[
            node.start_byte:node.end_byte
        ].decode(
            "utf-8",
            errors="replace",
        )

        return bool(
            __import__("re").search(
                rf"\b{storage_class}\b",
                text,
            )
        )

    @staticmethod
    def _collect_syntax_errors(
        node: Any,
    ) -> list[str]:
        errors: list[str] = []

        def walk(current: Any) -> None:
            if current.type == "ERROR":
                errors.append(
                    f"line {current.start_point[0] + 1}, "
                    f"column {current.start_point[1] + 1}"
                )

            for child in current.named_children:
                walk(child)

        walk(node)

        return errors

    @staticmethod
    def _deduplicate(
        functions: list[CFunction],
    ) -> list[dict[str, Any]]:
        """
        Remove duplicate declarations while preserving order.

        A declaration and a definition of the same function are considered
        the same exported function.
        """

        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        for function in functions:
            if function.name in seen:
                continue

            seen.add(function.name)
            result.append(
                function.to_dict()
            )

        return result

    @staticmethod
    def _validate_path(
        path: Path,
    ) -> None:
        if not path.exists():
            raise ScanError(
                f"File does not exist: {path}"
            )

        if not path.is_file():
            raise ScanError(
                f"Not a file: {path}"
            )

        if path.suffix.lower() not in {
            ".h",
            ".c",
        }:
            raise ScanError(
                "c2pip currently supports C files "
                "with .h and .c extensions."
            )


# ----------------------------------------------------------------------
# Simple public API
# ----------------------------------------------------------------------

def scan_file(
    path: str | Path,
) -> list[dict[str, Any]]:
    """
    Convenience wrapper around CScanner.scan().
    """

    return CScanner().scan(path)


def scan_source(
    source: str | bytes,
) -> list[dict[str, Any]]:
    """
    Convenience wrapper for scanning an in-memory C source.
    """

    return CScanner().scan_source(source)
