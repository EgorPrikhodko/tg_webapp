# backend/models.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ──────────────────────────────────────────────────────────────────────────────
# Базовый класс
# ──────────────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Модель пользователя (покупатель/админ)
# ──────────────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)

    # базовые флаги
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    # системные метки времени (UTC)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # удобнее дебажить
        return f"<User id={self.id} tg_id={self.tg_id} admin={self.is_admin}>"


# ──────────────────────────────────────────────────────────────────────────────
# Категории (дерево: parent → children)
# ──────────────────────────────────────────────────────────────────────────────
class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_categories_slug"),
        Index("ix_categories_parent", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)

    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)

    # связи
    parent: Mapped[Optional["Category"]] = relationship(
        back_populates="children", remote_side="Category.id"
    )
    children: Mapped[List["Category"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )

    # системные метки времени
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # товары в категории
    products: Mapped[List["Product"]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"<Category id={self.id} slug='{self.slug}'>"


# ──────────────────────────────────────────────────────────────────────────────
# Товары
# ──────────────────────────────────────────────────────────────────────────────
class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_products_slug"),
        Index("ix_products_category", "category_id"),
        Index("ix_products_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # базовые поля карточки
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # цена и остатки
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, server_default="0.00")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'RUB'"))
    stock: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    # изображения (массив URL-ов) и произвольные атрибуты для фильтров
    images: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)         # ["https://...jpg", ...]
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)     # {"brand":"...", "size":"M", ...}

    # связь с категорией
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    category: Mapped["Category"] = relationship(back_populates="products")

    # системные метки времени
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Product id={self.id} slug='{self.slug}' active={self.is_active}>"


# ──────────────────────────────────────────────────────────────────────────────
# Утилита: первичное создание таблиц без Alembic (по желанию)
# Если нужно быстро поднять таблицы до миграций — вызовем init_db(engine).
# На следующем шаге настроим Alembic и миграции.
# ──────────────────────────────────────────────────────────────────────────────
async def init_db(engine) -> None:
    """
    Создать все таблицы согласно моделям.
    В продакшене используем Alembic миграции — это временная помощь на старте.
    """
    from sqlalchemy.ext.asyncio import AsyncEngine

    if not isinstance(engine, AsyncEngine):
        raise TypeError("init_db ожидает AsyncEngine")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
