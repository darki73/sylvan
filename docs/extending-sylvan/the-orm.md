# The ORM

The ORM is fully async, uses the active record pattern, and talks to the
database through a pluggable `StorageBackend`. Filter methods are synchronous
(they build SQL); terminal methods are async (they execute it).

## Defining a model

```python
from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column, JsonColumn
from sylvan.database.orm.primitives.relations import BelongsTo, HasMany
from sylvan.database.orm.primitives.scopes import scope


class Repo(Model):
    __table__ = "repos"

    id = AutoPrimaryKey()
    name = Column(type=str)
    source_path = Column(type=str, nullable=True)
    file_count = Column(type=int, default=0)
    settings = JsonColumn(inner_type=dict, nullable=True)

    files = HasMany("File", foreign_key="repo_id")
```

### Column types

| Declaration | Python type | DB type |
|---|---|---|
| `Column(type=str)` | `str` | TEXT NOT NULL |
| `Column(type=int)` | `int` | INTEGER NOT NULL |
| `Column(type=float)` | `float` | REAL NOT NULL |
| `Column(type=bool)` | `bool` | INTEGER NOT NULL (0/1) |
| `Column(type=bytes)` | `bytes` | BLOB NOT NULL |
| `Column(type=str, nullable=True)` | `str \| None` | TEXT |
| `Column(type=int, default=0)` | `int` | INTEGER NOT NULL DEFAULT 0 |
| `Column(type=str, column_name="db_col")` | `str` | uses `db_col` in SQL |
| `AutoPrimaryKey()` | `int` | INTEGER PRIMARY KEY (auto-increment) |
| `JsonColumn(inner_type=list)` | `list` | TEXT (auto JSON serialize/deserialize) |
| `JsonColumn(inner_type=dict)` | `dict` | TEXT (auto JSON serialize/deserialize) |

### Relations

```python
class File(Model):
    __table__ = "files"

    id = AutoPrimaryKey()
    repo_id = Column(type=int)
    path = Column(type=str)

    # Many-to-one: each file belongs to one repo
    repo = BelongsTo("Repo", foreign_key="repo_id")

    # One-to-many: each file has many symbols
    symbols = HasMany("Symbol", foreign_key="file_id")

    # One-to-one: each file has one quality record
    quality = HasOne("QualityRecord", foreign_key="file_id")
```

```python
# Many-to-many through a pivot table
class Workspace(Model):
    __table__ = "workspaces"

    id = AutoPrimaryKey()
    name = Column(type=str)

    repos = BelongsToMany(
        "Repo",
        pivot_table="workspace_repos",
        foreign_key="workspace_id",
        related_key="repo_id",
    )
```

Relations are lazy by default. Access them after loading:

```python
repo = await Repo.find(1)
await repo.load("files")       # load the relation
files = repo.files              # now accessible
```

### Scopes

Scopes are reusable query fragments defined on the model:

```python
class Symbol(Model):
    __table__ = "symbols"

    id = AutoPrimaryKey()
    name = Column(type=str)
    kind = Column(type=str)
    repo_id = Column(type=int)

    @scope
    def functions(query):
        return query.where(kind="function")

    @scope
    def in_repo(query, repo_name):
        return query.join("repos", "repos.id = symbols.repo_id").where("repos.name", repo_name)
```

Use them as chainable methods:

```python
results = await Symbol.functions().in_repo("my-project").limit(10).get()
```

## QueryBuilder

Every `Model.where(...)` call returns a `QueryBuilder`. Chain filter methods
(sync), then call a terminal (async).

### Basic queries

```python
# All records
repos = await Repo.all().get()

# Filter with kwargs
functions = await Symbol.where(kind="function", language="python").get()

# Filter with operator
large = await Symbol.where("line_count", ">", 100).get()

# First result
repo = await Repo.where(name="sylvan").first()

# Find by primary key
repo = await Repo.find(42)
repo = await Repo.find_or_fail(42)  # raises if not found
```

