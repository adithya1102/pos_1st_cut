from uuid import UUID
from typing import Any, List
from datetime import datetime
import os
import json as _json
from sqlalchemy import select, update, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from app.modules.orders.model import Order
from app.modules.order_items.model import OrderItem
from app.modules.sessions.models import WaiterNotification
from app.modules.tables.models import TableSession
from app.core.websocket_manager import kitchen_manager, customer_manager, pos_manager, waiter_manager
from app.modules.orders.schema import OrderCreate, OrderUpdate, OrderItemCreate

OUTLET_ID = "0b8a8349-6144-41a8-b028-b9089bd8eaea"


class OrderService:
    @staticmethod
    async def get_all_orders(db: AsyncSession):
        result = await db.execute(
            select(Order).options(selectinload(Order.items))
        )
        return result.scalars().all()

    @staticmethod
    async def get_order_by_id(db: AsyncSession, order_id: UUID):
        result = await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_order(db: AsyncSession, payload: OrderCreate):
        import json

        source = (payload.source or "customer").strip()

        # "One Active Table = One Active Order" — merge into existing open order if present.
        existing = None
        if payload.table_id:
            r = await db.execute(
                select(Order)
                .options(selectinload(Order.items))
                .where(
                    Order.table_id == payload.table_id,
                    Order.outlet_id == payload.outlet_id,
                    Order.order_status.notin_(["paid", "cancelled"]),
                )
                .order_by(Order.created_at.desc())
                .limit(1)
            )
            existing = r.scalar_one_or_none()

        if existing:
            obj = existing
        else:
            obj = Order(
                outlet_id=payload.outlet_id,
                table_id=payload.table_id,
                customer_id=payload.customer_id,
                total_amount=0,
                order_status=payload.order_status.value if payload.order_status else "pending",
                kitchen_token=payload.kitchen_token,
                source=source,
            )
            db.add(obj)
            await db.flush()

        # Append new items and accumulate their total
        notif_items = []
        new_items_total = 0.0
        if payload.items:
            for item_data in payload.items:
                notes_dict: dict = {}
                if item_data.customizations:
                    notes_dict["customizations"] = item_data.customizations
                if item_data.custom_note:
                    notes_dict["custom_note"] = item_data.custom_note
                item_notes = json.dumps(notes_dict) if notes_dict else None
                db.add(OrderItem(
                    order_id=obj.id,
                    name_snap=item_data.name,
                    price_snap=item_data.unit_price,
                    quantity=item_data.quantity,
                    item_notes=item_notes,
                ))
                new_items_total += item_data.unit_price * item_data.quantity
                notif_items.append({
                    "name": item_data.name,
                    "quantity": item_data.quantity,
                    "unit_price": item_data.unit_price,
                    "customizations": item_data.customizations or [],
                    "custom_note": item_data.custom_note or "",
                })

        obj.total_amount = float(obj.total_amount) + new_items_total
        db.add(obj)

        # Only notify the waiter when the order came from a customer (not from the waiter app itself)
        if source != "waiter":
            db.add(WaiterNotification(
                outlet_id=obj.outlet_id,
                table_id=str(obj.table_id) if obj.table_id else "",
                customer_name="Customer",
                customer_id=str(obj.customer_id) if obj.customer_id else "",
                notif_type="order_placed",
                order_id=obj.id,
                total_amount=obj.total_amount,
                order_preview=_json.dumps(notif_items),
            ))

        await db.commit()
        result = await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == obj.id)
        )
        order = result.scalar_one()

        await kitchen_manager.broadcast_new_order(
            outlet_id=str(order.outlet_id),
            order={
                "id": str(order.id),
                "kitchen_token": order.kitchen_token,
                "table_id": str(order.table_id) if order.table_id else None,
                "customer_id": str(order.customer_id) if order.customer_id else None,
                "total_amount": float(order.total_amount),
                "order_status": order.order_status,
                "created_at": order.created_at,
            }
        )

        order_event_payload = {
            "id": str(order.id),
            "table_id": str(order.table_id) if order.table_id else None,
            "order_status": order.order_status,
            "total_amount": float(order.total_amount),
            "source": source,
        }
        await pos_manager.broadcast_order_event(
            outlet_id=str(order.outlet_id),
            event="NEW_ORDER",
            order=order_event_payload,
        )
        await waiter_manager.broadcast_order_event(
            outlet_id=str(order.outlet_id),
            event="NEW_ORDER",
            order=order_event_payload,
        )

        await customer_manager.notify_order_confirmed(
            order_id=str(order.id),
            order={
                "order_status": str(order.order_status),
                "kitchen_token": order.kitchen_token,
            }
        )

        # Mark table occupied on all floor views so the UI turns Red immediately
        if order.table_id:
            table_occupied = {"table_id": str(order.table_id), "status": "occupied"}
            await pos_manager.broadcast_order_event(
                str(order.outlet_id), "TABLE_STATUS_CHANGED", table_occupied
            )
            await waiter_manager.broadcast_order_event(
                str(order.outlet_id), "TABLE_STATUS_CHANGED", table_occupied
            )

        return order

    @staticmethod
    async def update_order(db: AsyncSession, order_id: UUID, payload: OrderUpdate):
        obj = await OrderService.get_order_by_id(db, order_id)
        if not obj:
            return None
        order_status_changed = False
        for k, v in payload.model_dump(exclude_unset=True).items():
            if k == "order_status" and v is not None:
                v = v.value if hasattr(v, "value") else v
                if getattr(obj, "order_status", None) != v:
                    order_status_changed = True
            setattr(obj, k, v)
        db.add(obj)
        await db.commit()
        result = await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        order = result.scalar_one()

        if order_status_changed:
            await kitchen_manager.broadcast_status_update(
                outlet_id=str(order.outlet_id),
                order={
                    "id": str(order.id),
                    "kitchen_token": order.kitchen_token,
                    "order_status": order.order_status,
                }
            )
            await customer_manager.notify_status_changed(
                order_id=str(order.id),
                order={
                    "order_status": str(order.order_status),
                    "kitchen_token": order.kitchen_token,
                }
            )
        return order

    @staticmethod
    async def replace_order_items(db: AsyncSession, order_id: UUID, items: List[OrderItemCreate]):
        """Delete all existing order items, insert the new list, and recalculate total_amount."""
        order = await OrderService.get_order_by_id(db, order_id)
        if not order:
            return None
        await db.execute(sa_delete(OrderItem).where(OrderItem.order_id == order_id))
        total = 0.0
        for item_data in items:
            notes_dict: dict = {}
            if item_data.customizations:
                notes_dict["customizations"] = item_data.customizations
            if item_data.custom_note:
                notes_dict["custom_note"] = item_data.custom_note
            item_notes = _json.dumps(notes_dict) if notes_dict else None
            db.add(OrderItem(
                order_id=order_id,
                name_snap=item_data.name,
                price_snap=item_data.unit_price,
                quantity=item_data.quantity,
                item_notes=item_notes,
            ))
            total += item_data.unit_price * item_data.quantity
        order.total_amount = total
        db.add(order)
        await db.commit()
        result = await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        return result.scalar_one()

    @staticmethod
    async def delete_order(db: AsyncSession, order_id: UUID) -> bool:
        result = await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        obj = result.scalar_one_or_none()
        if not obj:
            return False
        await db.delete(obj)
        await db.commit()
        return True

    @staticmethod
    async def get_orders_by_table(db: AsyncSession, table_id: str):
        """Get all unpaid orders for a table with their items."""
        result = await db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.table_id == table_id,
                Order.outlet_id == UUID(OUTLET_ID),
                Order.order_status != "paid",
            )
        )
        return result.scalars().all()

    @staticmethod
    async def settle_table(db: AsyncSession, table_id: str):
        """Mark all unpaid orders as paid, close the table session, and broadcast availability."""
        result = await db.execute(
            select(Order)
            .where(
                Order.table_id == table_id,
                Order.outlet_id == UUID(OUTLET_ID),
                Order.order_status != "paid",
            )
        )
        orders = result.scalars().all()
        total = 0.0
        for order in orders:
            order.order_status = "paid"
            total += float(order.total_amount)
            db.add(order)

        # Close any active table session so the table shows as available everywhere
        sessions_result = await db.execute(
            select(TableSession).where(
                TableSession.outlet_id == UUID(OUTLET_ID),
                TableSession.table_id == table_id,
                TableSession.is_active == True,
            )
        )
        for session in sessions_result.scalars().all():
            session.is_active = False
            session.closed_at = datetime.utcnow()

        await db.commit()

        # Notify all floor views to turn the table Green
        await pos_manager.broadcast_order_event(OUTLET_ID, "TABLE_CLOSED", {"table_id": table_id})
        await waiter_manager.broadcast_order_event(OUTLET_ID, "TABLE_CLOSED", {"table_id": table_id})

        return len(orders), total

    @staticmethod
    async def generate_bill(db: AsyncSession, table_id: str):
        """Generate a professional PDF bill for all unpaid orders on a table."""
        result = await db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.table_id == table_id,
                Order.outlet_id == UUID(OUTLET_ID),
                Order.order_status != "paid",
            )
        )
        orders = result.scalars().all()
        if not orders:
            return None

        # Collect all items from all orders, merging duplicates
        all_items = []
        order_ids = []
        for order in orders:
            order_ids.append(str(order.readable_id))
            for item in order.items:
                name = item.name_snap or "Item"
                qty = item.quantity or 1
                rate = float(item.price_snap or 0)
                amount = rate * qty
                existing = next((i for i in all_items if i["name"] == name), None)
                if existing:
                    existing["qty"] += qty
                    existing["amount"] += amount
                else:
                    all_items.append({
                        "name": name,
                        "qty": qty,
                        "rate": rate,
                        "amount": amount,
                    })

        # Fallback if no items stored � use order totals
        if not all_items:
            for order in orders:
                all_items.append({
                    "name": f"Order #{order.readable_id}",
                    "qty": 1,
                    "rate": float(order.total_amount),
                    "amount": float(order.total_amount),
                })

        subtotal = sum(i["amount"] for i in all_items)
        cgst = round(subtotal * 0.025, 2)
        sgst = round(subtotal * 0.025, 2)
        grand_total = subtotal + cgst + sgst
        net_payable = round(grand_total)
        round_off = round(net_payable - grand_total, 2)
        bill_no = "-".join(order_ids)
        now = datetime.now()

        # Create bills directory
        bills_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "bills",
        )
        os.makedirs(bills_dir, exist_ok=True)
        safe_table = table_id.replace("-", "")
        filename = f"bill_{safe_table}_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(bills_dir, filename)

        # ?? Build PDF (80mm receipt) ????????????????????????????
        page_width = 80 * mm
        page_height = (200 + len(all_items) * 16) * mm
        c = canvas.Canvas(pdf_path, pagesize=(page_width, page_height))
        y = page_height - 10 * mm
        lh = 5 * mm  # line height

        def center(text, size=8, bold=False):
            nonlocal y
            font = "Courier-Bold" if bold else "Courier"
            c.setFont(font, size)
            tw = c.stringWidth(text, font, size)
            c.drawString((page_width - tw) / 2, y, text)
            y -= lh

        def hline():
            nonlocal y
            c.setLineWidth(0.5)
            c.line(5 * mm, y + 3 * mm, page_width - 5 * mm, y + 3 * mm)
            y -= 2 * mm

        def dline():
            nonlocal y
            c.setLineWidth(0.5)
            c.line(5 * mm, y + 4.5 * mm, page_width - 5 * mm, y + 4.5 * mm)
            c.line(5 * mm, y + 3 * mm, page_width - 5 * mm, y + 3 * mm)
            y -= 2 * mm

        def left_right(left, right, size=7, bold=False):
            nonlocal y
            font = "Courier-Bold" if bold else "Courier"
            c.setFont(font, size)
            c.drawString(5 * mm, y, left)
            c.drawRightString(page_width - 5 * mm, y, right)
            y -= lh

        # Header
        center("RUDRARTHI", 12, bold=True)
        center("Fine Dining Restaurant", 8)
        center("123 Anna Salai, Chennai, TN", 7)
        center("Ph: +91 98765 43210", 7)
        center("GSTIN: 33AAAAA0000A1Z5", 7)
        hline()

        # Bill info
        c.setFont("Courier", 7)
        c.drawString(5 * mm, y, f"Bill No : {bill_no}")
        y -= lh
        c.drawString(5 * mm, y, f"Date    : {now.strftime('%d-%m-%Y')}    Time: {now.strftime('%H:%M')}")
        y -= lh
        c.drawString(5 * mm, y, f"Table   : {table_id}")
        y -= lh
        hline()

        # Column headers
        c.setFont("Courier-Bold", 7)
        c.drawString(5 * mm, y, "ITEM")
        c.drawString(42 * mm, y, "QTY")
        c.drawString(52 * mm, y, "RATE")
        c.drawString(64 * mm, y, "AMT")
        y -= lh
        hline()

        # Item rows
        for item in all_items:
            name = item["name"][:18]
            c.setFont("Courier", 7)
            c.drawString(5 * mm, y, name)
            c.drawString(43 * mm, y, str(item["qty"]))
            c.drawString(51 * mm, y, f"{item['rate']:.0f}")
            c.drawString(63 * mm, y, f"{item['amount']:.0f}")
            y -= lh

        hline()

        # Totals
        def total_row(label, amount, bold=False):
            left_right(label, f": {amount:.2f}", size=7, bold=bold)

        total_row("Subtotal", subtotal)
        total_row("CGST (2.5%)", cgst)
        total_row("SGST (2.5%)", sgst)
        hline()
        left_right("GRAND TOTAL", f": {grand_total:.2f}", size=8, bold=True)
        total_row("Round Off", round_off)
        dline()
        left_right("NET PAYABLE", f": {net_payable:.2f}", size=9, bold=True)
        y -= lh
        hline()

        # Footer
        center("Thank you for dining with us!", 8)
        center("Visit us again!", 8)

        c.showPage()
        c.save()

        return {
            "pdf_path": pdf_path,
            "total": net_payable,
            "items": all_items,
            "bill_no": bill_no,
        }
