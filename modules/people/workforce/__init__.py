"""Immutable effective-dated workforce aggregates and authority ports."""
from .model import EmploymentVersion, PeopleDomainError
from .service import WorkforceService

__all__ = ["EmploymentVersion", "PeopleDomainError", "WorkforceService"]
