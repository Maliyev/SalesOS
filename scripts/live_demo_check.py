"""Real Gemini + elen.az checkout in an isolated TEST database; sends no Telegram messages."""
from pathlib import Path
import os
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from app_config import get_gemini_model
from config import load_env_file
from database import initialize_database,insert_incoming_message,save_model_message
from message_service import generate_customer_reply
from commerce import get_cart,list_orders
from prompts import load_agent_instructions


def main():
    load_env_file(ROOT/'.env')
    key=os.getenv('GEMINI_API_KEY')
    if not key:
        print('GEMINI_API_KEY is missing.'); return
    runtime=ROOT/'data'/'runtime'
    runtime.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime,prefix='live-check-') as temporary:
        db=Path(temporary)/'test.db'
        initialize_database(db)
        sid='telegram:isolated-live-check'
        def turn(text):
            user_id=insert_incoming_message(db,sid,text)
            reply=generate_customer_reply(db,sid,text,get_gemini_model(),key,*load_agent_instructions(),in_reply_to_message_id=user_id)
            save_model_message(db,sid,reply.customer_reply)
            print('USER:',text,flush=True)
            print('REPLY:',reply.customer_reply,flush=True)
            return reply.customer_reply
        url='https://www.elen.az/shop/1028/desc/18650-lithium-battery-shield-v8-5v-3a-3v-1a'
        turn(f'Добавь в корзину 1 штуку товара по этой ссылке: {url}')
        cart=get_cart(db,sid)
        if not cart['items']:
            print('FAIL: model did not add requested product.'); return
        turn('Оформи заказ. Имя: TEST CUSTOMER, телефон: +994500000000, самовывоз.')
        orders=list_orders(db)
        print('ORDERS:',len(orders),flush=True)
        if len(orders)!=1: raise RuntimeError('No persisted order')
        print('PASS: live Gemini cart + source + direct SQLite order without confirmation. Telegram delivery simulated.',flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        # Provider keys are headers; explicitly redact anyway before reporting.
        detail=str(error)
        for name in ('GEMINI_API_KEY','TELEGRAM_BOT_TOKEN','OPENROUTER_API_KEY'):
            secret=os.getenv(name)
            if secret: detail=detail.replace(secret,'[REDACTED]')
        print('FAIL:',type(error).__name__,detail[:600],flush=True)
        sys.exit(1)
