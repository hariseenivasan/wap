#!/usr/bin/env python3
"""
Example: Auto-Purge Old Media in a WhatsApp Group
Demonstrates how to clean heavy images and videos in a target group
after a configured retention period.

Usage:
    python auto_clean_group_media.py --group "Project Workspace" --hours 48
"""
import argparse
import sys
import requests

WAP_URL = "http://localhost:3001"

def clean_group_media(group_name: str, hours: int, delete_for_everyone: bool = False):
    print(f"[*] Checking WAP service status at {WAP_URL}...")
    try:
        status_res = requests.get(f"{WAP_URL}/api/status", timeout=5).json()
    except Exception as e:
        print(f"[!] Error: Could not connect to WAP service: {e}")
        sys.exit(1)

    if status_res.get("status") != "WORKING":
        print(f"[!] Session not ready. Current status: {status_res.get('status')}")
        sys.exit(1)

    print(f"[*] Scanning group '{group_name}' for media older than {hours} hours...")
    try:
        clean_res = requests.post(f"{WAP_URL}/api/maintenance/auto-clean-media", json={
            "chatId": group_name,
            "olderThanHours": hours,
            "deleteForEveryone": delete_for_everyone
        }, timeout=60).json()

        print(f"[+] Cleanup complete!")
        print(f"    Target Group   : {clean_res.get('chatId')}")
        print(f"    Items Deleted  : {clean_res.get('deletedCount', 0)}")
    except Exception as e:
        print(f"[!] Cleanup request failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge old media from WhatsApp groups via WAP")
    parser.add_argument("--group", required=True, help="Target Group Name or JID (e.g. 'Project Workspace')")
    parser.add_argument("--hours", type=int, default=48, help="Delete media older than this many hours (default: 48)")
    parser.add_argument("--delete-for-everyone", action="store_true", help="Attempt delete for everyone if admin")
    args = parser.parse_args()

    clean_group_media(args.group, args.hours, args.delete_for_everyone)
