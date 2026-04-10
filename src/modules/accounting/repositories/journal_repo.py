"""Journal repository."""

from sqlalchemy import select
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.journal import Journal


class JournalRepository(BaseRepository[Journal]):
    model = Journal

    async def find_by_code(self, code: str) -> Journal | None:
        result = await self.db.execute(
            select(self.model).where(self.model.code == code)
        )
        return result.scalar_one_or_none()

    async def get_by_type(self, journal_type: str) -> list[Journal]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.journal_type == journal_type, self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[Journal]:
        result = await self.db.execute(
            select(self.model)
            .where(self.model.is_active.is_(True))
            .order_by(self.model.sequence, self.model.name)
        )
        return list(result.scalars().all())
