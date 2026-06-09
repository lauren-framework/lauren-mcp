# Decorators in Depth

Lauren MCP exposes three method-level decorators — `@mcp_tool`, `@mcp_resource`,
and `@mcp_prompt` — and one class-level decorator — `@mcp_server`.  This guide
covers every option each decorator accepts, how schema generation works, and
common patterns.

---

## `@mcp_server`

Marks a class as an MCP server endpoint.  Must appear on the class before any
method decorators.

```python
from lauren_mcp import mcp_server

@mcp_server("/mcp")
class MyServer:
    ...
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | — | Mount path; WebSocket will be at `{path}/ws` |
| `transport` | `str` | `"ws"` | `"ws"`, `"sse"`, or `"both"` |

The decorator also applies `@injectable(scope=Scope.SINGLETON)` so the class
participates in the Lauren DI container — constructor dependencies are resolved
automatically.

```python
from lauren_mcp import mcp_server

# WebSocket only (default)
@mcp_server("/mcp")
class MyServer: ...

# HTTP+SSE only
@mcp_server("/mcp", transport="sse")
class MyServer: ...

# Both transports
@mcp_server("/mcp", transport="both")
class MyServer: ...
```

---

## `@mcp_tool`

Exposes an `async` method as a callable tool.  The JSON Schema is generated
automatically from type annotations.

### Signature

```python
def mcp_tool(*, name: str | None = None, description: str | None = None)
```

### Basic usage

```python
from lauren_mcp import mcp_tool

@mcp_tool()
async def greet(self, name: str) -> str:
    """Greet someone by name.

    Args:
        name: The person's name.
    """
    return f"Hello, {name}!"
```

### Override name and description

```python
@mcp_tool(name="catalogue_search", description="Full-text search across items.")
async def search(self, query: str) -> list[dict]:
    ...
```

### All supported parameter types

```python
@mcp_tool()
async def example(
    self,
    # Scalar types
    text: str,              # → {"type": "string"}
    count: int,             # → {"type": "integer"}
    ratio: float,           # → {"type": "number"}
    flag: bool,             # → {"type": "boolean"}
    # Collections
    tags: list[str],        # → {"type": "array"}
    metadata: dict,         # → {"type": "object"}
    # Optional (not required in schema)
    note: str | None = None,
    limit: int = 10,
) -> dict:
    ...
```

### Required vs optional parameters

Parameters **without** a default are **required** in the generated schema.
Parameters **with** a default (including `None`) are **optional**:

```python
@mcp_tool()
async def create_order(
    self,
    product_id: int,        # required
    quantity: int,          # required
    discount: float = 0.0,  # optional
    notes: str | None = None, # optional
) -> dict:
    """Create a new order.

    Args:
        product_id: The product to order.
        quantity: How many units.
        discount: Discount percentage (0–100).
        notes: Optional order notes.
    """
    ...
```

Generated schema:

```json
{
  "type": "object",
  "properties": {
    "product_id": {"type": "integer"},
    "quantity": {"type": "integer"},
    "discount": {"type": "number"},
    "notes": {"type": "string"}
  },
  "required": ["product_id", "quantity"]
}
```

### Docstring Args section

Place argument descriptions in a Google-style `Args:` section.  They are
extracted and stored in `ToolMeta` (not currently sent on the wire but useful
for code readers):

```python
@mcp_tool()
async def translate(self, text: str, target_lang: str = "en") -> str:
    """Translate text to another language.

    Args:
        text: The source text to translate.
        target_lang: BCP-47 language code for the target language.
    """
    ...
```

---

## `@mcp_resource`

Exposes an `async` method as a readable MCP resource at a given URI template.

### Signature

```python
def mcp_resource(
    uri_template: str,
    *,
    name: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
)
```

### Basic usage

```python
from lauren_mcp import mcp_resource

@mcp_resource("/items/{item_id}")
async def item_resource(self, item_id: str) -> str:
    """Return an item's description as plain text.

    Args:
        item_id: Extracted from the URI path.
    """
    item = db.get(item_id)
    return f"{item['name']}: {item['description']}"
```

URI template variables are **always passed as strings** (extracted from the
URI) regardless of how you annotate them.  Cast inside the method body:

```python
@mcp_resource("/orders/{order_id}")
async def order_resource(self, order_id: str) -> str:
    order = await db.get_order(int(order_id))   # cast here
    ...
```

### Multiple path segments

```python
@mcp_resource("/catalogue/{category}/{item_id}")
async def item_by_category(self, category: str, item_id: str) -> str:
    ...
```

### MIME type

```python
import json

