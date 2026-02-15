"""CLI script to create an AgentGate account and issue an API key.

Usage:
    uv run python scripts/create_account.py --email user@example.com --password secret123 --role consumer
"""

import argparse
import asyncio
import hashlib
import sys
import uuid

from sqlalchemy import select

from ag_common.auth import generate_api_key
from ag_common.config import BaseConfig
from ag_db.models import Account, ApiKey, LedgerAccount
from ag_db.session import create_engine_and_session


async def create_account(email: str, password: str, role: str) -> None:
    config = BaseConfig()
    engine, session_factory = create_engine_and_session(config.database_url)

    async with session_factory() as session:
        # Check if account exists
        result = await session.execute(select(Account).where(Account.email == email))
        if result.scalar_one_or_none():
            print(f"Error: Account with email {email} already exists")
            sys.exit(1)

        # Create account
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        account = Account(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            role=role,
        )
        session.add(account)

        # Create API key
        full_key, key_prefix, key_hash = generate_api_key()
        api_key = ApiKey(
            id=uuid.uuid4(),
            account_id=account.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
        )
        session.add(api_key)

        # Create ledger accounts
        if role == "consumer":
            ledger_types = ["consumer_balance", "held_funds"]
        elif role == "developer":
            ledger_types = ["developer_earnings"]
        else:
            ledger_types = ["consumer_balance", "held_funds", "developer_earnings", "platform_revenue"]

        for acct_type in ledger_types:
            la = LedgerAccount(
                id=uuid.uuid4(),
                account_id=account.id,
                account_type=acct_type,
            )
            session.add(la)

        await session.commit()

        print(f"Account created successfully!")
        print(f"  Account ID: {account.id}")
        print(f"  Email:      {email}")
        print(f"  Role:       {role}")
        print(f"  API Key:    {full_key}")
        print()
        print("IMPORTANT: Save this API key — it cannot be retrieved again.")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an AgentGate account")
    parser.add_argument("--email", required=True, help="Account email")
    parser.add_argument("--password", required=True, help="Account password")
    parser.add_argument(
        "--role",
        choices=["consumer", "developer", "admin"],
        default="consumer",
        help="Account role (default: consumer)",
    )
    args = parser.parse_args()

    asyncio.run(create_account(args.email, args.password, args.role))


if __name__ == "__main__":
    main()
