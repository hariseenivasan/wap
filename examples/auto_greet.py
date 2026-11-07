#!/usr/bin/env python3
"""
Example: Auto-Greet New WhatsApp Messages
Polls for unread conversations via WAP and automatically replies
to greeting keywords like 'hi', 'hello', 'hey'.

Usage:
    python auto_greet.py --interval 10
"""
import argparse
import time
import requests

WAP_URL = "http://localhost:3001"
GREETING_KEYWORDS = ["hi", "hello", "hey", "good morning", "good evening"]
GREETING_REPLY = "Hello! Thanks for reaching out. This is an automated response from WAP."

def poll_and_greet(interval_seconds: int = 10):
    print(f"[*] Starting WAP Auto-Greet Daemon (polling every {interval_seconds}s)...")
    replied_chats = set()

    while True:
        try:
            chats = requests.get(f"{WAP_URL}/api/chats", params={"unreadOnly": True}, timeout=10).json()
            for chat in chats:
                chat_id = chat.get("id")
                if not chat_id or chat_id in replied_chats:
                    continue

                messages = requests.get(f"{WAP_URL}/api/chats/{chat_id}/messages", params={"limit": 3}, timeout=10).json()
                if not messages:
                    continue

                last_msg = messages[-1]
                if not last_msg.get("isOutgoing"):
                    text_lower = last_msg.get("text", "").lower().strip()
                    if any(keyword in text_lower for keyword in GREETING_KEYWORDS):
                        print(f"[+] Greeting detected from '{chat_id}': '{last_msg.get('text')}'")
                        send_res = requests.post(f"{WAP_URL}/api/sendText", json={
                            "chatId": chat_id,
                            "text": GREETING_REPLY
                        }, timeout=20)
                        if send_res.status_code in (200, 201):
                            print(f"[✓] Sent auto-reply to '{chat_id}'")
                            replied_chats.add(chat_id)
        except Exception as e:
            print(f"[!] Error during polling cycle: {e}")

        time.sleep(interval_seconds)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-greet unread WhatsApp messages via WAP")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds")
    args = parser.parse_args()

    poll_and_greet(args.interval)