### Where variants

```python
# IN clause
await Symbol.where_in("kind", ["function", "method"]).get()

# NOT equal
await Symbol.where_not(kind="constant").get()

# LIKE pattern
await Symbol.where_like("name", "test_%").get()

# NULL checks
await Symbol.where_null("summary").get()
await Symbol.where_not_null("docstring").get()

# BETWEEN
await Symbol.where_between("line_count", 10, 100).get()

# Subquery IN
subquery = Repo.where(name="sylvan").to_subquery("id")
await Symbol.where_in_subquery("repo_id", subquery).get()

# Grouped conditions (parenthesized)
await Symbol.where(kind="function").where_group(
    lambda q: q.where_like("name", "test_%").or_where(language="typescript")
).get()
```

### Joins, ordering, grouping

```python
# Join
await Symbol.where(kind="class").join(
    "files", "files.id = symbols.file_id"
).get()

# Left join
await Symbol.where(kind="function").left_join(
    "quality_records", "quality_records.symbol_id = symbols.id"
).get()

# Order
await Symbol.all().order_by("name", "ASC").get()
await Symbol.all().order_by_desc("line_count").get()

# Group
await Symbol.all().select("kind").group_by("kind").get()

# Limit and offset
await Symbol.all().limit(20).offset(40).get()
```

### Select and raw select

```python
# Select specific columns
await Symbol.all().select("name", "kind").get()

# Raw SQL expression in select
await Symbol.all().select_raw("COUNT(*) as total").group_by("kind").get()
```

### Aggregates

```python
# Single aggregates
count = await Symbol.where(kind="function").count()
total = await Symbol.where(repo_id=1).sum("line_count")
average = await Symbol.where(kind="class").avg("complexity")
biggest = await Symbol.where(repo_id=1).max("line_count")
smallest = await Symbol.where(repo_id=1).min("line_count")

# With group_by, aggregates return dicts
counts = await Symbol.all().group_by("kind").count()
# => {"function": 120, "class": 45, "method": 300, ...}
```

### Multi-aggregate

```python
from sylvan.database.orm.query.execution import Sum, Avg, Count, Max

stats = await Symbol.where(repo_id=1).aggregates(
    total_lines=Sum("line_count"),
    avg_complexity=Avg("complexity"),
    symbol_count=Count("*"),
    max_lines=Max("line_count"),
)
# => {"total_lines": 5000, "avg_complexity": 3.2, "symbol_count": 500, "max_lines": 200}
```

### Subqueries

```python
# Build a subquery without executing
subquery = Symbol.where(kind="function").to_subquery("file_id")

# Use in another query
files = await File.where_in_subquery("id", subquery).get()
```

### Search

```python
# FTS5 full-text search
results = await Symbol.search("parse json config").get()

# Vector similarity search
results = await Symbol.similar_to("function that parses configuration", k=20).get()

# Combine search with filters
results = await (
    Symbol.search("authentication")
    .where(kind="function")
    .where(language="python")
    .limit(10)
    .get()
)
```

### Eager loading

```python
# Load relations in batch (avoids N+1)
symbols = await Symbol.where(kind="class").with_("file").get()
for s in symbols:
    print(s.file.path)  # already loaded, no extra query

# Count related records
repos = await Repo.all().with_count("files").get()
```

### Pagination

```python
page = await Symbol.where(kind="function").paginate(page=2, per_page=20)
# => {
#     "data": [...],        # list of Symbol instances
#     "total": 500,         # total matching records
#     "page": 2,
#     "per_page": 20,
#     "total_pages": 25,
# }
```

### Conditional queries

```python
include_tests = True
results = await (
    Symbol.where(kind="function")
    .when(include_tests, lambda q: q.where_like("name", "test_%"))
    .get()
)
```

### Exists and pluck

