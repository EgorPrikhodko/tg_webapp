# backend/api.py
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status, Query
from pydantic import BaseModel, Field, conint, field_validator
from sqlalchemy import select, update, delete, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import User, Category, Product

router = APIRouter(tags=["api"])

# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные утилиты: доступ к сессии и правам
# ──────────────────────────────────────────────────────────────────────────────

def _parse_moder_ids(raw: str) -> List[int]:
    out: List[int] = []
    for part in (raw or "").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            continue
    return out

MODERATOR_IDS: List[int] = _parse_moder_ids(os.getenv("MODERATOR_IDS", ""))


async def get_session(request: Request) -> AsyncSession:
    """Берём sessionmaker, который ты положил в app.state.sessionmaker в main.py"""
    sm = getattr(request.app.state, "sessionmaker", None)
    if sm is None:
        raise RuntimeError("Sessionmaker не найден. В main.py добавь: app.state.sessionmaker = AsyncSessionLocal")
    async with sm() as session:  # type: AsyncSession
        yield session


async def get_tg_id(
    x_telegram_id: Optional[int] = Header(None, convert_underscores=False, alias="X-Telegram-Id"),
    tg_id_q: Optional[int] = Query(None, alias="tg_id"),  # на случай тестов из браузера
) -> Optional[int]:
    """Получаем Telegram ID из заголовка X-Telegram-Id или query-параметра tg_id (для локальных тестов)."""
    return x_telegram_id or tg_id_q


async def require_admin(tg_id: Optional[int] = Depends(get_tg_id)) -> int:
    if tg_id is None:
        raise HTTPException(status_code=401, detail="Не передан Telegram ID (X-Telegram-Id)")
    if tg_id not in MODERATOR_IDS:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return tg_id


# ──────────────────────────────────────────────────────────────────────────────
# Схемы (Pydantic)
# ──────────────────────────────────────────────────────────────────────────────

# Users
class EnsureUserIn(BaseModel):
    tg_id: conint(gt=0)


class EnsureUserOut(BaseModel):
    id: int
    tg_id: int
    is_admin: bool
    is_active: bool


# Categories
class CategoryIn(BaseModel):
    name: str = Field(..., max_length=200)
    slug: str = Field(..., max_length=200)
    parent_id: Optional[int] = None


class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str
    parent_id: Optional[int]


