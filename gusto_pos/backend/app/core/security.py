"""Password and PIN hashing.

bcrypt for everything new; sha256_crypt accepted only long enough to rehash an
existing login into bcrypt; md5_crypt not accepted at all.

WHAT WAS HERE BEFORE
--------------------
    pwd_context = CryptContext(schemes=["sha256_crypt", "md5_crypt"], ...)

passlib uses the FIRST scheme for new hashes, so every password and every staff
PIN written by this codebase was sha256_crypt, and md5_crypt hashes still
verified. Both are fast by design. Applied to a 4-DIGIT PIN — which is what
StaffService.create_staff stores — the entire 10,000-value keyspace falls in
negligible time against a stolen hash, and the production database credential
was committed to a public repository, so "stolen hash" is not hypothetical.

requirements.txt pins `passlib[bcrypt]` and `bcrypt==4.3.0` with the comment
"staff login depends on this pair", and there was a commented-out bcrypt
context at the top of this file. The intent was always bcrypt; the active code
had drifted away from it.

WHY THE CONTEXT IS SHAPED THIS WAY
----------------------------------
The obvious spelling — schemes=["bcrypt"], deprecated=["sha256_crypt",
"md5_crypt"] — raises at import:

    KeyError: deprecated scheme not found in policy: 'sha256_crypt'

passlib requires a deprecated scheme to also be listed in `schemes`, because
`deprecated` means "still verifiable, but rehash it", not "rejected". So
sha256_crypt is listed and marked deprecated: existing logins keep working and
are upgraded in place on the next successful sign-in (see verify_and_rehash).

md5_crypt is simply absent, which is what "dropped entirely" has to mean — an
md5 hash now raises UnknownHashError and cannot be verified at any cost.

  !! OPERATIONAL NOTE. If any account in a live database still holds an
  !! md5_crypt hash, that account can no longer log in and needs a password
  !! reset. md5_crypt was in the accepted list, so such rows are possible;
  !! whether any exist has NOT been verified against production.

bcrypt's own $2a$/$2b$ hashes are handled natively by passlib here. The
hand-rolled `if hashed_password.startswith("$2b$")` branch that used to sit in
verify_password is gone — it called bcrypt.checkpw directly and swallowed every
exception as a False, which turned a misconfigured backend into a silent
"wrong password" for every user.
"""
from typing import Optional, Tuple

from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["bcrypt", "sha256_crypt"],
    deprecated=["sha256_crypt"],
    # bcrypt's cost factor. 12 is ~250ms on current hardware — deliberately
    # slow, which is the entire point for a 4-digit PIN.
    bcrypt__rounds=12,
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """True if the password matches.

    Returns False rather than raising for a hash this context cannot read (an
    md5_crypt leftover, or a corrupt value), so a bad row in the users table is
    a failed login rather than a 500.
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        # passlib raises UnknownHashError (a ValueError) for an unrecognised or
        # malformed hash.
        return False


def verify_and_rehash(
    plain_password: str, hashed_password: str
) -> Tuple[bool, Optional[str]]:
    """Verify, and hand back a bcrypt replacement when the stored hash is stale.

    Returns ``(ok, new_hash)``. ``new_hash`` is None when the password was
    wrong OR the stored hash is already bcrypt at the current cost — so a
    caller writes to the database only when there is something to change.

    This is the migration path. Existing sha256_crypt rows cannot be converted
    in bulk: the plaintext is not recoverable, so the ONLY moment a bcrypt hash
    can be computed is the instant someone successfully signs in and the
    plaintext is briefly in hand. Callers that skip this keep every legacy row
    on the weak algorithm indefinitely.
    """
    if not verify_password(plain_password, hashed_password):
        return False, None
    if pwd_context.needs_update(hashed_password):
        return True, pwd_context.hash(plain_password)
    return True, None


def get_password_hash(password: str) -> str:
    """Hash with the default scheme — bcrypt."""
    return pwd_context.hash(password)
