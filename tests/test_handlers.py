import asyncio
import unittest
from src.bot.handlers import rate_limit_exceeded, reply_in_chunks


class FakeMessage:
    def __init__(self):
        self.chunks = []

    async def reply_text(self, text, reply_markup=None):
        self.chunks.append((text, reply_markup))


class HandlerTests(unittest.TestCase):
    def test_rate_limit_allows_twenty_requests(self):
        user_id = 910001
        for _ in range(20):
            self.assertFalse(rate_limit_exceeded(user_id))
        self.assertTrue(rate_limit_exceeded(user_id))

    def test_long_replies_are_split_and_keyboard_is_on_last_chunk(self):
        message = FakeMessage()
        keyboard = object()
        asyncio.run(reply_in_chunks(message, "a" * 8001, keyboard))
        self.assertEqual(len(message.chunks), 3)
        self.assertTrue(all(len(chunk[0]) <= 3900 for chunk in message.chunks))
        self.assertIsNone(message.chunks[0][1])
        self.assertIs(message.chunks[-1][1], keyboard)


if __name__ == "__main__":
    unittest.main()
