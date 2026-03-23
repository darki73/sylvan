"""Lifecycle hooks for ORM models -- removed (zero callers).

The HookMixin was never used by any concrete model. The _fire_hook()
bridge in Model.base still exists as a no-op for forward compatibility.
"""
