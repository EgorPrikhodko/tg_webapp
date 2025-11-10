# backend/api.py
from __future__ import annotations

import os
import json
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
    Query,
)
from pydantic import BaseModel, Field, conint, field_validator
from sqlalchemy import select, update, delete, and_, or_, func, insert
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
    """
    Берём sessionmaker, который кладётся в app.state.sessionmaker в main.py.
    """
    sm = getattr(request.app.state, "sessionmaker", None)
    if sm is None:
        raise RuntimeError(
            "Sessionmaker не найден. В main.py добавь: app.state.sessionmaker = AsyncSessionLocal"
        )
    async with sm() as session:  # type: AsyncSession
        yield session


async def get_tg_id(
    x_telegram_id: Optional[int] = Header(None, convert_underscores=False, alias="X-Telegram-Id"),
    tg_id_q: Optional[int] = Query(None, alias="tg_id"),  # на случай ручных тестов из браузера
) -> Optional[int]:
    """Telegram ID из заголовка X-Telegram-Id или query-параметра tg_id."""
    return x_telegram_id or tg_id_q


async def require_admin(tg_id: Optional[int] = Depends(get_tg_id)) -> int:
    if tg_id is None:
        raise HTTPException(status_code=401, detail="Не передан Telegram ID (X-Telegram-Id)")
    if tg_id not in MODERATOR_IDS:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return tg_id


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────
_slug_re = re.compile(r"[^a-z0-9\-]+")

def slugify(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"\s+", "-", v)
    v = _slug_re.sub("-", v)
    v = re.sub(r"-{2,}", "-", v).strip("-")
    return v or "item"

async def parse_json_or_form(request: Request, allowed_fields: List[str]) -> Dict[str, Any]:
    """
    Универсальный парсер: JSON или multipart/form-data → dict.
    Разрешён только белый список полей.
    """
    ctype = (request.headers.get("content-type") or "").lower()
    data: Dict[str, Any]
    if "application/json" in ctype:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(422, "JSON payload must be an object")
    elif "multipart/form-data" in ctype:
        form = await request.form()
        data = {k: form.get(k) for k in allowed_fields if k in form}
    else:
        # Для простоты поддержим и application/x-www-form-urlencoded
        if "application/x-www-form-urlencoded" in ctype:
            form = await request.form()
            data = {k: form.get(k) for k in allowed_fields if k in form}
        else:
            raise HTTPException(415, "Unsupported Media Type")
    # Оставим только разрешённые поля
    return {k: v for k, v in data.items() if k in allowed_fields}


def to_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in {"1", "true", "on", "yes"}

def to_int_or_none(v: Any) -> Optional[int]:
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(v)
    except Exception:
        return None

