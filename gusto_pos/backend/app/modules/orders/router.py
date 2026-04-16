

@router.get("/history/{outlet_id}")
async def get_order_history(outlet_id: str, date: str = None, table_id: str = None, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, date as date_type
    import datetime as dt
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        target_date = dt.date.today()
    start = datetime.combine(target_date, dt.time.min)
    end = datetime.combine(target_date, dt.time.max)
    query = select(Order).where(
        Order.outlet_id == outlet_id,
        Order.created_at >= start,
        Order.created_at <= end
    ).order_by(Order.created_at.asc())
    if table_id:
        query = query.where(Order.table_id == table_id)
    result = await db.execute(query)
    orders = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "readable_id": getattr(o, "readable_id", None),
            "table_id": o.table_id,
            "total_amount": float(o.total_amount) if o.total_amount else 0,
            "status": o.status,
            "payment_method": getattr(o, "payment_method", "cash"),
            "created_at": o.created_at.isoformat() if o.created_at else None
        }
        for o in orders
    ]


@router.get("/summary/{outlet_id}")
async def get_order_summary(outlet_id: str, date: str = None, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, date as date_type
    import datetime as dt
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        target_date = dt.date.today()
    start = datetime.combine(target_date, dt.time.min)
    end = datetime.combine(target_date, dt.time.max)
    result = await db.execute(
        select(Order).where(
            Order.outlet_id == outlet_id,
            Order.created_at >= start,
            Order.created_at <= end
        )
    )
    orders = result.scalars().all()
    total_revenue = sum(float(o.total_amount or 0) for o in orders)
    cash = sum(float(o.total_amount or 0) for o in orders if getattr(o, "payment_method", "cash") == "cash")
    card = sum(float(o.total_amount or 0) for o in orders if getattr(o, "payment_method", "cash") == "card")
    upi = sum(float(o.total_amount or 0) for o in orders if getattr(o, "payment_method", "cash") == "upi")
    active = sum(1 for o in orders if o.status != "paid")
    settled = sum(1 for o in orders if o.status == "paid")
    return {
        "total_orders": len(orders),
        "total_revenue": total_revenue,
        "cash_total": cash,
        "card_total": card,
        "upi_total": upi,
        "active_orders": active,
        "settled_orders": settled
    }
