"""Session-bound shopping state. Money is stored as integer minor units.

Checkout uses a delivered summary followed by an authenticated /confirm token.
The model cannot provide a session ID, a price, or confirmation evidence.
"""
import json
import re
import secrets
from decimal import Decimal, InvalidOperation

from database import run_database_operation, validate_session_id


class CommerceError(ValueError):
    pass


def migration_007_commerce(connection):
    statements = (
        """CREATE TABLE carts (
            id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','checked_out')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            pending_token TEXT, pending_json TEXT, prepared_message_id INTEGER REFERENCES messages(id))""",
        "CREATE UNIQUE INDEX active_cart_per_session ON carts(session_id) WHERE status = 'active'",
        """CREATE TABLE cart_items (
            id INTEGER PRIMARY KEY, cart_id INTEGER NOT NULL REFERENCES carts(id),
            product_name TEXT NOT NULL, product_url TEXT NOT NULL,
            variant_name TEXT NOT NULL DEFAULT '', unit_price INTEGER NOT NULL CHECK(unit_price >= 0),
            quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 999),
            currency TEXT NOT NULL DEFAULT 'AZN', UNIQUE(cart_id, product_url, variant_name))""",
        """CREATE TABLE orders (
            id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
            cart_id INTEGER NOT NULL UNIQUE REFERENCES carts(id),
            customer_name TEXT NOT NULL, customer_phone TEXT NOT NULL, delivery_address TEXT,
            items_json TEXT NOT NULL, total_amount INTEGER NOT NULL, currency TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','processing','completed','cancelled')),
            confirmation_token TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE INDEX orders_by_session ON orders(session_id, id)",
    )
    for statement in statements:
        connection.execute(statement)


def minor_units(value):
    if value is None or isinstance(value, bool):
        raise CommerceError('A verified price is required.')
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal('10000000'):
            raise CommerceError('Invalid product price.')
        minor = amount * 100
        if minor != minor.to_integral_value():
            raise CommerceError('Price must have at most two decimal places.')
        return int(minor)
    except (InvalidOperation, ValueError) as error:
        raise CommerceError('Invalid or missing product price.') from error


def money(value):
    return format(Decimal(value) / 100, '.2f')


def _quantity(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 999:
        raise CommerceError('Quantity must be an integer from 1 to 999.')
    return value


def _cart(connection, session_id, create=True):
    validate_session_id(session_id)
    row = connection.execute("SELECT * FROM carts WHERE session_id=? AND status='active'", (session_id,)).fetchone()
    if row is None and create:
        connection.execute('INSERT OR IGNORE INTO sessions(session_id) VALUES (?)', (session_id,))
        connection.execute('INSERT INTO carts(session_id) VALUES (?)', (session_id,))
        row = connection.execute("SELECT * FROM carts WHERE session_id=? AND status='active'", (session_id,)).fetchone()
    return row


def _snapshot(connection, cart):
    rows = connection.execute('SELECT * FROM cart_items WHERE cart_id=? ORDER BY id', (cart['id'],)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item['unit_price_minor'] = item.pop('unit_price')
        item['line_total_minor'] = item['unit_price_minor'] * item['quantity']
        item['unit_price'] = money(item['unit_price_minor'])
        item['line_total'] = money(item['line_total_minor'])
        items.append(item)
    total = sum(item['line_total_minor'] for item in items)
    return dict(id=cart['id'], items=items, total_minor=total, total_amount=money(total),
                currency=items[0]['currency'] if items else 'AZN')


def _invalidate(connection, cart_id):
    connection.execute('UPDATE carts SET pending_token=NULL, pending_json=NULL, prepared_message_id=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?', (cart_id,))


def get_cart(database_path, session_id):
    def read(connection):
        connection.execute('BEGIN IMMEDIATE')
        return _snapshot(connection, _cart(connection, session_id))
    return run_database_operation(database_path, read)


def _verified_product(product, variant_name, quantity):
    if not isinstance(product, dict) or not product.get('title') or not product.get('url'):
        raise CommerceError('Product source did not return a valid product.')
    facts = product
    if product.get('variants'):
        facts = next((item for item in product['variants'] if item['name'] == variant_name), None)
        if facts is None:
            raise CommerceError('Select an exact verified variant name first.')
    elif variant_name:
        raise CommerceError('This product has no verified variant with that name.')
    stock = facts.get('stock_quantity')
    if stock is not None and stock < quantity:
        raise CommerceError('Requested quantity exceeds verified stock.')
    return minor_units(facts.get('price')), product.get('currency') or 'AZN'


def add_to_cart(database_path, session_id, product_url, quantity, product_data_fn, variant_name='', message_id=None):
    _quantity(quantity)
    product = product_data_fn(product_url)
    price, currency = _verified_product(product, variant_name, quantity)
    def add(connection):
        connection.execute('BEGIN IMMEDIATE')
        arguments_json = json.dumps(dict(product_url=product_url,quantity=quantity,variant_name=variant_name),sort_keys=True)
        if message_id is not None:
            _user_turn(connection, session_id, message_id)
            receipt = connection.execute("""SELECT result_json FROM tool_calls WHERE session_id=? AND message_id=?
                AND tool_name='add_to_cart' AND arguments_json=? AND status='succeeded' LIMIT 1""",
                (session_id,message_id,arguments_json)).fetchone()
            if receipt is not None:
                return json.loads(receipt['result_json'])
        cart = _cart(connection, session_id)
        existing = connection.execute('SELECT quantity FROM cart_items WHERE cart_id=? AND product_url=? AND variant_name=?', (cart['id'], product_url, variant_name)).fetchone()
        combined = quantity + (existing['quantity'] if existing else 0)
        _quantity(combined)
        _verified_product(product, variant_name, combined)
        other = connection.execute('SELECT currency FROM cart_items WHERE cart_id=? LIMIT 1', (cart['id'],)).fetchone()
        if other and other['currency'] != currency:
            raise CommerceError('A cart cannot mix currencies.')
        connection.execute('''INSERT INTO cart_items(cart_id,product_name,product_url,variant_name,unit_price,quantity,currency)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(cart_id,product_url,variant_name)
            DO UPDATE SET quantity=excluded.quantity, unit_price=excluded.unit_price''',
            (cart['id'], product['title'], product_url, variant_name, price, combined, currency))
        _invalidate(connection, cart['id'])
        result = _snapshot(connection, cart)
        if message_id is not None:
            connection.execute("""INSERT INTO tool_calls(session_id,message_id,tool_name,arguments_json,result_json,status,finished_at)
                VALUES (?,?,'add_to_cart',?,?,'succeeded',CURRENT_TIMESTAMP)""",
                (session_id,message_id,arguments_json,json.dumps(result,ensure_ascii=False)))
        return result
    return run_database_operation(database_path, add)


def change_cart(database_path, session_id, action, item_id=None, quantity=None):
    if action not in ('update', 'remove', 'clear'):
        raise CommerceError('Unknown cart operation.')
    if action == 'update':
        _quantity(quantity)
    if action != 'clear' and (isinstance(item_id, bool) or not isinstance(item_id, int)):
        raise CommerceError('Use the item ID returned by get_cart.')
    def change(connection):
        connection.execute('BEGIN IMMEDIATE')
        cart = _cart(connection, session_id)
        if action == 'clear':
            connection.execute('DELETE FROM cart_items WHERE cart_id=?', (cart['id'],))
        else:
            item = connection.execute('SELECT id FROM cart_items WHERE cart_id=? AND id=?', (cart['id'], item_id)).fetchone()
            if item is None:
                raise CommerceError('Item not found in this session cart.')
            if action == 'update':
                connection.execute('UPDATE cart_items SET quantity=? WHERE id=?', (quantity, item_id))
            else:
                connection.execute('DELETE FROM cart_items WHERE id=?', (item_id,))
        _invalidate(connection, cart['id'])
        return _snapshot(connection, cart)
    return run_database_operation(database_path, change)


def _recheck(items, product_data_fn):
    warnings = []
    for item in items:
        try:
            product = product_data_fn(item['product_url'])
        except (RuntimeError, ValueError, OSError) as error:
            warnings.append(f"{item['product_name']}: source unavailable; merchant must verify price/stock.")
            continue
        price, currency = _verified_product(product, item['variant_name'], item['quantity'])
        if price != item['unit_price_minor'] or currency != item['currency']:
            raise CommerceError('Price changed. Remove and add the item again, then request a new checkout summary.')
        facts = next((v for v in product.get('variants', []) if v['name'] == item['variant_name']), product)
        if facts.get('stock_quantity') is None:
            warnings.append(f"{item['product_name']}: stock is unconfirmed; merchant must verify it.")
    return warnings


def _user_turn(connection, session_id, message_id):
    row = connection.execute("SELECT * FROM messages WHERE id=? AND session_id=? AND role='user' AND archived=0", (message_id, session_id)).fetchone()
    if row is None:
        raise CommerceError('Checkout requires an authenticated customer message.')
    return row


def prepare_checkout(database_path, session_id, message_id, customer_name, customer_phone,
                     delivery_address, product_data_fn):
    if not isinstance(customer_name, str) or not customer_name.strip() or len(customer_name) > 150:
        raise CommerceError('Ask for the customer name.')
    if (not isinstance(customer_phone, str) or not re.fullmatch(r'\+?[0-9 ()-]{7,30}', customer_phone)
            or not 7 <= len(re.sub(r'\D', '', customer_phone)) <= 15):
        raise CommerceError('Ask for a valid customer phone number.')
    if not isinstance(delivery_address, str) or len(delivery_address) > 1000:
        raise CommerceError('Invalid delivery address.')
    cart = get_cart(database_path, session_id)
    if not cart['items']:
        raise CommerceError('The cart is empty.')
    warnings = _recheck(cart['items'], product_data_fn)
    token = secrets.token_hex(6)
    snapshot = {**cart, 'customer_name': customer_name.strip(), 'customer_phone': customer_phone.strip(),
                'delivery_address': delivery_address.strip(), 'warnings': warnings}
    def prepare(connection):
        connection.execute('BEGIN IMMEDIATE')
        _user_turn(connection, session_id, message_id)
        active = _cart(connection, session_id)
        if _snapshot(connection, active) != cart:
            raise CommerceError('Cart changed. Request a new checkout summary.')
        connection.execute('UPDATE carts SET pending_token=?,pending_json=?,prepared_message_id=? WHERE id=?',
                           (token, json.dumps(snapshot, ensure_ascii=False), message_id, cart['id']))
    run_database_operation(database_path, prepare)
    lines = ['Заказ / Sifariş / Order:']
    for item in cart['items']:
        variant = f" ({item['variant_name']})" if item['variant_name'] else ''
        lines.append(f"{item['product_name']}{variant}: {item['quantity']} × {item['unit_price']} = {item['line_total']} {cart['currency']}")
        lines.append(item['product_url'])
    lines.extend([f"Итого / Cəmi / Total: {cart['total_amount']} {cart['currency']}",
                  f"{snapshot['customer_name']} · {snapshot['customer_phone']}",
                  snapshot['delivery_address'] or 'Самовывоз / Pickup',
                  'Доставка и оплата уточняются продавцом. / Delivery and payment are arranged by the merchant.',
                  *warnings,
                  'Для подтверждения отправьте команду ниже. Это заявка продавцу, без оплаты.',
                  'Təsdiqləmək üçün aşağıdakı əmri göndərin. Ödəniş tutulmur.',
                  'To confirm, send the command below. Recorded for manual fulfillment; no payment is taken.',
                  f'/confirm {token}'])
    return '\n'.join(lines)


def confirm_order(database_path, session_id, message_id, token, product_data_fn):
    def pending(connection):
        _user_turn(connection, session_id, message_id)
        return connection.execute('SELECT * FROM carts WHERE session_id=? AND pending_token=?', (session_id, token)).fetchone()
    cart = run_database_operation(database_path, pending)
    if cart is None:
        raise CommerceError('No matching checkout. Request a new checkout summary.')
    snapshot = json.loads(cart['pending_json'])
    # Avoid network work on repeated confirmation after successful checkout.
    warnings = _recheck(snapshot['items'], product_data_fn) if cart['status'] == 'active' else []
    def confirm(connection):
        connection.execute('BEGIN IMMEDIATE')
        user = _user_turn(connection, session_id, message_id)
        if user['text'].strip() != f'/confirm {token}':
            raise CommerceError('Send the exact /confirm command from the checkout summary.')
        existing = connection.execute('SELECT * FROM orders WHERE session_id=? AND confirmation_token=?', (session_id, token)).fetchone()
        if existing:
            return _order(existing)
        active = _cart(connection, session_id, create=False)
        if active is None or active['pending_token'] != token:
            raise CommerceError('Checkout was invalidated. Request a new summary.')
        summary = connection.execute("""SELECT id FROM messages WHERE session_id=? AND role='model'
            AND status='DELIVERED' AND archived=0 AND id>? AND id<? AND instr(text,?)>0 ORDER BY id DESC LIMIT 1""",
            (session_id, active['prepared_message_id'], message_id, f'/confirm {token}')).fetchone()
        if summary is None:
            raise CommerceError('The checkout summary must be delivered before confirmation.')
        current = _snapshot(connection, active)
        if any(current[key] != snapshot[key] for key in ('items','total_minor','currency')):
            raise CommerceError('Cart changed. Request a new summary.')
        cursor = connection.execute('''INSERT INTO orders(session_id,cart_id,customer_name,customer_phone,
            delivery_address,items_json,total_amount,currency,confirmation_token) VALUES (?,?,?,?,?,?,?,?,?)''',
            (session_id, active['id'], snapshot['customer_name'], snapshot['customer_phone'],
             snapshot['delivery_address'], json.dumps(snapshot['items'], ensure_ascii=False),
             snapshot['total_minor'], snapshot['currency'], token))
        connection.execute("UPDATE carts SET status='checked_out',updated_at=CURRENT_TIMESTAMP WHERE id=?", (active['id'],))
        return _order(connection.execute('SELECT * FROM orders WHERE id=?', (cursor.lastrowid,)).fetchone())
    result = run_database_operation(database_path, confirm)
    result['warnings'] = warnings
    return result


def place_order(database_path, session_id, message_id, customer_name, customer_phone,
                delivery_address, product_data_fn):
    """Record checkout directly; merchant fulfills it manually. Retry-safe per user turn."""
    def receipt(connection):
        _user_turn(connection, session_id, message_id)
        row = connection.execute("""SELECT result_json FROM tool_calls WHERE session_id=? AND message_id=?
            AND tool_name='place_order' AND status='succeeded' LIMIT 1""", (session_id,message_id)).fetchone()
        return json.loads(row['result_json']) if row else None
    previous = run_database_operation(database_path, receipt)
    if previous is not None:
        return previous
    # Reuse contact validation and price/stock recheck; no summary needs to be sent.
    prepare_checkout(database_path,session_id,message_id,customer_name,customer_phone,
                     delivery_address,product_data_fn)
    def save(connection):
        connection.execute('BEGIN IMMEDIATE')
        previous = receipt(connection)
        if previous is not None:
            return previous
        cart = _cart(connection,session_id,create=False)
        if cart is None or cart['prepared_message_id'] != message_id or not cart['pending_json']:
            raise CommerceError('Cart changed. Request checkout again.')
        snapshot = json.loads(cart['pending_json'])
        current = _snapshot(connection,cart)
        if any(current[key] != snapshot[key] for key in ('items','total_minor','currency')):
            raise CommerceError('Cart changed. Request checkout again.')
        cursor = connection.execute('''INSERT INTO orders(session_id,cart_id,customer_name,customer_phone,
            delivery_address,items_json,total_amount,currency,confirmation_token) VALUES (?,?,?,?,?,?,?,?,?)''',
            (session_id,cart['id'],snapshot['customer_name'],snapshot['customer_phone'],snapshot['delivery_address'],
             json.dumps(snapshot['items'],ensure_ascii=False),snapshot['total_minor'],snapshot['currency'],cart['pending_token']))
        connection.execute("UPDATE carts SET status='checked_out',updated_at=CURRENT_TIMESTAMP WHERE id=?",(cart['id'],))
        result = _order(connection.execute('SELECT * FROM orders WHERE id=?',(cursor.lastrowid,)).fetchone())
        result['warnings'] = snapshot['warnings']
        connection.execute("""INSERT INTO tool_calls(session_id,message_id,tool_name,result_json,status,finished_at)
            VALUES (?,?,'place_order',?,'succeeded',CURRENT_TIMESTAMP)""",(session_id,message_id,json.dumps(result,ensure_ascii=False)))
        return result
    return run_database_operation(database_path,save)


def _order(row):
    data = dict(row)
    data['items'] = json.loads(data.pop('items_json'))
    data['total_minor'] = data.pop('total_amount')
    data['total_amount'] = money(data['total_minor'])
    data['item_count'] = sum(item['quantity'] for item in data['items'])
    data.pop('confirmation_token', None)
    return data


def list_orders(database_path):
    return run_database_operation(database_path, lambda connection: [_order(row) for row in
        connection.execute('SELECT * FROM orders ORDER BY id DESC LIMIT 200')])


def get_order(database_path, order_id):
    def read(connection):
        row = connection.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if row is None:
            raise CommerceError('Order not found.')
        return _order(row)
    return run_database_operation(database_path, read)


def update_order_status(database_path, order_id, status):
    if status not in ('new','processing','completed','cancelled'):
        raise CommerceError('Invalid order status.')
    def update(connection):
        cursor = connection.execute('UPDATE orders SET status=? WHERE id=?', (status, order_id))
        if not cursor.rowcount:
            raise CommerceError('Order not found.')
    run_database_operation(database_path, update)
    return get_order(database_path, order_id)


def order_metrics(database_path):
    def read(connection):
        groups = []
        for row in connection.execute("SELECT currency,COUNT(*) AS count,COALESCE(SUM(total_amount),0) AS total FROM orders WHERE status!='cancelled' GROUP BY currency"):
            groups.append(dict(currency=row['currency'], count=row['count'], total_amount=money(row['total'])))
        count = connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        item_count = sum(sum(item['quantity'] for item in json.loads(row[0])) for row in connection.execute('SELECT items_json FROM orders'))
        return dict(order_count=count, item_count=item_count, totals=groups)
    return run_database_operation(database_path, read)


def _declaration(name, description, properties=None, required=None):
    return dict(name=name, description=description,
                parameters=dict(type='OBJECT', properties=properties or {}, required=required or []))


COMMERCE_DECLARATIONS = [
    _declaration('get_cart', 'Read the current customer cart; use its item IDs for updates.'),
    _declaration('add_to_cart', 'Add a customer-requested product. Server fetches price and stock. Never invent a URL or variant.',
        dict(product_url=dict(type='STRING'), quantity=dict(type='INTEGER'), variant_name=dict(type='STRING')),
        ['product_url','quantity']),
    _declaration('update_cart_item', 'Set a cart item quantity.', dict(item_id=dict(type='INTEGER'),quantity=dict(type='INTEGER')), ['item_id','quantity']),
    _declaration('remove_from_cart', 'Remove a customer-requested cart item.', dict(item_id=dict(type='INTEGER')), ['item_id']),
    _declaration('clear_cart', 'Clear the cart only on customer request.'),
    _declaration('place_order', 'When the customer asks to checkout and name/phone are available, immediately save the cart as a merchant order. No extra confirmation command. Do not call merely for adding to cart.',
        dict(customer_name=dict(type='STRING'),customer_phone=dict(type='STRING'),delivery_address=dict(type='STRING')), ['customer_name','customer_phone']),
]


def execute_tool(database_path, session_id, message_id, name, args, product_data_fn):
    if not isinstance(args, dict):
        raise CommerceError('Invalid tool arguments.')
    if name == 'get_cart':
        return get_cart(database_path, session_id)
    if name == 'place_order':
        return place_order(database_path,session_id,message_id,args.get('customer_name'),args.get('customer_phone'),args.get('delivery_address',''),product_data_fn)
    if name == 'add_to_cart':
        return add_to_cart(database_path, session_id, args.get('product_url'), args.get('quantity'), product_data_fn, args.get('variant_name',''), message_id=message_id)
    if name in ('update_cart_item','remove_from_cart','clear_cart'):
        action = {'update_cart_item':'update','remove_from_cart':'remove','clear_cart':'clear'}[name]
        return change_cart(database_path, session_id, action, args.get('item_id'), args.get('quantity'))
    if name == 'prepare_checkout':
        return prepare_checkout(database_path, session_id, message_id, args.get('customer_name'), args.get('customer_phone'), args.get('delivery_address',''), product_data_fn)
    if name == 'confirm_order':
        return confirm_order(database_path, session_id, message_id, args.get('token'), product_data_fn)
    raise CommerceError('Unknown shopping tool.')
