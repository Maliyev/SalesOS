"""Focused SalesOS checks; no provider or production credentials needed."""
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from commerce import (CommerceError, add_to_cart, change_cart, confirm_order,
                      get_cart, list_orders, prepare_checkout, update_order_status)
from database import initialize_database, insert_incoming_message, save_model_message
from agent import get_agent_reply
from app_config import load_config, set_config


URL = 'https://www.elen.az/shop/2/desc/diode'
PRODUCT = dict(title='Diode', url=URL, price=0.1, currency='AZN', stock_quantity=50)


class CommerceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test.db'
        initialize_database(self.db)
        self.sid = 'telegram:123'
        self.fetch = Mock(return_value=PRODUCT.copy())
        set_config(load_config())

    def tearDown(self):
        set_config(None)
        self.temp.cleanup()

    def add(self, quantity=3):
        return add_to_cart(self.db, self.sid, URL, quantity, self.fetch)

    def quote(self, delivered=True):
        user_id = insert_incoming_message(self.db, self.sid, 'Checkout: Ali, +994501234567')
        summary = prepare_checkout(self.db, self.sid, user_id, 'Ali', '+994501234567', '', self.fetch)
        token = re.search(r'/confirm ([a-f0-9]+)', summary).group(1)
        if delivered:
            save_model_message(self.db, self.sid, summary)
        return token

    def test_cart_isolation_totals_and_mutations(self):
        cart = self.add()
        self.assertEqual(cart['total_amount'], '0.30')
        self.assertEqual(get_cart(self.db, 'telegram:456')['items'], [])
        item_id = cart['items'][0]['id']
        with self.assertRaises(CommerceError):
            change_cart(self.db, 'telegram:456', 'remove', item_id)
        cart = change_cart(self.db, self.sid, 'update', item_id, 7)
        self.assertEqual(cart['total_amount'], '0.70')
        self.assertEqual(change_cart(self.db, self.sid, 'remove', item_id)['items'], [])
        self.add()
        self.assertEqual(change_cart(self.db, self.sid, 'clear')['items'], [])

    def test_negative_quantity_missing_price_and_source_failure(self):
        for quantity in (-1, 0, True, 1000):
            with self.assertRaises(CommerceError): self.add(quantity)
        self.fetch.return_value = {**PRODUCT, 'price': None}
        with self.assertRaises(CommerceError): self.add()
        self.fetch.side_effect = RuntimeError('source unavailable')
        with self.assertRaises(RuntimeError): self.add()
        self.assertEqual(list_orders(self.db), [])

    def test_confirmation_requires_actual_command_and_delivered_summary(self):
        self.add()
        token = self.quote(delivered=False)
        message_id = insert_incoming_message(self.db, self.sid, f'/confirm {token}')
        with self.assertRaises(CommerceError): confirm_order(self.db, self.sid, message_id, token, self.fetch)
        token = self.quote()
        message_id = insert_incoming_message(self.db, self.sid, 'I want it')
        with self.assertRaises(CommerceError): confirm_order(self.db, self.sid, message_id, token, self.fetch)
        self.assertEqual(list_orders(self.db), [])

    def test_persistent_idempotent_checkout_and_fresh_cart(self):
        self.add()
        token = self.quote()
        message_id = insert_incoming_message(self.db, self.sid, f'/confirm {token}')
        order = confirm_order(self.db, self.sid, message_id, token, self.fetch)
        again_id = insert_incoming_message(self.db, self.sid, f'/confirm {token}')
        self.assertEqual(confirm_order(self.db, self.sid, again_id, token, self.fetch)['id'], order['id'])
        self.assertEqual(len(list_orders(self.db)), 1)
        self.assertEqual(order['total_amount'], '0.30')
        self.assertEqual(get_cart(self.db, self.sid)['items'], [])
        initialize_database(self.db)
        self.assertEqual(list_orders(self.db)[0]['items'][0]['quantity'], 3)
        self.assertEqual(update_order_status(self.db, order['id'], 'processing')['status'], 'processing')

    def test_cart_change_invalidates_quote(self):
        cart = self.add()
        token = self.quote()
        change_cart(self.db, self.sid, 'update', cart['items'][0]['id'], 4)
        message_id = insert_incoming_message(self.db, self.sid, f'/confirm {token}')
        with self.assertRaises(CommerceError): confirm_order(self.db, self.sid, message_id, token, self.fetch)

    def test_price_change_stock_and_foreign_session_rejected(self):
        self.add()
        token = self.quote()
        foreign = insert_incoming_message(self.db, 'telegram:456', f'/confirm {token}')
        with self.assertRaises(CommerceError): confirm_order(self.db, self.sid, foreign, token, self.fetch)
        message_id = insert_incoming_message(self.db, self.sid, f'/confirm {token}')
        self.fetch.return_value = {**PRODUCT, 'price': 0.2}
        with self.assertRaises(CommerceError): confirm_order(self.db, self.sid, message_id, token, self.fetch)
        self.fetch.return_value = {**PRODUCT, 'stock_quantity': 0}
        with self.assertRaises(CommerceError): confirm_order(self.db, self.sid, message_id, token, self.fetch)
        self.assertEqual(list_orders(self.db), [])

    def test_variant_price_and_stock_are_verified(self):
        self.fetch.return_value = dict(title='Part',url=URL,currency='AZN',variants=[dict(name='Red',price=0.2,stock_quantity=4)])
        with self.assertRaises(CommerceError): self.add()
        cart = add_to_cart(self.db,self.sid,URL,3,self.fetch,'Red')
        self.assertEqual(cart['total_amount'],'0.60')
        with self.assertRaises(CommerceError): add_to_cart(self.db,self.sid,URL,2,self.fetch,'Red')

    def test_superseded_turn_retry_does_not_add_the_same_item_twice(self):
        user_id=insert_incoming_message(self.db,self.sid,'Add three diodes')
        first=add_to_cart(self.db,self.sid,URL,3,self.fetch,message_id=user_id)
        again=add_to_cart(self.db,self.sid,URL,3,self.fetch,message_id=user_id)
        self.assertEqual(again,first)
        self.assertEqual(get_cart(self.db,self.sid)['items'][0]['quantity'],3)
        next_id=insert_incoming_message(self.db,self.sid,'Add three more')
        add_to_cart(self.db,self.sid,URL,3,self.fetch,message_id=next_id)
        self.assertEqual(get_cart(self.db,self.sid)['items'][0]['quantity'],6)

    def test_direct_checkout_without_confirmation_and_retry(self):
        from commerce import place_order
        self.add()
        user_id=insert_incoming_message(self.db,self.sid,'Checkout: Ali +994501234567')
        order=place_order(self.db,self.sid,user_id,'Ali','+994501234567','',self.fetch)
        self.assertEqual(order['total_amount'],'0.30')
        self.assertEqual(len(list_orders(self.db)),1)
        self.assertEqual(place_order(self.db,self.sid,user_id,'Ali','+994501234567','',self.fetch)['id'],order['id'])
        self.assertEqual(len(list_orders(self.db)),1)
        self.assertEqual(get_cart(self.db,self.sid)['items'],[])

    def test_direct_checkout_requires_contact_and_actual_session(self):
        from commerce import place_order
        self.add()
        user_id=insert_incoming_message(self.db,self.sid,'Checkout')
        with self.assertRaises(CommerceError): place_order(self.db,self.sid,user_id,'Ali','','',self.fetch)
        foreign=insert_incoming_message(self.db,'telegram:456','Checkout')
        with self.assertRaises(CommerceError): place_order(self.db,self.sid,foreign,'Ali','+994501234567','',self.fetch)
        self.assertEqual(list_orders(self.db),[])

    def test_agent_shopping_tool_and_confirmation_without_llm(self):
        user_id = insert_incoming_message(self.db,self.sid,'Add three diodes')
        model = Mock(side_effect=[
            {'candidates':[{'content':{'parts':[{'functionCall':{'name':'add_to_cart','args':dict(product_url=URL,quantity=3)}}]}}]},
            {'candidates':[{'content':{'parts':[{'text':'Added three diodes.'}]}}]},
        ])
        reply = get_agent_reply([], 'Add three diodes', 'test', 'key', 'rules', 'select', 'respond',
            database_path=self.db,session_id=self.sid,in_reply_to_message_id=user_id,
            product_data_fn=self.fetch,generate_fn=model)
        self.assertEqual(reply.customer_reply,'Added three diodes.')
        declarations = model.call_args_list[0].kwargs['tools'][0]['functionDeclarations']
        self.assertNotIn('request_operator', [tool['name'] for tool in declarations])
        self.assertIn('add_to_cart', [tool['name'] for tool in declarations])
        self.assertEqual(get_cart(self.db,self.sid)['total_amount'],'0.30')
        token = self.quote()
        user_id = insert_incoming_message(self.db,self.sid,f'/confirm {token}')
        model.reset_mock()
        reply = get_agent_reply([],f'/confirm {token}','test','key','rules','select','respond',
            database_path=self.db,session_id=self.sid,in_reply_to_message_id=user_id,
            product_data_fn=self.fetch,generate_fn=model)
        self.assertIn('Order #1',reply.customer_reply)
        model.assert_not_called()

    def test_orders_visible_and_protected_in_control_panel(self):
        from admin_dashboard import create_admin_app
        with patch.dict('os.environ', ADMIN_PASSWORD='test-password', ADMIN_SESSION_SECRET='x'*40):
            app = create_admin_app(self.db,send_fn=lambda *args: None)
        client = app.test_client()
        self.assertEqual(client.get('/admin/api/orders').status_code,401)
        with client.session_transaction() as session:
            session['admin_authenticated']=True
            session['csrf_token']='test-csrf'
        self.add(); token=self.quote()
        user_id=insert_incoming_message(self.db,self.sid,f'/confirm {token}')
        confirm_order(self.db,self.sid,user_id,token,self.fetch)
        self.assertEqual(client.get('/admin/api/orders').get_json()['orders'][0]['total_amount'],'0.30')
        self.assertEqual(client.get('/admin/api/overview').get_json()['orders']['order_count'],1)
        self.assertEqual(client.put('/admin/api/orders/1',json=dict(status='completed')).status_code,403)
        self.assertEqual(client.put('/admin/api/orders/1',json=dict(status='completed'),headers={'X-CSRF-Token':'test-csrf'}).status_code,200)

    def test_function_call_id_and_thought_signature_are_preserved(self):
        from agent import _append_search_turns
        part = {'functionCall': {'name': 'search_products', 'id': 'call-123', 'args': {'query': 'diode'}}, 'thoughtSignature': 'signature'}
        turns = _append_search_turns([], [(part, [])])
        self.assertEqual(turns[0]['parts'][0]['thoughtSignature'], 'signature')
        self.assertEqual(turns[1]['parts'][0]['functionResponse']['id'], 'call-123')

    def test_confirm_command_reaches_telegram_session(self):
        from telegram_bot import handle_update
        submit = Mock()
        handle_update({'message': {'chat': {'id':123}, 'text':'/confirm abc123'}},submit,Mock(),Mock())
        submit.assert_called_once_with('telegram:123','/confirm abc123',123)

    def test_telegram_runner_starts_without_whatsapp_credentials(self):
        import runner
        telegram = Mock()
        with patch.dict('os.environ', {
            'GEMINI_API_KEY':'test-key','TELEGRAM_BOT_TOKEN':'test-token',
            'ADMIN_PASSWORD':'test-password','ADMIN_SESSION_SECRET':'x'*40,
            'SALESOS_DATABASE_PATH':str(self.db)}, clear=True), \
             patch.object(runner,'load_env_file'), \
             patch.object(runner,'configure_logging'), \
             patch.object(runner,'build_telegram_channel',return_value=telegram), \
             patch.object(runner,'get_whatsapp_settings') as whatsapp_settings, \
             patch.object(runner,'build_whatsapp_channel') as whatsapp_channel, \
             patch.object(runner.threading,'Thread'), \
             patch.object(runner.threading,'Event') as event:
            event.return_value.wait.side_effect=KeyboardInterrupt
            runner.main()
        telegram.start.assert_called_once()
        telegram.stop.assert_called_once()
        whatsapp_settings.assert_not_called()
        whatsapp_channel.assert_not_called()


if __name__ == '__main__':
    unittest.main()
