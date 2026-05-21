---
name: docs
description: Writes or updates docstrings for Python functions, methods, and modules following Google-style conventions. Use when asked to document code, add docstrings, or when the user says "document this", "add docs", or "write documentation" for any Python file or function.
---

## Style rules
- Follow PEP 257 and Google-style docstrings.
- Be short and concise. No filler phrases like "This function is responsible for...".
- One-line summary first. Add Args/Returns/Raises only when not obvious from names and type hints.
- Never document what the code obviously does — only what isn't clear from reading it.
- Do not add docstrings to trivial properties or `__init__` that only assigns attributes.

## Format

### Functions and methods
```python
def process_stock_update(product_id: str, delta: int) -> Product:
    """Apply a stock delta to a product and return the updated document.

    Args:
        delta: Positive to add stock, negative to remove.

    Returns:
        The updated Product document after persistence.

    Raises:
        ProductNotFoundError: If no product matches product_id.
        InsufficientStockError: If the resulting stock would be negative.
    """
```
## When to document Args
- Document a parameter if its name alone doesn't explain its meaning or valid range
- Skip if the name + type hint is self-explanatory (e.g. `product_id: str`, `active: bool`)

## When to document Returns
- Skip if the return type hint is sufficient
- Add if the return value has non-obvious semantics (e.g. what "updated document" means in context)

## When to document Raises
- Document all raises if there are 2 or more possible exceptions
- Skip if there's only one obvious exception and the function name implies it

### Modules
One or two sentences at the top describing what the module owns. No author, no date, no version.