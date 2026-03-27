from http.server import BaseHTTPRequestHandler
import json
import asyncio
from telegram import Update
from src.bot.main import build_application
import os

bot_instance = None

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_len)
            update_data = json.loads(post_body)
            
            global bot_instance
            if bot_instance is None:
                bot_instance = build_application()
                
            # Create a new event loop for this webhook request
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            if not bot_instance._initialized:
                loop.run_until_complete(bot_instance.initialize())
                
            update = Update.de_json(update_data, bot_instance.bot)
            loop.run_until_complete(bot_instance.process_update(update))
            loop.close()
            
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode('utf-8'))

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Telegram Bot Webhook is Active on Vercel!")
