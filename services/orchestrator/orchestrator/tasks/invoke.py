"""Credential decryption and retrieval utilities."""

from __future__ import annotations

from uuid import UUID

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import AgentCredential, ConsumerCredential

log = structlog.get_logger()


def decrypt_credential(encrypted_value: bytes, encryption_key: str) -> str:
    """Decrypt a single credential value using Fernet symmetric encryption.

    Parameters
    ----------
    encrypted_value:
        The ciphertext stored in the database (``AgentCredential.encrypted_value``).
    encryption_key:
        The Fernet-compatible key string (base64-encoded 32-byte key).

    Returns
    -------
    str
        The plaintext credential value.

    Raises
    ------
    ValueError
        If decryption fails (bad key or corrupted data).
    """
    try:
        fernet = Fernet(encryption_key.encode())
        return fernet.decrypt(encrypted_value).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        raise ValueError(f"Failed to decrypt credential: {exc}") from exc


async def get_agent_credentials(
    session: AsyncSession,
    agent_id: UUID,
    encryption_key: str,
) -> dict[str, str]:
    """Load and decrypt all credentials for a given agent.

    Parameters
    ----------
    session:
        An active SQLAlchemy async session.
    agent_id:
        The agent's primary key.
    encryption_key:
        The Fernet encryption key used to decrypt stored values.

    Returns
    -------
    dict[str, str]
        Mapping of ``credential_name`` to the decrypted plaintext value.
    """
    stmt = select(AgentCredential).where(AgentCredential.agent_id == agent_id)
    result = await session.execute(stmt)
    credentials = result.scalars().all()

    decrypted: dict[str, str] = {}
    for cred in credentials:
        try:
            decrypted[cred.credential_name] = decrypt_credential(
                cred.encrypted_value, encryption_key
            )
        except ValueError:
            log.error(
                "credential.decrypt_failed",
                agent_id=str(agent_id),
                credential_name=cred.credential_name,
            )
            # Skip credentials that cannot be decrypted rather than
            # aborting the entire invocation.
            continue

    return decrypted


async def get_consumer_credentials(
    session: AsyncSession,
    account_id: UUID,
    encryption_key: str,
) -> dict[str, str]:
    """Load and decrypt all credentials for a given consumer account.

    Returns a dict with keys prefixed by ``CONSUMER_CRED_``.
    """
    stmt = select(ConsumerCredential).where(ConsumerCredential.account_id == account_id)
    result = await session.execute(stmt)
    credentials = result.scalars().all()

    decrypted: dict[str, str] = {}
    for cred in credentials:
        try:
            value = decrypt_credential(cred.encrypted_value, encryption_key)
            decrypted[f"CONSUMER_CRED_{cred.service_name}"] = value
        except ValueError:
            log.error(
                "consumer_credential.decrypt_failed",
                account_id=str(account_id),
                service_name=cred.service_name,
            )
            continue

    return decrypted
