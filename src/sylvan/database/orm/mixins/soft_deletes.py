"""Soft delete support for ORM models -- removed (zero callers).

The SoftDeleteMixin was never mixed into any concrete model.
The delete() method in persistence.py still checks __soft_deletes__
for forward compatibility but no model sets it.
"""
