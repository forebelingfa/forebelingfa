---
name: python-comment-annotator
description: >-
  Adds Pythonic structural annotations to code in other languages using
  comments. This helps Python developers understand the logic and flow of
  non-Python code by providing the equivalent Python syntax in comments above
  the relevant blocks.
disabled: true
---

# Python Comment Annotator

Translate the "shape" of code into Python for easier comprehension by Python developers.

## Intent
When a user provides code in a language other than Python, this skill should annotate that code by inserting comments immediately preceding major structural elements. These comments must contain the equivalent Python code that represents that structure.

## Rules of Engagement

1. **Identify Language**: Determine the source language (Rust, Go, C++, JS, etc.).

2. **Structural Analysis**: Locate key programming constructs:
   - Functions/Methods/Closures
   - Classes/Structs/Interfaces
   - Control Flow (if/else, loops, switch/match)
   - Error Handling (try/catch, Result/Option, err != nil)
   - Async/Await patterns
   - Module entry points (main)

3. **Python Translation**: For each construct, generate the idiomatic Python equivalent.

4. **Comment Injection**:
   - Use the target language's comment syntax (e.g., `//` for C-style, `#` for Python, `--` for SQL).
   - Place the comment(s) *immediately above* the code block they describe.
   - The Python code in the comment should be a structural "sketch" (accurate representation of the logic).

5. **No Human Language**: Do NOT use English descriptions in the comments. Use **only** the Python equivalent.

6. **Preservation**: Do NOT modify the original code. The output must be the complete, original code with only the new comments added.

## Examples

### Example 1: Rust
**Input:**
```rust
#[tokio::main]
async fn main() {
    println!("Hello, world!");
}
```

**Output:**
```rust
// if __name__ == "__main__":
//     asyncio.run(main())
#[tokio::main]
async fn main() {
    println!("Hello, world!");
}
```

### Example 2: Go
**Input:**
```go
func add(a, b int) int {
    return a + b
}
```

**Output:**
```go
// def add(a: int, b: int) -> int:
//     ...
func add(a, b int) int {
    return a + b
}
```

### Example 3: JavaScript
**Input:**
```javascript
const fetchData = async (url) => {
  const response = await fetch(url);
  return response.json();
};
```

**Output:**
```javascript
// async def fetch_data(url):
//     ...
const fetchData = async (url) => {
  const response = await fetch(url);
  return response.json();
};
```

## Quality Checklist

- [ ] Is the original code completely unchanged?
- [ ] Are the comments using the correct comment syntax for the language?
- [ ] Do the comments contain *only* Python code?
- [ ] Is every major structural block annotated?
- [ ] Does the Python "sketch" accurately reflect the logic of the original block?
