import pathlib

f = pathlib.Path(__file__).parent / 'controller.py'
txt = f.read_text()

marker = '@router.put("/{item_id}", response_model=OrderRead)'
new_ep = '''
@router.post("/{order_id}/confirm")
async def confirm_order(order_id: UUID, db: AsyncSession = Depends(get_db)):
    """Confirm an order - updates status from pending to confirmed."""
    obj = await OrderService.get_order_by_id(db, order_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    obj.order_status = "confirmed"
    await db.commit()
    return {"message": "Order confirmed", "order_id": str(order_id), "status": "confirmed"}


'''

if '@router.post("/{order_id}/confirm")' not in txt:
    txt = txt.replace(marker, new_ep + marker, 1)
    f.write_text(txt)
    print('Confirm endpoint added.')
else:
    print('Confirm endpoint already exists.')
