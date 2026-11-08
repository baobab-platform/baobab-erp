"""Immutable effective-dated workforce proposals and authority ports."""
from .model import EmploymentVersion, PeopleDomainError
from .service import WorkforceService

__all__ = ["EmploymentVersion", "PeopleDomainError", "WorkforceService"]