@mcp_resource("/products/{sku}", mime_type="application/json")
async def product_json(self, sku: str) -> str:
    product = await catalogue.get_product(sku)
    return json.dumps(product)
```

### Not-found handling

Return a descriptive string — the client receives it as the resource content:

```python
@mcp_resource("/items/{item_id}")
async def item_resource(self, item_id: str) -> str:
    item = db.get(item_id)
    if item is None:
        return f"Item '{item_id}' not found."
    return f"{item['name']}: £{item['price']:.2f}"
```

---

## `@mcp_prompt`

Exposes an `async` method as a reusable LLM prompt template.  The method
should return a string or a list of message dicts.

### Signature

```python
def mcp_prompt(name: str | None = None, *, description: str | None = None)
```

### Return a plain string

The server wraps a string return value into a single `user` message:

```python
from lauren_mcp import mcp_prompt

@mcp_prompt()
async def summarise(self, topic: str) -> str:
    """Generate a summarisation prompt.

    Args:
        topic: What to summarise.
    """
    return f"Please write a concise summary about: {topic}"
```

Rendered result structure:

```json
{
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "Please write..."}}
  ]
}
```

### Return a message list

For multi-turn prompts return a list of `{"role", "content"}` dicts directly:

```python
@mcp_prompt()
async def code_review(self, language: str, code: str) -> list[dict]:
    """A multi-turn code review prompt.

    Args:
        language: Programming language of the code.
        code: Source code to review.
    """
    return [
        {
            "role": "user",
            "content": {"type": "text", "text": (
                f"Please review this {language} code and list any bugs:\n\n```\n{code}\n```"
            )},
        }
    ]
```

### Optional vs required arguments

Arguments without a default are **required**; those with a default are
**optional** in the prompt's argument list:

```python
@mcp_prompt()
async def email_draft(
    self,
    recipient: str,         # required
    subject: str,           # required
    tone: str = "formal",   # optional
) -> str:
    """Draft a professional email.

    Args:
        recipient: Who the email is addressed to.
        subject: The email subject line.
        tone: Writing tone (default "formal").
    """
    return (
        f"Draft a {tone} email to {recipient} about: {subject}. "
        "Keep it under 200 words."
    )
```

### Override name

```python
@mcp_prompt(name="product_pitch")
async def pitch(self, product: str) -> str:
    ...
```

---

## Putting it all together

A complete server using all four decorators:

```python
from __future__ import annotations

from lauren import Lauren
from lauren_mcp import (
    mcp_server, mcp_tool, mcp_resource, mcp_prompt, McpServerModule
)

PRODUCTS = [
    {"id": "p1", "name": "Laptop Pro", "price": 999.00, "category": "electronics"},
    {"id": "p2", "name": "Wireless Mouse", "price": 29.99, "category": "electronics"},
    {"id": "p3", "name": "Notebook", "price": 4.99, "category": "stationery"},
]


@mcp_server("/mcp")
class ShopServer:

    # ----- tools -----

    @mcp_tool()
    async def search(self, query: str, category: str | None = None) -> list[dict]:
        """Search products by name.

        Args:
            query: Search terms.
            category: Optional category filter.
        """
        results = [p for p in PRODUCTS if query.lower() in p["name"].lower()]
        if category:
            results = [p for p in results if p["category"] == category]
        return results

    @mcp_tool()
    async def get_product(self, product_id: str) -> dict | None:
        """Fetch a product by its ID.

        Args:
            product_id: The product identifier (e.g. "p1").
        """
        return next((p for p in PRODUCTS if p["id"] == product_id), None)

    # ----- resources -----

    @mcp_resource("/products/{product_id}", mime_type="text/plain")
    async def product_card(self, product_id: str) -> str:
        """One-line product card for a given ID.

        Args:
            product_id: Product identifier extracted from URI.
        """
        p = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if p is None:
            return f"Product {product_id!r} not found."
        return f"{p['name']} — £{p['price']:.2f} ({p['category']})"

    # ----- prompts -----

    @mcp_prompt()
    async def recommend(self, budget: str) -> str:
        """Generate a product recommendation prompt.

        Args:
            budget: Customer's maximum budget in GBP (e.g. "50").
        """
        affordable = [p for p in PRODUCTS if p["price"] <= float(budget)]
        names = ", ".join(p["name"] for p in affordable) or "none"
        return (
            f"Recommend a product to a customer with a £{budget} budget. "
            f"Available items: {names}."
        )


app = Lauren()
app.include_module(McpServerModule.for_root(ShopServer))
```

---

## Next steps

- **[Multiple servers](multiple-servers.md)** — tool namespacing across servers
- **[Testing](testing.md)** — test all four decorator types
