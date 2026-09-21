"""Who is acting. §1024.38(c) wants the servicing file to show what happened; "what happened" includes who
approved the triage and who signed the exception. Until now the actor was a string in the request body —
self-reported, which is no identity at all. Now it comes from the credential.

Bearer tokens, three roles, one env var. `OPERATOR_TOKENS="<token>:<name>:<role>;..."`:

    readonly    can read cases, audit, documents, templates
    operator    + intake, approve a proposal, send letters, respond, transition
    supervisor  + approve with an exception code — declining a notice or request under §1024.35(g) /
                  §1024.36(f) is a determination the servicer makes, not a triage edit

Static tokens are the demo-scale answer; the shape (a Principal with a name and a role, resolved by a
dependency) is what an OIDC/SSO integration would fill in instead. Nothing below this layer knows the
difference: service functions take `operator=principal.name`, and the audit row records it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request

from .config import settings

Role = Literal["readonly", "operator", "supervisor"]
RANK: dict[str, int] = {"readonly": 0, "operator": 1, "supervisor": 2}


@dataclass(frozen=True)
class Principal:
    name: str
    role: Role

    def can(self, role: Role) -> bool:
        return RANK[self.role] >= RANK[role]


def parse_tokens(spec: str) -> dict[str, Principal]:
    out: dict[str, Principal] = {}
    for entry in filter(None, (e.strip() for e in spec.split(";"))):
        try:
            token, name, role = (p.strip() for p in entry.split(":"))
        except ValueError as e:
            raise ValueError(f"OPERATOR_TOKENS entry {entry!r}: want token:name:role") from e
        if role not in RANK:
            raise ValueError(f"OPERATOR_TOKENS entry for {name!r}: unknown role {role!r}")
        out[token] = Principal(name, role)  # type: ignore[arg-type]
    return out


def principal(request: Request) -> Principal:
    """Resolve the bearer token. No configured tokens is a deployment error, not open access."""
    tokens = parse_tokens(settings.operator_tokens)
    if not tokens:
        raise HTTPException(503, "OPERATOR_TOKENS is not configured; the desk refuses to run without identities")
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "bearer token required", headers={"WWW-Authenticate": "Bearer"})
    p = tokens.get(token.strip())
    if p is None:
        raise HTTPException(401, "unknown token", headers={"WWW-Authenticate": "Bearer"})
    return p


def require(role: Role):
    def _dep(p: Principal = Depends(principal)) -> Principal:
        if not p.can(role):
            raise HTTPException(403, f"{p.name} is {p.role}; this needs {role}")
        return p

    return _dep


Reader = Depends(require("readonly"))
Operator = Depends(require("operator"))
