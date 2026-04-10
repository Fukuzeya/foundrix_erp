"""Account and AccountTag repositories."""

import uuid
from sqlalchemy import Select, or_, select, func
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.account import Account, AccountTag


class AccountRepository(BaseRepository[Account]):
    model = Account

    async def find_by_code(self, code: str) -> Account | None:
        result = await self.db.execute(
            select(self.model).where(self.model.code == code)
        )
        return result.scalar_one_or_none()

    def build_filtered_query(
        self,
        *,
        search: str | None = None,
        account_type: str | None = None,
        internal_group: str | None = None,
        reconcile: bool | None = None,
        is_active: bool | None = True,
    ) -> Select:
        query = select(self.model)
        if search:
            term = f"%{search}%"
            query = query.where(or_(
                self.model.code.ilike(term),
                self.model.name.ilike(term),
            ))
        if account_type:
            query = query.where(self.model.account_type == account_type)
        if internal_group:
            query = query.where(self.model.internal_group == internal_group)
        if reconcile is not None:
            query = query.where(self.model.reconcile.is_(reconcile))
        if is_active is not None:
            query = query.where(self.model.is_active.is_(is_active))
        return query.order_by(self.model.code)

    async def get_by_internal_group(self, group: str) -> list[Account]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.internal_group == group, self.model.is_active.is_(True))
            .order_by(self.model.code)
        )
        return list(result.scalars().all())

    async def get_receivable_payable(self) -> list[Account]:
        result = await self.db.execute(
            select(self.model).where(
                self.model.account_type.in_(["asset_receivable", "liability_payable"]),
                self.model.is_active.is_(True),
            ).order_by(self.model.code)
        )
        return list(result.scalars().all())


class AccountTagRepository(BaseRepository[AccountTag]):
    model = AccountTag

    async def find_by_name(self, name: str, applicability: str = "accounts") -> AccountTag | None:
        result = await self.db.execute(
            select(self.model).where(
                self.model.name == name,
                self.model.applicability == applicability,
            )
        )
        return result.scalar_one_or_none()