```python
# Check existence without loading records
has_py = await Symbol.where(language="python").exists()

# Get a flat list of one column
names = await Symbol.where(kind="class").pluck("name")
# => ["Model", "QueryBuilder", "Schema", ...]
```

### Chunked processing

```python
async def process_batch(symbols):
    for s in symbols:
        print(s.name)

await Symbol.all().chunk(100, process_batch)
```

## CRUD operations

### Create

```python
repo = await Repo.create(name="my-project", source_path="/code/my-project")
```

### Save (insert or update)

```python
repo = Repo(name="my-project", source_path="/code")
await repo.save()        # INSERT (no id yet)

repo.file_count = 42
await repo.save()        # UPDATE (has id now)
```

### Update

```python
# Instance update
repo = await Repo.find(1)
await repo.update(file_count=100, source_path="/new/path")

# Bulk update via query
await Symbol.where(repo_id=1).update(summary=None)
```

### Delete

```python
# Instance delete
repo = await Repo.find(1)
await repo.delete()

# Bulk delete via query
count = await Symbol.where(repo_id=1).delete()
```

### Upsert

```python
repo = await Repo.upsert(
    conflict_columns=["name"],
    update_columns=["source_path", "file_count"],
    name="my-project",
    source_path="/updated/path",
    file_count=50,
)
```

### Insert or ignore / replace

```python
# Skip if exists
await Repo.insert_or_ignore(name="my-project", source_path="/code")

# Replace if exists
await Repo.insert_or_replace(name="my-project", source_path="/new/code")
```

### First or create / update or create

```python
# Find or create
repo = await Repo.first_or_create(
    search_by={"name": "my-project"},
    source_path="/code",
)

# Find and update, or create
repo = await Repo.update_or_create(
    search_by={"name": "my-project"},
    source_path="/updated/path",
)
```

## Bulk operations

```python
# Insert many records at once
count = await Symbol.bulk_create([
    {"name": "foo", "kind": "function", "repo_id": 1, "file_id": 1},
    {"name": "bar", "kind": "function", "repo_id": 1, "file_id": 1},
    {"name": "Baz", "kind": "class", "repo_id": 1, "file_id": 1},
])

# Upsert many at once
count = await Symbol.bulk_upsert(
    records=[
        {"symbol_id": "a::foo#function", "name": "foo", "kind": "function"},
        {"symbol_id": "a::bar#function", "name": "bar", "kind": "function"},
    ],
    conflict_columns=["symbol_id"],
    update_columns=["name", "kind"],
)

# Update many rows with different values per row
count = await Symbol.bulk_update(
    records=[
        {"id": 1, "summary": "Updated summary for foo"},
        {"id": 2, "summary": "Updated summary for bar"},
    ],
)

# Specify a custom primary key column
count = await Symbol.bulk_update(
    records=[
        {"symbol_id": "a::foo#function", "summary": "new summary"},
        {"symbol_id": "a::bar#function", "summary": "new summary"},
    ],
    pk_column="symbol_id",
)
```

`bulk_update` generates a single `UPDATE ... SET col = CASE WHEN pk = ? THEN ? ... END`
statement per batch, which is far more efficient than individual `update()` calls when
you need to set different values on each row.

## Raw SQL

For queries the builder cannot express:

```python
results = await Symbol.raw(
    "SELECT * FROM symbols WHERE name LIKE ? AND repo_id = ?",
    ["%test%", 1],
)
```

## Query debugging

```python
# Enable query logging
QueryBuilder.enable_debug()

# Run queries...
await Symbol.where(kind="function").get()

# Read the log
for sql, params in QueryBuilder.get_query_log():
    print(sql, params)

# Clean up
QueryBuilder.clear_query_log()
QueryBuilder.disable_debug()
```

## Inspecting SQL without executing

```python
sql, params = Symbol.where(kind="function").order_by("name").to_sql()
print(sql)     # SELECT ... FROM symbols WHERE kind = ? ORDER BY name ASC
print(params)  # ['function']
```