# Products
class ProductIn(BaseModel):
    title: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=255)
    description: Optional[str] = None
    price: float = Field(ge=0)
    currency: str = Field("RUB", min_length=3, max_length=3)
    stock: int = Field(0, ge=0)
    is_active: bool = True
    images: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None
    category_id: int

    @field_validator("images")
    @classmethod
    def _validate_images(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        return [s for s in v if isinstance(s, str) and s.strip()]


class ProductOut(BaseModel):
    id: int
    title: str
    slug: str
    description: Optional[str]
    price: float
    currency: str
    stock: int
    is_active: bool
    images: Optional[List[str]]
    attributes: Optional[Dict[str, Any]]
    category_id: int


# ──────────────────────────────────────────────────────────────────────────────
# Users
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/users/ensure", response_model=EnsureUserOut)
async def ensure_user(payload: EnsureUserIn, session: AsyncSession = Depends(get_session)):
    """Зарегистрировать пользователя по tg_id, если его ещё нет (используй при первом входе в WebApp)."""
    q = select(User).where(User.tg_id == payload.tg_id)
    res = await session.execute(q)
    user = res.scalar_one_or_none()
    if not user:
        user = User(tg_id=payload.tg_id, is_admin=(payload.tg_id in MODERATOR_IDS))
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return EnsureUserOut(
        id=user.id,
        tg_id=user.tg_id,
        is_admin=bool(user.is_admin),
        is_active=bool(user.is_active),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Categories
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/categories", response_model=List[CategoryOut])
async def list_categories(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Category).order_by(Category.id))
    rows = res.scalars().all()
    return [CategoryOut(id=r.id, name=r.name, slug=r.slug, parent_id=r.parent_id) for r in rows]


@router.post("/categories", response_model=CategoryOut)
async def create_category(
    payload: CategoryIn,
    _: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    cat = Category(name=payload.name, slug=payload.slug, parent_id=payload.parent_id)
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return CategoryOut(id=cat.id, name=cat.name, slug=cat.slug, parent_id=cat.parent_id)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int,
    payload: CategoryIn,
    _: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    q = select(Category).where(Category.id == category_id)
    res = await session.execute(q)
    cat = res.scalar_one_or_none()
    if not cat:
        raise HTTPException(404, "Категория не найдена")

    cat.name = payload.name
    cat.slug = payload.slug
    cat.parent_id = payload.parent_id
    await session.commit()
    await session.refresh(cat)
    return CategoryOut(id=cat.id, name=cat.name, slug=cat.slug, parent_id=cat.parent_id)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    _: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(delete(Category).where(Category.id == category_id))
    await session.commit()
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Products
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/products", response_model=List[ProductOut])
async def list_products(
    q: Optional[str] = Query(None, description="Поиск по названию/описанию"),
    category_id: Optional[int] = Query(None),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    is_active: Optional[bool] = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    conds = []
    if is_active is not None:
        conds.append(Product.is_active == is_active)
    if category_id is not None:
        conds.append(Product.category_id == category_id)
    if min_price is not None:
        conds.append(Product.price >= Decimal(str(min_price)))
    if max_price is not None:
        conds.append(Product.price <= Decimal(str(max_price)))
    if q:
        conds.append(or_(Product.title.ilike(f"%{q}%"), Product.description.ilike(f"%{q}%")))

    stmt = (
        select(Product)
        .where(and_(*conds) if conds else True)
        .order_by(Product.id.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await session.execute(stmt)
    rows = res.scalars().all()

    def _to_out(p: Product) -> ProductOut:
        price = float(p.price) if isinstance(p.price, Decimal) else float(p.price or 0)
        return ProductOut(
            id=p.id,
            title=p.title,
            slug=p.slug,
            description=p.description,
            price=price,
            currency=p.currency,
            stock=p.stock,
            is_active=bool(p.is_active),
            images=p.images,
            attributes=p.attributes,
            category_id=p.category_id,
        )

    return [_to_out(p) for p in rows]


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(product_id: int, session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Product).where(Product.id == product_id))
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Товар не найден")
    price = float(p.price) if isinstance(p.price, Decimal) else float(p.price or 0)
    return ProductOut(
        id=p.id,
        title=p.title,
        slug=p.slug,
        description=p.description,
        price=price,
        currency=p.currency,
        stock=p.stock,
        is_active=bool(p.is_active),
        images=p.images,
        attributes=p.attributes,
        category_id=p.category_id,
    )


@router.post("/products", response_model=ProductOut)
async def create_product(
    payload: ProductIn,
    _: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    p = Product(
        title=payload.title,
        slug=payload.slug,
        description=payload.description,
        price=Decimal(str(payload.price)),
        currency=payload.currency.upper(),
        stock=payload.stock,
        is_active=payload.is_active,
        images=payload.images,
        attributes=payload.attributes,
        category_id=payload.category_id,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return ProductOut(
        id=p.id,
        title=p.title,
        slug=p.slug,
        description=p.description,
        price=float(p.price),
        currency=p.currency,
        stock=p.stock,
        is_active=bool(p.is_active),
        images=p.images,
        attributes=p.attributes,
        category_id=p.category_id,
    )


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int,
    payload: ProductIn,
    _: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(Product).where(Product.id == product_id))
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Товар не найден")

    p.title = payload.title
    p.slug = payload.slug
    p.description = payload.description
    p.price = Decimal(str(payload.price))
    p.currency = payload.currency.upper()
    p.stock = payload.stock
    p.is_active = payload.is_active
    p.images = payload.images
    p.attributes = payload.attributes
    p.category_id = payload.category_id

    await session.commit()
    await session.refresh(p)
    return ProductOut(
        id=p.id,
        title=p.title,
        slug=p.slug,
        description=p.description,
        price=float(p.price),
        currency=p.currency,
        stock=p.stock,
        is_active=bool(p.is_active),
        images=p.images,
        attributes=p.attributes,
        category_id=p.category_id,
    )


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    _: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(delete(Product).where(Product.id == product_id))
    await session.commit()
    return None