def to_float(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", ".")
    return float(s)

def parse_json_field(v: Any) -> Optional[dict | list]:
    if v is None or v == "":
        return None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(str(v))
    except Exception:
        return None


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


# Products (вход мягко валидируется)
class ProductIn(BaseModel):
    title: str = Field(..., max_length=255)
    slug: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    price: float = Field(ge=0)
    currency: str = Field("RUB", min_length=3, max_length=3)
    stock: int = Field(0, ge=0)
    is_active: bool = True
    images: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None
    category_id: Optional[int] = None  # разрешим None → проверим сами

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("title is required")
        return v

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: Optional[str], info):
        if v is None or not str(v).strip():
            # сгенерируем потом из title (в эндпоинте), здесь только очистим
            return None
        return str(v).strip()

    @field_validator("description")
    @classmethod
    def _desc(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None

    @field_validator("price")
    @classmethod
    def _price(cls, v):
        if isinstance(v, str):
            v = v.strip().replace(",", ".")
        return float(v)

    @field_validator("stock")
    @classmethod
    def _stock(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return 0
        return int(v)

    @field_validator("currency")
    @classmethod
    def _curr(cls, v: str) -> str:
        v = (v or "RUB").strip().upper()
        if len(v) != 3:
            raise ValueError("currency must be 3 letters")
        return v

    @field_validator("category_id")
    @classmethod
    def _cat(cls, v):
        if v in ("", None):
            return None
        return int(v)

    @field_validator("images")
    @classmethod
    def _images(cls, v):
        # допускаем JSON-строку или список
        if v is None or v == "":
            return None
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(s).strip() for s in parsed if str(s).strip()]
                return None
            except Exception:
                return None
        if isinstance(v, list):
            return [str(s).strip() for s in v if str(s).strip()]
        return None

    @field_validator("attributes")
    @classmethod
    def _attrs(cls, v):
        # допускаем JSON-строку или dict
        if v is None or v == "":
            return None
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
                return None
            except Exception:
                return None
        if isinstance(v, dict):
            return v
        return None


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
    """Зарегистрировать пользователя по tg_id, если его ещё нет (первый вход в WebApp)."""
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


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(
    request: Request,
    _: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    # Разрешённый набор полей с формы/JSON:
    allowed = [
        "title", "slug", "description", "price", "currency",
        "stock", "is_active", "images", "attributes", "category_id",
    ]
    raw = await parse_json_or_form(request, allowed)

    # Мягкая нормализация
    payload = ProductIn(
        title=str(raw.get("title", "")),
        slug=(raw.get("slug") or None),
        description=(raw.get("description") or None),
        price=to_float(raw.get("price", 0)),
        currency=str(raw.get("currency", "RUB")).upper(),
        stock=int(to_int_or_none(raw.get("stock")) or 0),
        is_active=to_bool(raw.get("is_active")),
        images=(parse_json_field(raw.get("images")) if isinstance(raw.get("images"), str) else raw.get("images")),
        attributes=(parse_json_field(raw.get("attributes")) if isinstance(raw.get("attributes"), str) else raw.get("attributes")),
        category_id=to_int_or_none(raw.get("category_id")),
    )

    if payload.category_id is None:
        raise HTTPException(422, detail="category_id is required")

    # slug по умолчанию из title
    slug = payload.slug or slugify(payload.title)

    p = Product(
        title=payload.title,
        slug=slug,
        description=payload.description,
        price=Decimal(str(payload.price)),
        currency=payload.currency,
        stock=payload.stock,
        is_active=payload.is_active,
        images=payload.images,
        attributes=payload.attributes,
        category_id=payload.category_id,  # type: ignore[arg-type]
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
    request: Request,
    _: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(Product).where(Product.id == product_id))
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Товар не найден")

    allowed = [
        "title", "slug", "description", "price", "currency",
        "stock", "is_active", "images", "attributes", "category_id",
    ]
    raw = await parse_json_or_form(request, allowed)

    # Обновляем только присланные поля (с мягким приведением типов)
    if "title" in raw:
        p.title = str(raw["title"]).strip()
    if "slug" in raw:
        s = str(raw["slug"]).strip()
        p.slug = s or slugify(p.title)
    if "description" in raw:
        desc = str(raw["description"]).strip()
        p.description = desc or None
    if "price" in raw:
        p.price = Decimal(str(to_float(raw["price"])))
    if "currency" in raw:
        p.currency = str(raw["currency"]).strip().upper() or p.currency
    if "stock" in raw:
        iv = to_int_or_none(raw["stock"])
        p.stock = int(iv or 0)
    if "is_active" in raw:
        p.is_active = to_bool(raw["is_active"])
    if "images" in raw:
        p.images = parse_json_field(raw["images"]) if isinstance(raw["images"], str) else raw["images"]
    if "attributes" in raw:
        p.attributes = parse_json_field(raw["attributes"]) if isinstance(raw["attributes"], str) else raw["attributes"]
    if "category_id" in raw:
        cid = to_int_or_none(raw["category_id"])
        if cid is None:
            raise HTTPException(422, detail="category_id must be int")
        p.category_id = cid

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
