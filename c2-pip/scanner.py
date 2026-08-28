# c2pip/scanner.py
import re
from pathlib import Path
from typing import List, Dict, Any, Union, Set

# Comprehensive C keywords and control structures to filter out during scanning
C_KEYWORDS: Set[str] = {
    'if', 'for', 'while', 'return', 'switch', 'case', 'default', 
    'break', 'continue', 'goto', 'typedef', 'struct', 'union', 
    'enum', 'extern', 'static', 'const', 'volatile', 'register', 
    'auto', 'sizeof', 'sizeof...', 'alignof', 'alignas', 'inline', 
    '_Atomic', '_Complex', '_Generic', '_Imaginary', '_Noreturn', 
    '_Static_assert', '_Thread_local', 'true', 'false', 'NULL'
}

# Standard C types used for basic type classification and parsing format mapping
PRIMITIVE_TYPES: Set[str] = {
    'int', 'short', 'long', 'char', 'float', 'double', 
    'unsigned', 'signed', 'void', 'size_t', 'ssize_t', 
    'int8_t', 'int16_t', 'int32_t', 'int64_t', 
    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t', 'bool'
}

class AdvancedCScanner:
    """Production-grade AST-emulating C scanner, preprocessor directive stripper, 
    and signature parser designed to extract exportable C functions from headers or source files.
    
    Handles:
    - Multi-line and single-line comment stripping
    - Preprocessor macro/include elimination (#include, #define, #ifdef, etc.)
    - Complex pointer types (e.g., const char *, int **, unsigned long long *)
    - Multi-word type specifiers (e.g., unsigned long int, long double)
    - Function attribute macro stripping (e.g., __attribute__((visibility("default"))), WINAPI)
    """

    def __init__(self, file_path: Union[str, Path]):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"C source or header file not found: {self.file_path}")
        self.raw_content = self.file_path.read_text(encoding='utf-8', errors='ignore')
        self.cleaned_content = ""

    def _preprocess(self) -> str:
        """Strips comments, preprocessor directives, and compiler-specific macro bloat."""
        code = self.raw_content
        
        # 1. Remove multi-line comments /* ... */
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        
        # 2. Remove single-line comments // ...
        code = re.sub(r'//.*$', '', code, flags=re.MULTILINE)
        
        # 3. Handle line continuations (\ followed by newline)
        code = re.sub(r'\\\s*\n', ' ', code)
        
        # 4. Strip preprocessor directives (#include, #define, #if, #endif, etc.)
        lines = code.split('\n')
        filtered_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#'):
                # Keep track or skip; we skip directives for signature parsing
                continue
            filtered_lines.append(line)
        code = '\n'.join(filtered_lines)
        
        # 5. Strip compiler attribute macros like __attribute__((...)) or __declspec(...)
        code = re.sub(r'__attribute__\s*\(\(.*?\)\)', '', code, flags=re.DOTALL)
        code = re.sub(r'__declspec\s*\(.*?\)', '', code, flags=re.DOTALL)
        code = re.sub(r'\b(WINAPI|APIENTRY|CALLBACK)\b', '', code)
        
        return code

    def parse(self) -> List[Dict[str, Any]]:
        """Parses the cleaned C code and extracts a structured list of function signatures."""
        self.cleaned_content = self._preprocess()
        
        # Regex strategy:
        # Matches: [return_type(s)] [function_name] ([arguments]) followed by either a semicolon or opening brace.
        # Group 1: Return type specifiers (e.g. "unsigned int", "const char*", "void")
        # Group 2: Function identifier name
        # Group 3: Parameter list string inside parentheses
        pattern = r'([a-zA-Z_]\w*(?:\s+\*+)?(?:\s+(?:const|volatile|unsigned|signed|struct|union|enum))*\s*(?:\s*\*+\s*|\b[a-zA-Z_]\w*\b)*)\s+([a-zA-Z_]\w*)\s*\(([^)]*)\)\s*(?:;|{)'
        
        raw_matches = re.findall(pattern, self.cleaned_content)
        functions: List[Dict[str, Any]] = []
        seen_signatures: Set[str] = set()

        for raw_ret, name, raw_args in raw_matches:
            ret_type = ' '.join(raw_ret.split())
            name = name.strip()
            
            # Filter out control keywords erroneously caught as functions
            if name in C_KEYWORDS or ret_type in C_KEYWORDS:
                continue
            
            # Prevent duplicate entries if both declaration and definition exist in header/source
            if name in seen_signatures:
                continue
            seen_signatures.add(name)

            args = []
            raw_args_trimmed = raw_args.strip()
            
            if raw_args_trimmed and raw_args_trimmed.lower() != 'void':
                # Split parameters by comma, handling potential nested structures or pointer arrays safely
                param_list = [p.strip() for p in raw_args_trimmed.split(',')]
                
                for param_idx, param in enumerate(param_list):
                    if not param or param == '...':
                        continue
                        
                    # Normalize whitespace
                    param_clean = '️ '.join(param.split())
                    
                    # Separate type from variable name
                    # Example: "const char *filename" -> type: "const char *", name: "filename"
                    # Example: "int arr[]" -> type: "int*", name: "arr"
                    parts = param.split()
                    if len(parts) >= 2:
                        arg_name_raw = parts[-1]
                        
                        # Handle array notation like arr[] or arr[10]
                        is_array = False
                        if '[' in arg_name_raw and ']' in arg_name_raw:
                            is_array = True
                            arg_name_raw = arg_name_raw.split('[')[0]
                            
                        arg_name = arg_name_raw.lstrip('*').strip()
                        if not arg_name or not arg_name.isidentifier():
                            arg_name = f"arg_{param_idx}"
                            
                        # Reconstruct full type including any attached asterisks
                        type_parts = parts[:-1]
                        stars_in_name = arg_name_raw[:len(arg_name_raw) - len(arg_name)]
                        if stars_in_name:
                            type_parts.append(stars_in_name)
                            
                        arg_type = ' '.join(type_parts).strip()
                        is_pointer = '*' in arg_type or '*' in stars_in_name or is_array
                        
                        args.append({
                            'type': arg_type,
                            'name': arg_name,
                            'is_pointer': is_pointer,
                            'is_array': is_array
                        })
                    elif len(parts) == 1:
                        # Edge case: anonymous parameter types in declarations like "int, double"
                        arg_type = parts[0]
                        args.append({
                            'type': arg_type,
                            'name': f"arg_{param_idx}",
                            'is_pointer': '*' in arg_type,
                            'is_array': False
                        })

            functions.append({
                'return_type': ret_type,
                'name': name,
                'args': args,
                'signature_hash': f"{ret_type} {name}({len(args)}args)"
            })

        return functions

    def dump_debug_info(self) -> Dict[str, Any]:
        """Returns diagnostic data regarding the scanned file for robust troubleshooting."""
        return {
            "file_path": str(self.file_path),
            "total_lines": len(self.raw_content.splitlines()),
            "cleaned_length": len(self.cleaned_content),
  }
      
