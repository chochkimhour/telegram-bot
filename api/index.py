from http.server import BaseHTTPRequestHandler
import json
import asyncio
from telegram import Update
from src.bot.main import build_application
import os

app = None

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_len)
            update_data = json.loads(post_body)
            
            global app
            if app is None:
                app = build_application()
                
            # Create a new event loop for this webhook request
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            if not app._initialized:
                loop.run_until_complete(app.initialize())
                
            update = Update.de_json(update_data, app.bot)
            loop.run_until_complete(app.process_update(update))
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
