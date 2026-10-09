"""Read-only provider/source check. Never prints credentials or token-bearing URLs."""
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import requests
from config import load_env_file
from app_config import get_gemini_model
from gemini import generate_content, get_text_response
from product_search import search_products
from product_parser import get_product_data


def main():
    load_env_file(ROOT / '.env')
    model = get_gemini_model()
    key = os.getenv('GEMINI_API_KEY')
    print('Configured model:', model)
    if key:
        try:
            response = requests.get('https://generativelanguage.googleapis.com/v1beta/models',
                                    headers={'x-goog-api-key': key}, timeout=15)
            print('Models endpoint HTTP:', response.status_code)
            if response.ok:
                names = [m['name'].removeprefix('models/') for m in response.json().get('models', [])]
                print('Requested model listed:', model in names)
                if model not in names:
                    print('Available Flash Lite models:', ', '.join(name for name in names if 'flash-lite' in name))
                else:
                    data = generate_content([dict(role='user',parts=[dict(text='Reply only OK')])],model,key,'Reply concisely.',timeout=20)
                    print('Gemini generation:', get_text_response(data))
        except Exception as error:
            print('Gemini check failed:', type(error).__name__)
    else:
        print('Gemini key is missing.')
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if token:
        try:
            response = requests.get(f'https://api.telegram.org/bot{token}/getMe',timeout=15)
            print('Telegram getMe HTTP:', response.status_code)
            if response.ok:
                username = response.json().get('result',{}).get('username')
                print('Telegram bot link:', f'https://t.me/{username}')
        except Exception as error:
            print('Telegram check failed:', type(error).__name__)
    else:
        print('Telegram token is missing.')
    try:
        products = search_products('ESP32',max_results=3)
        print('Live elen.az results:',len(products))
        print(json.dumps(products,ensure_ascii=False))
        if products:
            print('Verified product:',json.dumps(get_product_data(products[0]['url']),ensure_ascii=False))
    except Exception as error:
        print('Live source check failed:',type(error).__name__)


if __name__ == '__main__':
    main()
